"""Schema-Guard: Alembic ist die einzige Schema-Autoritaet (WP-INFRA-1).

Zwei getrennte Verantwortlichkeiten:

1. **Runtime-Guard (nur lesend)** - ``verify_schema()`` / ``verify_schema_async()``:
   wird beim Anwendungsstart (``app.database.init_db``) ausgefuehrt und prueft
   fail-closed, dass die Datenbank exakt auf dem erwarteten Alembic-Head steht
   und alle verwalteten Tabellen (4 Legacy + 17 Reference Core) existieren.
   Der Guard erzeugt, stempelt, migriert oder veraendert NIEMALS etwas - auch
   die Tabelle ``alembic_version`` wird nur per ``SELECT`` gelesen (keine
   Alembic-Kommandos mit Seiteneffekten).

2. **Explizites Stampen (CLI)** - ``python -m app.schema_guard stamp-legacy``:
   bringt eine bestehende, vor Alembic per ``create_all()`` erzeugte Datenbank
   unter Alembic-Verwaltung, indem ``0000_legacy_baseline`` gestempelt wird.
   Das passiert NUR nach einem fail-closed Struktur-Preflight (Tabellen,
   Spalten, Typen, Nullability, PKs, FKs inkl. ON DELETE, Indizes, PostgreSQL-
   Enum ``claim_status``, keine Reference-Core-Tabelle, kein widerspruechlicher
   ``alembic_version``-Zustand). Jede Abweichung -> kein Stamp.

Nicht enthalten (bewusst): automatische Migration beim Start. Die
Migrationsausfuehrung (``alembic upgrade head``) ist eine Deployment-
Entscheidung ausserhalb der Anwendung.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import NullPool

from app.config import settings

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
ALEMBIC_SCRIPT_LOCATION = REPO_ROOT / "alembic"

LEGACY_BASELINE_REVISION = "0000_legacy_baseline"
ALEMBIC_VERSION_TABLE = "alembic_version"

LEGACY_TABLES: tuple[str, ...] = (
    "goa_ziffern",
    "encrypted_backups",
    "medical_claims",
    "claim_line_items",
)

# Namen der 17 Reference-Core-Tabellen (WP-01). Bewusst als Konstante, damit der
# Guard app.models.reference_core NICHT importiert (Laufzeit-Isolation, T11).
REFERENCE_CORE_TABLES: tuple[str, ...] = (
    "source_records",
    "patient_message_policies",
    "verification_records",
    "fee_schedule_editions",
    "reference_releases",
    "fee_calculation_rules",
    "factor_rules",
    "condition_groups",
    "billing_rules",
    "billing_rule_conditions",
    "goa_reference_entries",
    "billing_rule_codes",
    "reference_assertions",
    "assertion_dependencies",
    "analog_references",
    "audit_reference_snapshots",
    "audit_evidence_manifests",
)

MANAGED_TABLES: tuple[str, ...] = LEGACY_TABLES + REFERENCE_CORE_TABLES

CLAIM_STATUS_LABELS: tuple[str, ...] = ("PENDING", "PROCESSED_FLAGGED", "PROCESSED_CLEAN")

# Legacy-Indizes, die create_all() historisch erzeugt hat.
LEGACY_INDEXES: dict[str, dict[str, tuple[str, ...]]] = {
    "claim_line_items": {"ix_claim_line_items_claim_id": ("claim_id",)},
    "encrypted_backups": {"ix_encrypted_backups_user_id_hash": ("user_id_hash",)},
}


# ---------------------------------------------------------------------------
# Fehlerklassen (alle mit handlungsfaehiger Meldung)
# ---------------------------------------------------------------------------


class SchemaGuardError(RuntimeError):
    """Basisklasse: Datenbankschema entspricht nicht dem erwarteten Zustand."""


class SchemaNotInitialized(SchemaGuardError):
    """Keine Alembic-Revision und keine Legacy-Tabellen: Datenbank ist leer."""


class LegacyDatabaseNotStamped(SchemaGuardError):
    """Legacy-Tabellen vorhanden, aber kein Alembic-Stamp (pre-Alembic-Datenbank)."""


class SchemaVersionMismatch(SchemaGuardError):
    """alembic_version entspricht nicht dem erwarteten Head."""


class SchemaIncomplete(SchemaGuardError):
    """Revision korrekt, aber verwaltete Tabellen fehlen."""


class StampPreflightError(SchemaGuardError):
    """stamp-legacy verweigert: Struktur entspricht nicht der Legacy-Baseline."""


# ---------------------------------------------------------------------------
# Alembic-Metadaten (rein lesend)
# ---------------------------------------------------------------------------


def alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_SCRIPT_LOCATION))
    return cfg


def expected_head() -> str:
    """Liest den Head aus alembic/versions (keine Datenbankverbindung)."""
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    if head is None:
        raise SchemaGuardError("Alembic-Skriptverzeichnis enthaelt keinen Head.")
    return head


def read_current_revisions(conn: Connection) -> list[str]:
    """Liest alembic_version per SELECT. Leere Liste, wenn Tabelle fehlt/leer."""
    if not inspect(conn).has_table(ALEMBIC_VERSION_TABLE):
        return []
    rows = conn.execute(sa.text(f"SELECT version_num FROM {ALEMBIC_VERSION_TABLE}")).scalars()
    return [str(r) for r in rows]


# ---------------------------------------------------------------------------
# Runtime-Guard (nur lesend)
# ---------------------------------------------------------------------------


def verify_schema(conn: Connection) -> str:
    """Prueft fail-closed, dass die Datenbank auf dem erwarteten Head steht.

    Fuehrt ausschliesslich Inspector-Abfragen und ein SELECT aus. Gibt die
    verifizierte Revision zurueck oder loest eine SchemaGuardError-Subklasse aus.
    """
    head = expected_head()
    tables = set(inspect(conn).get_table_names())
    revisions = read_current_revisions(conn)

    if not revisions:
        if set(LEGACY_TABLES) <= tables:
            raise LegacyDatabaseNotStamped(
                "Datenbank enthaelt die Legacy-Tabellen, aber keinen Alembic-Stamp. "
                "Einmalig ausfuehren: `python -m app.schema_guard stamp-legacy` "
                "(fail-closed Preflight), danach `alembic upgrade head`."
            )
        raise SchemaNotInitialized(
            "Datenbankschema ist nicht initialisiert (keine Alembic-Revision). "
            "Ausfuehren: `alembic upgrade head`. Die Anwendung erzeugt kein Schema mehr."
        )

    if len(revisions) != 1 or revisions[0] != head:
        raise SchemaVersionMismatch(
            f"alembic_version={revisions!r}, erwartet {head!r}. "
            "Ausfuehren: `alembic upgrade head` (bzw. Deployment zurueckrollen)."
        )

    missing = [name for name in MANAGED_TABLES if name not in tables]
    if missing:
        raise SchemaIncomplete(
            f"Revision {head!r} ist gestempelt, aber es fehlen Tabellen: {missing}. "
            "Die Datenbank ist inkonsistent; Migrationen pruefen."
        )
    return head


def verify_schema_url(sync_url: str) -> str:
    engine = sa.create_engine(sync_url, poolclass=NullPool, future=True)
    try:
        with engine.connect() as conn:
            return verify_schema(conn)
    finally:
        engine.dispose()


async def verify_schema_async(engine: AsyncEngine) -> str:
    async with engine.connect() as conn:
        return await conn.run_sync(verify_schema)


# ---------------------------------------------------------------------------
# stamp-legacy: fail-closed Preflight + expliziter Stamp
# ---------------------------------------------------------------------------

_TYPE_ALIASES = {
    "DOUBLE PRECISION": "FLOAT",
    "FLOAT(53)": "FLOAT",
}


def _normalized_type(type_: sa.types.TypeEngine, dialect) -> str:  # noqa: ANN001
    compiled = " ".join(type_.compile(dialect=dialect).upper().split())
    return _TYPE_ALIASES.get(compiled, compiled)


def _normalized_ondelete(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.upper()
    return None if value == "NO ACTION" else value


def _legacy_model_tables() -> dict[str, sa.Table]:
    # Lazy import: nur die Legacy-Modelle (app.models importiert reference_core NICHT).
    from app import models  # noqa: F401
    from app.database import Base

    return {name: Base.metadata.tables[name] for name in LEGACY_TABLES}


def stamp_legacy_preflight(conn: Connection) -> None:
    """Sammelt ALLE Abweichungen und verweigert bei der kleinsten Unklarheit."""
    insp = inspect(conn)
    dialect = conn.dialect
    tables = set(insp.get_table_names())
    problems: list[str] = []

    # 1. Kein widerspruechlicher alembic_version-Zustand.
    revisions = read_current_revisions(conn)
    if revisions:
        problems.append(
            f"alembic_version enthaelt bereits {revisions!r}; ein Stamp ueber einen "
            "bestehenden Zustand ist nicht erlaubt"
        )

    # 2. Keine Reference-Core-Tabelle darf existieren.
    present_rc = sorted(set(REFERENCE_CORE_TABLES) & tables)
    if present_rc:
        problems.append(f"Reference-Core-Tabellen existieren bereits: {present_rc}")

    # 3. Alle vier Legacy-Tabellen muessen existieren.
    missing_tables = [name for name in LEGACY_TABLES if name not in tables]
    if missing_tables:
        problems.append(f"Legacy-Tabellen fehlen: {missing_tables}")

    # 4. Struktur jeder vorhandenen Legacy-Tabelle gegen das ORM-Modell.
    model_tables = _legacy_model_tables()
    for name in LEGACY_TABLES:
        if name in missing_tables:
            continue
        model = model_tables[name]
        actual_cols = {c["name"]: c for c in insp.get_columns(name)}
        expected_cols = {c.name: c for c in model.columns}

        missing_cols = sorted(set(expected_cols) - set(actual_cols))
        extra_cols = sorted(set(actual_cols) - set(expected_cols))
        if missing_cols:
            problems.append(f"{name}: Spalten fehlen {missing_cols}")
        if extra_cols:
            problems.append(f"{name}: unbekannte Spalten {extra_cols}")

        for col_name in sorted(set(expected_cols) & set(actual_cols)):
            expected_type = _normalized_type(expected_cols[col_name].type, dialect)
            actual_type = _normalized_type(actual_cols[col_name]["type"], dialect)
            if expected_type != actual_type:
                problems.append(
                    f"{name}.{col_name}: Typ {actual_type!r}, erwartet {expected_type!r}"
                )
            if bool(actual_cols[col_name]["nullable"]) != bool(expected_cols[col_name].nullable):
                problems.append(
                    f"{name}.{col_name}: nullable={actual_cols[col_name]['nullable']!r}, "
                    f"erwartet {expected_cols[col_name].nullable!r}"
                )
        # Server-Defaults werden bewusst NICHT verglichen (historische ALTER-Defaults
        # auf den acht goa_ziffern-Spalten sind toleriert und dokumentiert).

        actual_pk = tuple(insp.get_pk_constraint(name)["constrained_columns"])
        expected_pk = tuple(c.name for c in model.primary_key.columns)
        if actual_pk != expected_pk:
            problems.append(f"{name}: PK {actual_pk!r}, erwartet {expected_pk!r}")

        actual_fks = {
            (
                tuple(fk["constrained_columns"]),
                fk["referred_table"],
                tuple(fk["referred_columns"]),
                _normalized_ondelete((fk.get("options") or {}).get("ondelete")),
            )
            for fk in insp.get_foreign_keys(name)
        }
        expected_fks = {
            (
                tuple(c.name for c in fk.columns),
                fk.referred_table.name,
                tuple(e.column.name for e in fk.elements),
                _normalized_ondelete(fk.ondelete),
            )
            for fk in model.foreign_key_constraints
        }
        if actual_fks != expected_fks:
            problems.append(
                f"{name}: Fremdschluessel {sorted(actual_fks)!r}, "
                f"erwartet {sorted(expected_fks)!r}"
            )

        actual_ix = {ix["name"]: tuple(ix["column_names"]) for ix in insp.get_indexes(name)}
        expected_ix = LEGACY_INDEXES.get(name, {})
        for ix_name, cols in expected_ix.items():
            if actual_ix.get(ix_name) != cols:
                problems.append(
                    f"{name}: Index {ix_name!r} fehlt oder hat andere Spalten "
                    f"({actual_ix.get(ix_name)!r}, erwartet {cols!r})"
                )
        extra_ix = sorted(set(actual_ix) - set(expected_ix))
        if extra_ix:
            problems.append(f"{name}: unbekannte Indizes {extra_ix}")

    # 5. PostgreSQL: nativer Enum-Typ claim_status mit exakt den drei Labels.
    if dialect.name == "postgresql" and "medical_claims" not in missing_tables:
        labels = tuple(
            conn.execute(
                sa.text(
                    "SELECT e.enumlabel FROM pg_enum e "
                    "JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = 'claim_status' ORDER BY e.enumsortorder"
                )
            ).scalars()
        )
        if labels != CLAIM_STATUS_LABELS:
            problems.append(
                f"PostgreSQL-Enum claim_status hat Labels {labels!r}, "
                f"erwartet {CLAIM_STATUS_LABELS!r}"
            )

    if problems:
        raise StampPreflightError(
            "stamp-legacy VERWEIGERT (fail-closed). Die Datenbank entspricht nicht "
            "eindeutig der Legacy-Baseline:\n  - " + "\n  - ".join(problems)
        )


def stamp_legacy() -> str:
    """Fuehrt den Preflight aus und stempelt dann 0000_legacy_baseline.

    Ziel-Datenbank ist immer ``settings.effective_sync_database_url`` (dieselbe
    URL, die alembic/env.py verwendet). Einzige Stelle, die alembic_version
    schreibt, ausser Alembic selbst.
    """
    sync_url = settings.effective_sync_database_url
    engine = sa.create_engine(sync_url, poolclass=NullPool, future=True)
    try:
        with engine.connect() as conn:
            stamp_legacy_preflight(conn)
    finally:
        engine.dispose()
    command.stamp(alembic_config(), LEGACY_BASELINE_REVISION)
    logger.info("Legacy-Baseline %s gestempelt.", LEGACY_BASELINE_REVISION)
    return LEGACY_BASELINE_REVISION


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.schema_guard",
        description="ProofMed Schema-Guard (Alembic ist die Schema-Autoritaet).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="Nur lesend: Schema gegen erwarteten Alembic-Head pruefen.")
    sub.add_parser(
        "stamp-legacy",
        help="Bestehende pre-Alembic-Datenbank nach fail-closed Preflight mit "
        f"{LEGACY_BASELINE_REVISION} stempeln (schreibt NUR alembic_version).",
    )
    args = parser.parse_args(argv)

    try:
        if args.command == "check":
            revision = verify_schema_url(settings.effective_sync_database_url)
            print(f"OK: Schema auf Alembic-Revision {revision}.")
            return 0
        if args.command == "stamp-legacy":
            revision = stamp_legacy()
            print(f"OK: {revision} gestempelt. Jetzt `alembic upgrade head` ausfuehren.")
            return 0
    except SchemaGuardError as exc:
        print(f"FEHLER ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
