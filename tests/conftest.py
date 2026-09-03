"""Pytest-Fixtures fuer WP-01 (Reference Core Schema-Skelett).

Wichtig: ``alembic/env.py`` liest die DB-URL aus ``app.config.settings``
(gecachter Singleton). Deshalb wird ``DATABASE_URL`` HIER gesetzt, bevor
irgendein ``app``-Modul importiert wird.

* Standard: isolierte temporaere SQLite-Datei (pro Test zurueckgesetzt).
* PostgreSQL: ``PROOFMED_TEST_PG_URL`` setzen (z.B. Wegwerf-Container);
  dann laeuft dieselbe Suite gegen diese Datenbank. Ohne die Variable werden
  die PostgreSQL-Faelle uebersprungen, nie stillschweigend als bestanden gewertet.

Die SQLite-Fremdschluesselpruefung (PRAGMA foreign_keys=ON) wird ausschliesslich
auf der Test-Engine aktiviert, niemals in ``app/database.py``.

Sicherheitsschranke (fail-closed): Der destruktive PostgreSQL-Reset laeuft NUR,
wenn die Ziel-URL einen lokalen Host UND den WP-01-Wegwerf-Datenbanknamen
(``proofmed_wp01`` bzw. Praefix ``proofmed_wp01_``) hat UND zusaetzlich
``PROOFMED_ALLOW_TEST_DB_RESET=YES`` gesetzt ist. Andernfalls wird VOR jedem
reflect/drop_all/DROP TYPE ein ``RuntimeError`` ausgeloest.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

_PG_URL = os.environ.get("PROOFMED_TEST_PG_URL", "").strip()
_TMP_DIR = Path(tempfile.mkdtemp(prefix="proofmed_wp01_"))
_SQLITE_FILE = _TMP_DIR / "wp01_test.db"

if _PG_URL:
    os.environ["DATABASE_URL"] = _PG_URL
else:
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_SQLITE_FILE.as_posix()}"

# Erst jetzt duerfen app-Module importiert werden.
import sqlalchemy as sa  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.engine import Engine, make_url  # noqa: E402

from app.config import settings  # noqa: E402

IS_POSTGRES = settings.effective_sync_database_url.startswith("postgresql")
SYNC_URL = settings.effective_sync_database_url

# --- WP-01 destructive-test safety guard (PostgreSQL) -------------------------
LOCAL_TEST_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})
TEST_DB_NAME = "proofmed_wp01"
TEST_DB_PREFIX = "proofmed_wp01_"
RESET_OPT_IN_VAR = "PROOFMED_ALLOW_TEST_DB_RESET"
RESET_OPT_IN_VALUE = "YES"


def assert_pg_reset_allowed(url: str, env: Mapping[str, str] | None = None) -> None:
    """Fail-closed Pruefung, ob ``url`` eine WP-01-Wegwerf-PostgreSQL-DB bezeichnet.

    Loest ``RuntimeError`` aus, wenn NICHT alle Bedingungen erfuellt sind:
    lokaler Host, Datenbankname ``proofmed_wp01`` / Praefix ``proofmed_wp01_``,
    und ``PROOFMED_ALLOW_TEST_DB_RESET=YES`` in ``env``. Fuehrt keinerlei
    Datenbankoperation aus.
    """
    environment: Mapping[str, str] = os.environ if env is None else env
    parsed = make_url(url)
    problems: list[str] = []

    if not parsed.drivername.startswith("postgresql"):
        problems.append(f"driver {parsed.drivername!r} is not PostgreSQL")

    host = (parsed.host or "").strip("[]").lower()
    if host not in LOCAL_TEST_HOSTS:
        problems.append(
            f"host {parsed.host!r} is not local (allowed: {', '.join(sorted(LOCAL_TEST_HOSTS))})"
        )

    database = parsed.database or ""
    if not (database == TEST_DB_NAME or database.startswith(TEST_DB_PREFIX)):
        problems.append(
            f"database {database!r} is not the WP-01 throwaway database "
            f"({TEST_DB_NAME!r} or prefix {TEST_DB_PREFIX!r})"
        )

    opt_in = environment.get(RESET_OPT_IN_VAR)
    if opt_in != RESET_OPT_IN_VALUE:
        problems.append(
            f"{RESET_OPT_IN_VAR}={opt_in!r} (explicit {RESET_OPT_IN_VALUE!r} required)"
        )

    if problems:
        raise RuntimeError(
            "WP-01 destructive-test safety check FAILED for PostgreSQL database "
            f"{parsed.render_as_string(hide_password=True)!r}: "
            + "; ".join(problems)
            + ". No reflect/drop_all/DROP TYPE was executed. Tests refuse to reset "
            "anything that is not a local proofmed_wp01 throwaway database with "
            f"{RESET_OPT_IN_VAR}={RESET_OPT_IN_VALUE}."
        )


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(_TMP_DIR, ignore_errors=True)


def _make_engine(enforce_fk: bool = True) -> Engine:
    engine = sa.create_engine(SYNC_URL, future=True)
    if not IS_POSTGRES and enforce_fk:

        @event.listens_for(engine, "connect")
        def _enable_sqlite_fk(dbapi_connection, _record):  # pragma: no cover - trivial
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def reset_database() -> None:
    """Bringt die Testdatenbank in einen leeren Zustand (alle Tabellen weg)."""
    if IS_POSTGRES:
        # Fail-closed: MUSS vor jeder destruktiven Operation (reflect, drop_all,
        # DROP TYPE) und vor dem Aufbau einer Engine stehen.
        assert_pg_reset_allowed(SYNC_URL)
        engine = _make_engine(enforce_fk=False)
        try:
            meta = sa.MetaData()
            meta.reflect(bind=engine)
            meta.drop_all(bind=engine)
            with engine.begin() as conn:
                # Legacy-Enum-Typ (claim_status) aus dem Legacy-Fixture aufraeumen.
                conn.execute(sa.text("DROP TYPE IF EXISTS claim_status"))
        finally:
            engine.dispose()
    else:
        if _SQLITE_FILE.exists():
            _SQLITE_FILE.unlink()


@pytest.fixture
def alembic_cfg() -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    return cfg


@pytest.fixture
def clean_db(alembic_cfg: Config) -> Iterator[Config]:
    """Leere Datenbank vor und nach dem Test."""
    reset_database()
    yield alembic_cfg
    reset_database()


@pytest.fixture
def engine(clean_db: Config) -> Iterator[Engine]:  # noqa: ARG001
    """Synchrone Engine mit SQLite-FK-Enforcement (nur im Test)."""
    eng = _make_engine(enforce_fk=True)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def migrated_engine(engine: Engine, alembic_cfg: Config) -> Engine:
    """Datenbank nach ``alembic upgrade head``."""
    command.upgrade(alembic_cfg, "head")
    return engine


@pytest.fixture
def pg_only() -> None:
    if not IS_POSTGRES:
        pytest.skip("PostgreSQL-Integrationsfall: PROOFMED_TEST_PG_URL nicht gesetzt")
