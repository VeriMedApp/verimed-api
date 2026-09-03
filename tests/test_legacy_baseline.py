"""WP-INFRA-1: Legacy-Baseline, Revisionsgraph, Schema-Guard, stamp-legacy (B1-B12).

Laeuft gegen die isolierte SQLite-Testdatei bzw. die Wegwerf-PostgreSQL-DB
(siehe conftest.py). Beruehrt niemals verimed.db oder Produktionsdaten.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app import schema_guard
from app.schema_guard import (
    LegacyDatabaseNotStamped,
    SchemaIncomplete,
    SchemaNotInitialized,
    SchemaVersionMismatch,
    StampPreflightError,
    stamp_legacy,
    verify_schema,
)
from tests.conftest import (
    IS_POSTGRES,
    LEGACY_TABLES,
    UTC_NOW,
    _make_engine,
    create_legacy_schema,
    dispose_app_engine,
    legacy_snapshot,
    reflect_structure,
    reset_database,
    seed_legacy_state,
)

LEGACY_REV = "0000_legacy_baseline"
HEAD_REV = "0001_reference_core"
REFERENCE_TABLES = set(schema_guard.REFERENCE_CORE_TABLES)
CLAIM_STATUS_LABELS = ("PENDING", "PROCESSED_FLAGGED", "PROCESSED_CLEAN")

# Historischer Zustand VOR den acht Zusatzspalten + die alten ad-hoc ALTER-Strings
# aus app/database.py (dort inzwischen entfernt; hier nur zur Simulation).
_OLD_GOA_DDL = (
    "CREATE TABLE goa_ziffern ("
    "ziffer VARCHAR(16) NOT NULL, title_official VARCHAR(512) NOT NULL, "
    "title_patient VARCHAR(512) NOT NULL, rule_time_minutes INTEGER NOT NULL, "
    "exclusion_ziffern JSON NOT NULL, PRIMARY KEY (ziffer))"
)
_OLD_GOA_ALTERS = (
    ("category", "VARCHAR(32) NOT NULL DEFAULT 'personal'"),
    ("threshold_multiplier", "FLOAT NOT NULL DEFAULT 2.3"),
    ("max_multiplier", "FLOAT NOT NULL DEFAULT 3.5"),
    ("fee_simple", "FLOAT NOT NULL DEFAULT 0"),
    ("fee_threshold", "FLOAT NOT NULL DEFAULT 0"),
    ("fee_max", "FLOAT NOT NULL DEFAULT 0"),
    ("max_per_session", "INTEGER"),
    ("sort_order", "INTEGER NOT NULL DEFAULT 0"),
)


def _tables(engine: sa.Engine) -> set[str]:
    return set(sa.inspect(engine).get_table_names())


def _versions(engine: sa.Engine) -> list[str]:
    with engine.connect() as conn:
        return schema_guard.read_current_revisions(conn)


def _pg_enum_labels(engine: sa.Engine) -> tuple[str, ...]:
    with engine.connect() as conn:
        return tuple(
            conn.execute(
                sa.text(
                    "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = 'claim_status' ORDER BY e.enumsortorder"
                )
            ).scalars()
        )


def _pg_type_exists(engine: sa.Engine, name: str) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                sa.text("SELECT 1 FROM pg_type WHERE typname = :n"), {"n": name}
            ).scalar()
        )


def _create_alter_upgraded_legacy_schema(engine: sa.Engine) -> None:
    """Simuliert eine per altem ALTER-Loop hochgezogene Legacy-DB (mit Server-Defaults)."""
    from app.database import Base
    from tests.conftest import legacy_metadata_tables

    with engine.begin() as conn:
        conn.execute(sa.text(_OLD_GOA_DDL))
    others = [t for t in legacy_metadata_tables() if t.name != "goa_ziffern"]
    Base.metadata.create_all(engine, tables=others)
    with engine.begin() as conn:
        for name, ddl in _OLD_GOA_ALTERS:
            conn.execute(sa.text(f"ALTER TABLE goa_ziffern ADD COLUMN {name} {ddl}"))


# ---------------------------------------------------------------------------
# B1/B2 - Baseline und Head auf leerer Datenbank
# ---------------------------------------------------------------------------


def test_b1_baseline_only_on_clean_db(engine: sa.Engine, alembic_cfg) -> None:
    command.upgrade(alembic_cfg, LEGACY_REV)
    assert _tables(engine) == set(LEGACY_TABLES) | {"alembic_version"}
    assert _versions(engine) == [LEGACY_REV]
    if IS_POSTGRES:
        assert _pg_enum_labels(engine) == CLAIM_STATUS_LABELS
    with engine.connect() as conn:
        for name in LEGACY_TABLES:
            assert conn.execute(sa.text(f"SELECT COUNT(*) FROM {name}")).scalar_one() == 0


def test_b2_head_is_21_tables(migrated_engine: sa.Engine) -> None:
    tables = _tables(migrated_engine)
    assert tables == set(LEGACY_TABLES) | REFERENCE_TABLES | {"alembic_version"}
    assert len(tables) == 22  # 21 verwaltete Tabellen + alembic_version
    assert _versions(migrated_engine) == [HEAD_REV]
    assert schema_guard.expected_head() == HEAD_REV


# ---------------------------------------------------------------------------
# B3 - Baseline/Modell-Aequivalenz
# ---------------------------------------------------------------------------


def test_b3_baseline_matches_create_all(clean_db) -> None:
    alembic_cfg = clean_db

    engine_a = _make_engine()
    try:
        create_legacy_schema(engine_a)  # historischer create_all()-Pfad
        from_create_all = reflect_structure(engine_a, LEGACY_TABLES)
        labels_a = _pg_enum_labels(engine_a) if IS_POSTGRES else None
    finally:
        engine_a.dispose()

    reset_database()
    command.upgrade(alembic_cfg, LEGACY_REV)
    engine_b = _make_engine()
    try:
        from_baseline = reflect_structure(engine_b, LEGACY_TABLES)
        labels_b = _pg_enum_labels(engine_b) if IS_POSTGRES else None
    finally:
        engine_b.dispose()

    for name in sorted(LEGACY_TABLES):
        assert from_create_all[name] == from_baseline[name], f"Strukturabweichung in {name}"
    assert labels_a == labels_b


# ---------------------------------------------------------------------------
# B4/B6 - Bestehende Legacy-DB -> sicherer Stamp -> Head (SQLite und PostgreSQL)
# ---------------------------------------------------------------------------


def test_b4_legacy_db_stamp_then_head_preserves_data(stamped_legacy_engine, alembic_cfg) -> None:
    engine, before = stamped_legacy_engine
    assert _versions(engine) == [LEGACY_REV]
    command.upgrade(alembic_cfg, "head")
    assert _tables(engine) == set(LEGACY_TABLES) | REFERENCE_TABLES | {"alembic_version"}
    assert legacy_snapshot(engine) == before
    assert _versions(engine) == [HEAD_REV]
    with engine.connect() as conn:
        assert verify_schema(conn) == HEAD_REV


# ---------------------------------------------------------------------------
# B5 - ALTER-hochgezogene Legacy-Form (Server-Defaults toleriert) -> Stamp -> Head -> Seed
# ---------------------------------------------------------------------------


def test_b5_alter_upgraded_legacy_shape(engine: sa.Engine, alembic_cfg) -> None:
    from app.models.backup import EncryptedBackup
    from app.seed import seed_goa_catalog

    _create_alter_upgraded_legacy_schema(engine)
    with Session(engine) as session:
        session.add(
            EncryptedBackup(
                user_id_hash="hash_alter",
                ciphertext_base64="Y2lwaGVy",
                iv_base64="aXY=",
                salt_base64="c2FsdA==",
                updated_at=UTC_NOW,
            )
        )
        session.commit()
    before = legacy_snapshot(engine)

    stamp_legacy()  # toleriert die historischen Server-Defaults
    command.upgrade(alembic_cfg, "head")
    with engine.connect() as conn:
        assert verify_schema(conn) == HEAD_REV
    assert legacy_snapshot(engine) == before

    try:
        inserted = asyncio.run(seed_goa_catalog())
    finally:
        dispose_app_engine()
    assert inserted == 26
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT COUNT(*) FROM goa_ziffern")).scalar_one() == 26
        assert conn.execute(sa.text("SELECT COUNT(*) FROM encrypted_backups")).scalar_one() == 1


# ---------------------------------------------------------------------------
# B7 - stamp-legacy verweigert (fail-closed), ohne alembic_version zu schreiben
# ---------------------------------------------------------------------------


def _assert_refused(engine: sa.Engine, match: str) -> None:
    with pytest.raises(StampPreflightError, match=match):
        stamp_legacy()
    assert _versions(engine) == [], "Trotz Verweigerung wurde gestempelt"


def test_b7a_stamp_refuses_missing_table(engine: sa.Engine) -> None:
    create_legacy_schema(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("DROP TABLE encrypted_backups"))
    _assert_refused(engine, "Legacy-Tabellen fehlen")


def test_b7b_stamp_refuses_missing_columns(engine: sa.Engine) -> None:
    from app.database import Base
    from tests.conftest import legacy_metadata_tables

    with engine.begin() as conn:
        conn.execute(sa.text(_OLD_GOA_DDL))  # 5-Spalten-Form ohne ALTER
    Base.metadata.create_all(
        engine, tables=[t for t in legacy_metadata_tables() if t.name != "goa_ziffern"]
    )
    _assert_refused(engine, "goa_ziffern: Spalten fehlen")


def test_b7c_stamp_refuses_extra_column(engine: sa.Engine) -> None:
    create_legacy_schema(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("ALTER TABLE encrypted_backups ADD COLUMN stray_col TEXT"))
    _assert_refused(engine, "unbekannte Spalten")


def test_b7d_stamp_refuses_when_reference_core_table_exists(engine: sa.Engine) -> None:
    from app.database import Base
    from app.models import reference_core  # noqa: F401 - nur im Test

    create_legacy_schema(engine)
    Base.metadata.create_all(engine, tables=[Base.metadata.tables["source_records"]])
    _assert_refused(engine, "Reference-Core-Tabellen existieren bereits")


def test_b7e_stamp_refuses_incompatible_alembic_version(engine: sa.Engine) -> None:
    create_legacy_schema(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES ('deadbeef')"))
    with pytest.raises(StampPreflightError, match="alembic_version enthaelt bereits"):
        stamp_legacy()
    assert _versions(engine) == ["deadbeef"], "Bestehender Zustand wurde ueberschrieben"


def test_b7f_stamp_tolerates_empty_alembic_version_table(engine: sa.Engine) -> None:
    # Leere Tabelle (z.B. von `alembic check`) ist kein Widerspruch.
    seed_legacy_state(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
    assert stamp_legacy() == LEGACY_REV
    assert _versions(engine) == [LEGACY_REV]


def test_b7g_stamp_refuses_wrong_ondelete(engine: sa.Engine) -> None:
    from app.database import Base
    from tests.conftest import legacy_metadata_tables

    Base.metadata.create_all(
        engine, tables=[t for t in legacy_metadata_tables() if t.name != "claim_line_items"]
    )
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE claim_line_items (id INTEGER NOT NULL, claim_id VARCHAR(36) NOT NULL, "
                "ziffer VARCHAR(16) NOT NULL, multiplier FLOAT NOT NULL, justification TEXT, "
                "PRIMARY KEY (id), FOREIGN KEY(claim_id) REFERENCES medical_claims (id), "
                "FOREIGN KEY(ziffer) REFERENCES goa_ziffern (ziffer))"
            )
        )
        conn.execute(sa.text("CREATE INDEX ix_claim_line_items_claim_id ON claim_line_items (claim_id)"))
    _assert_refused(engine, "claim_line_items: Fremdschluessel")


def test_b7h_stamp_refuses_missing_index(engine: sa.Engine) -> None:
    create_legacy_schema(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("DROP INDEX ix_claim_line_items_claim_id"))
    _assert_refused(engine, "Index 'ix_claim_line_items_claim_id' fehlt")


def test_b7i_pg_stamp_refuses_wrong_enum_labels(engine: sa.Engine, pg_only) -> None:  # noqa: ARG001
    create_legacy_schema(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("ALTER TYPE claim_status ADD VALUE 'BOGUS'"))
    _assert_refused(engine, "claim_status hat Labels")


# ---------------------------------------------------------------------------
# B8 - Runtime-Guard: vier Fehlerzustaende, ein Erfolgszustand, keine Seiteneffekte
# ---------------------------------------------------------------------------


def test_b8_runtime_guard_states(engine: sa.Engine, alembic_cfg) -> None:
    with engine.connect() as conn:
        with pytest.raises(SchemaNotInitialized):
            verify_schema(conn)
    assert _tables(engine) == set(), "Guard darf nichts anlegen (auch nicht alembic_version)"

    create_legacy_schema(engine)
    with engine.connect() as conn:
        with pytest.raises(LegacyDatabaseNotStamped, match="stamp-legacy"):
            verify_schema(conn)
    assert "alembic_version" not in _tables(engine)

    stamp_legacy()
    with engine.connect() as conn:
        with pytest.raises(SchemaVersionMismatch, match=HEAD_REV):
            verify_schema(conn)

    command.upgrade(alembic_cfg, "head")
    with engine.connect() as conn:
        assert verify_schema(conn) == HEAD_REV

    with engine.begin() as conn:
        conn.execute(sa.text("DROP TABLE verification_records"))
    with engine.connect() as conn:
        with pytest.raises(SchemaIncomplete, match="verification_records"):
            verify_schema(conn)


def test_b8b_init_db_delegates_to_guard(clean_db) -> None:  # noqa: ARG001
    from app.database import init_db

    try:
        with pytest.raises(SchemaNotInitialized):
            asyncio.run(init_db())
    finally:
        dispose_app_engine()
    probe = _make_engine()
    try:
        assert _tables(probe) == set()
    finally:
        probe.dispose()


# ---------------------------------------------------------------------------
# B9/B10 - Downgrades: nur Reference Core; Legacy-Datenschutz
# ---------------------------------------------------------------------------


def test_b9_downgrade_head_to_baseline_removes_only_reference_core(
    stamped_legacy_engine, alembic_cfg
) -> None:
    engine, before = stamped_legacy_engine
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, LEGACY_REV)
    assert _tables(engine) == set(LEGACY_TABLES) | {"alembic_version"}
    assert legacy_snapshot(engine) == before
    assert _versions(engine) == [LEGACY_REV]


def test_b10_downgrade_base_refuses_with_legacy_rows(
    stamped_legacy_engine, alembic_cfg, monkeypatch
) -> None:
    engine, before = stamped_legacy_engine
    command.upgrade(alembic_cfg, "head")

    monkeypatch.delenv("PROOFMED_ALLOW_LEGACY_DROP", raising=False)
    with pytest.raises(RuntimeError, match="legacy tables contain data"):
        command.downgrade(alembic_cfg, "base")
    assert set(LEGACY_TABLES) <= _tables(engine)
    assert legacy_snapshot(engine) == before

    monkeypatch.setenv("PROOFMED_ALLOW_LEGACY_DROP", "YES")
    command.downgrade(alembic_cfg, "base")
    assert _tables(engine) == {"alembic_version"}
    assert _versions(engine) == []
    if IS_POSTGRES:
        assert not _pg_type_exists(engine, "claim_status")


# ---------------------------------------------------------------------------
# B11 - claim_status Verhalten (ORM + nativer Typ)
# ---------------------------------------------------------------------------


def test_b11_claim_status_enum(migrated_engine: sa.Engine) -> None:
    from app.models.claim import ClaimStatus, MedicalClaim

    claim_id = str(uuid.uuid4())
    with Session(migrated_engine) as session:
        session.add(
            MedicalClaim(
                id=claim_id,
                patient_id="PATIENT_X",
                praxis_name="PRAXIS_X",
                geofence_arrival=UTC_NOW,
                geofence_departure=UTC_NOW,
                status=ClaimStatus.PROCESSED_CLEAN,
            )
        )
        session.commit()
    with Session(migrated_engine) as session:
        assert session.get(MedicalClaim, claim_id).status is ClaimStatus.PROCESSED_CLEAN
    with migrated_engine.connect() as conn:
        raw = conn.execute(
            sa.text("SELECT status FROM medical_claims WHERE id = :i"), {"i": claim_id}
        ).scalar_one()
    assert raw == "PROCESSED_CLEAN"  # Enum-NAME wird gespeichert, nicht der Wert
    if IS_POSTGRES:
        assert _pg_enum_labels(migrated_engine) == CLAIM_STATUS_LABELS
        with pytest.raises(DBAPIError):
            with migrated_engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO medical_claims (id, patient_id, praxis_name, "
                        "geofence_arrival, geofence_departure, total_billed_amount, status) "
                        "VALUES (:i, 'x', 'y', :t, :t, 0, 'BOGUS')"
                    ),
                    {"i": str(uuid.uuid4()), "t": UTC_NOW},
                )


# ---------------------------------------------------------------------------
# B12 - Fremdschluessel-Verhalten der Legacy-Tabellen
# ---------------------------------------------------------------------------


def test_b12_legacy_foreign_keys(migrated_engine: sa.Engine) -> None:
    from app.models.claim import ClaimLineItem, MedicalClaim
    from app.models.goa import GOAZiffer

    claim_id = str(uuid.uuid4())
    with Session(migrated_engine) as session:
        session.add(
            GOAZiffer(
                ziffer="Z1",
                title_official="T",
                title_patient="P",
                rule_time_minutes=1,
                exclusion_ziffern=[],
            )
        )
        session.add(
            MedicalClaim(
                id=claim_id,
                patient_id="PATIENT_X",
                praxis_name="PRAXIS_X",
                geofence_arrival=UTC_NOW,
                geofence_departure=UTC_NOW,
            )
        )
        session.flush()
        session.add(ClaimLineItem(claim_id=claim_id, ziffer="Z1", multiplier=1.0))
        session.commit()

    # Unbekannte Ziffer -> FK-Verstoss
    with Session(migrated_engine) as session:
        session.add(ClaimLineItem(claim_id=claim_id, ziffer="NOPE", multiplier=1.0))
        with pytest.raises(IntegrityError):
            session.commit()

    # ON DELETE CASCADE von medical_claims auf claim_line_items
    with migrated_engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM medical_claims WHERE id = :i"), {"i": claim_id})
    with migrated_engine.connect() as conn:
        assert conn.execute(sa.text("SELECT COUNT(*) FROM claim_line_items")).scalar_one() == 0
