"""Pytest-Fixtures fuer WP-01 (Reference Core Schema-Skelett) und WP-INFRA-1.

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

import asyncio
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

_PG_URL = os.environ.get("PROOFMED_TEST_PG_URL", "").strip()

# Dieses Modul kann im selben Prozess zweimal importiert werden (pytest laedt es
# als ``conftest``, die Tests importieren ``tests.conftest``). Der Pfad der
# SQLite-Testdatei wird deshalb ueber die Umgebung geteilt, damit BEIDE
# Instanzen dieselbe Datei zuruecksetzen.
_SQLITE_FILE_ENV = "PROOFMED_TEST_SQLITE_FILE"
if os.environ.get(_SQLITE_FILE_ENV):
    _SQLITE_FILE = Path(os.environ[_SQLITE_FILE_ENV])
    _TMP_DIR = _SQLITE_FILE.parent
else:
    _TMP_DIR = Path(tempfile.mkdtemp(prefix="proofmed_wp01_"))
    _SQLITE_FILE = _TMP_DIR / "wp01_test.db"
    os.environ[_SQLITE_FILE_ENV] = str(_SQLITE_FILE)

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
from sqlalchemy.orm import Session  # noqa: E402

from app.config import settings  # noqa: E402

IS_POSTGRES = settings.effective_sync_database_url.startswith("postgresql")
SYNC_URL = settings.effective_sync_database_url

LEGACY_TABLES: frozenset[str] = frozenset(
    {"goa_ziffern", "medical_claims", "claim_line_items", "encrypted_backups"}
)
UTC_NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)

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


def dispose_app_engine() -> None:
    """Schliesst gepoolte Verbindungen der Anwendungs-Engine (app.database.engine).

    Noetig, damit die SQLite-Testdatei unter Windows geloescht werden kann,
    nachdem Seed/Guard/TestClient die async Engine benutzt haben.
    """
    module = sys.modules.get("app.database")
    if module is None:
        return
    try:
        asyncio.run(module.engine.dispose())
    except Exception:  # pragma: no cover - Verbindungen anderer Event-Loops
        asyncio.run(module.engine.dispose(close=False))


def reset_database() -> None:
    """Bringt die Testdatenbank in einen leeren Zustand (alle Tabellen weg)."""
    dispose_app_engine()
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


# ---------------------------------------------------------------------------
# Gemeinsame Hilfsfunktionen (Legacy-Zustand, Struktur-Reflexion)
# ---------------------------------------------------------------------------


def legacy_metadata_tables() -> list[sa.Table]:
    """Die vier Legacy-Tabellen aus Base.metadata (registriert nur Legacy-Modelle)."""
    from app import models as legacy_models  # noqa: F401
    from app.database import Base

    return [Base.metadata.tables[name] for name in sorted(LEGACY_TABLES)]


def create_legacy_schema(engine: Engine) -> None:
    """Historischer Pfad: create_all() nur fuer die vier Legacy-Tabellen."""
    from app.database import Base

    Base.metadata.create_all(engine, tables=legacy_metadata_tables())


def seed_legacy_state(engine: Engine) -> dict[str, list]:
    """Legacy-Schema per create_all() + je eine Zeile in goa_ziffern/encrypted_backups."""
    from app.models.backup import EncryptedBackup
    from app.models.goa import GOAZiffer

    create_legacy_schema(engine)
    with Session(engine) as session:
        session.add(
            GOAZiffer(
                ziffer="TEST_X",
                title_official="TITLE_OFFICIAL_X",
                title_patient="TITLE_PATIENT_X",
                rule_time_minutes=1,
                exclusion_ziffern=[],
            )
        )
        session.add(
            EncryptedBackup(
                user_id_hash="hash_x",
                ciphertext_base64="Y2lwaGVy",
                iv_base64="aXY=",
                salt_base64="c2FsdA==",
                updated_at=UTC_NOW,
            )
        )
        session.commit()
    return legacy_snapshot(engine)


def legacy_snapshot(engine: Engine) -> dict[str, list]:
    insp = sa.inspect(engine)
    snapshot: dict[str, list] = {}
    with engine.connect() as conn:
        for name in sorted(LEGACY_TABLES):
            columns = [c["name"] for c in insp.get_columns(name)]
            rows = conn.execute(sa.text(f"SELECT * FROM {name} ORDER BY 1")).all()
            snapshot[name] = [columns, [tuple(r) for r in rows]]
    return snapshot


def _normalize_sql(text_: str | None) -> str:
    return " ".join((text_ or "").replace("\n", " ").split()).strip("()")


def reflect_structure(engine: Engine, table_names) -> dict:  # noqa: ANN001
    """Dialekt-neutrale, vergleichbare Strukturbeschreibung der Tabellen."""
    insp = sa.inspect(engine)
    structure: dict = {}
    for name in sorted(table_names):
        columns = []
        for col in insp.get_columns(name):
            default = col.get("default")
            columns.append(
                (
                    col["name"],
                    repr(col["type"]),
                    bool(col["nullable"]),
                    _normalize_sql(default) if default is not None else None,
                )
            )
        pk = tuple(insp.get_pk_constraint(name)["constrained_columns"])
        fks = sorted(
            (
                fk["name"],
                tuple(fk["constrained_columns"]),
                fk["referred_table"],
                tuple(fk["referred_columns"]),
                (fk.get("options") or {}).get("ondelete"),
            )
            for fk in insp.get_foreign_keys(name)
        )
        uniques = sorted(
            (uq["name"], tuple(uq["column_names"])) for uq in insp.get_unique_constraints(name)
        )
        checks = sorted(
            (ck["name"], _normalize_sql(ck["sqltext"])) for ck in insp.get_check_constraints(name)
        )
        indexes = sorted(
            (ix["name"], tuple(ix["column_names"]), bool(ix.get("unique")))
            for ix in insp.get_indexes(name)
        )
        structure[name] = {
            "columns": columns,
            "pk": pk,
            "fks": fks,
            "uniques": uniques,
            "checks": checks,
            "indexes": indexes,
        }
    return structure


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    """Datenbank nach ``alembic upgrade head`` (Legacy-Baseline + Reference Core)."""
    command.upgrade(alembic_cfg, "head")
    return engine


@pytest.fixture
def stamped_legacy_engine(engine: Engine) -> tuple[Engine, dict[str, list]]:
    """Pre-Alembic-Legacy-DB (create_all + Zeilen), per stamp-legacy gestempelt."""
    from app.schema_guard import stamp_legacy

    before = seed_legacy_state(engine)
    stamp_legacy()
    return engine, before


@pytest.fixture
def pg_only() -> None:
    if not IS_POSTGRES:
        pytest.skip("PostgreSQL-Integrationsfall: PROOFMED_TEST_PG_URL nicht gesetzt")
