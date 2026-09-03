"""WP-01 Schema-Tests: Reference Core V1.1.2 Skelett (T1-T12).

Alle Tests laufen synchron gegen eine isolierte Testdatenbank (SQLite-Datei
oder PostgreSQL via PROOFMED_TEST_PG_URL, siehe conftest.py).
"""

from __future__ import annotations

import ast
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base
from app.models import reference_core as rc
from tests import conftest
from tests.conftest import REPO_ROOT, _make_engine, assert_pg_reset_allowed, reset_database

REVISION = "0001_reference_core"
REFERENCE_TABLES = set(rc.REFERENCE_CORE_TABLES)
LEGACY_TABLES = {"goa_ziffern", "medical_claims", "claim_line_items", "encrypted_backups"}

UTC_NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _tables(engine: sa.Engine) -> set[str]:
    return set(sa.inspect(engine).get_table_names())


def _alembic_version_rows(engine: sa.Engine) -> list[str]:
    with engine.connect() as conn:
        return list(conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalars())


def _legacy_metadata_tables() -> list[sa.Table]:
    from app import models as legacy_models  # noqa: F401 - registriert Legacy-Tabellen

    return [Base.metadata.tables[name] for name in sorted(LEGACY_TABLES)]


def _reference_metadata_tables() -> list[sa.Table]:
    return [Base.metadata.tables[name] for name in rc.REFERENCE_CORE_TABLES]


def _normalize_sql(text_: str | None) -> str:
    return " ".join((text_ or "").replace("\n", " ").split()).strip("()")


def _reflect_structure(engine: sa.Engine, table_names: set[str]) -> dict:
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


def _new_edition(**overrides) -> rc.FeeScheduleEdition:
    values = dict(
        fee_schedule_edition_id=uuid.uuid4(),
        fee_schedule_name="EDITION_X",
        jurisdiction="JURISDICTION_X",
        legal_identifier="LEGAL_ID_X",
        edition_identifier="EDITION_X",
        effective_from=date(2020, 1, 1),
        verification_status="DRAFT",
        legal_status="CURRENT",
    )
    values.update(overrides)
    return rc.FeeScheduleEdition(**values)


def _new_release(edition: rc.FeeScheduleEdition, sequence: int = 1) -> rc.ReferenceRelease:
    return rc.ReferenceRelease(
        release_id=uuid.uuid4(),
        fee_schedule_edition_id=edition.fee_schedule_edition_id,
        version="0.0.0",
        release_sequence=sequence,
        release_name="RELEASE_X",
        status="DRAFT",
        created_at=UTC_NOW,
        created_by="tester",
    )


def _new_source(source_class: str) -> rc.SourceRecord:
    return rc.SourceRecord(
        source_id=uuid.uuid4(),
        source_class=source_class,
        issuer="ISSUER_X",
        document_title="DOCUMENT_X",
    )


def _new_calc_rule(release: rc.ReferenceRelease, source: rc.SourceRecord) -> rc.FeeCalculationRule:
    return rc.FeeCalculationRule(
        calculation_rule_id=uuid.uuid4(),
        release_id=release.release_id,
        rule_name="CALC_RULE_X",
        formula_type="DIRECT_MULTIPLICATION",
        rounding_mode="HALF_UP",
        rounding_precision="CENT",
        rounding_stage="FINAL_RESULT",
        source_id=source.source_id,
        legal_strength="STATUTORY_EXPLICIT",
        valid_from=date(2020, 1, 1),
    )


def _new_assertion(release: rc.ReferenceRelease | uuid.UUID, **overrides) -> rc.ReferenceAssertion:
    release_id = release if isinstance(release, uuid.UUID) else release.release_id
    values = dict(
        assertion_id=uuid.uuid4(),
        release_id=release_id,
        subject_type="GOA_ENTRY",
        subject_id=uuid.uuid4(),
        field_name="FIELD_X",
        assertion_value={"v": "VALUE_X"},
        value_type="STRING",
        valid_from=date(2020, 1, 1),
    )
    values.update(overrides)
    return rc.ReferenceAssertion(**values)


def _seed_release(session: Session) -> tuple[rc.FeeScheduleEdition, rc.ReferenceRelease]:
    edition = _new_edition()
    release = _new_release(edition)
    session.add_all([edition, release])
    session.flush()
    return edition, release


def _expect_integrity_error(engine: sa.Engine, *objects) -> None:
    with Session(engine) as session:
        session.add_all(objects)
        with pytest.raises(IntegrityError):
            session.commit()


# ---------------------------------------------------------------------------
# T1 - Upgrade auf leerer Datenbank
# ---------------------------------------------------------------------------


def test_t1_upgrade_clean_database(migrated_engine: sa.Engine) -> None:
    tables = _tables(migrated_engine)
    assert REFERENCE_TABLES <= tables
    assert "alembic_version" in tables
    assert tables - REFERENCE_TABLES - {"alembic_version"} == set()
    assert not (tables & LEGACY_TABLES), "Alembic darf keine Legacy-Tabellen anlegen"
    assert _alembic_version_rows(migrated_engine) == [REVISION]
    # Schema bleibt leer (keine Seed-Zeilen).
    with migrated_engine.connect() as conn:
        for name in rc.REFERENCE_CORE_TABLES:
            count = conn.execute(sa.text(f"SELECT COUNT(*) FROM {name}")).scalar_one()
            assert count == 0, f"{name} muss nach der Migration leer sein"


# ---------------------------------------------------------------------------
# T2 - Upgrade auf Datenbank mit Legacy-Zustand
# ---------------------------------------------------------------------------


def _seed_legacy_state(engine: sa.Engine) -> dict[str, list]:
    from app.models.backup import EncryptedBackup
    from app.models.goa import GOAZiffer

    Base.metadata.create_all(engine, tables=_legacy_metadata_tables())
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
    return _legacy_snapshot(engine)


def _legacy_snapshot(engine: sa.Engine) -> dict[str, list]:
    insp = sa.inspect(engine)
    snapshot: dict[str, list] = {}
    with engine.connect() as conn:
        for name in sorted(LEGACY_TABLES):
            columns = [c["name"] for c in insp.get_columns(name)]
            rows = conn.execute(
                sa.text(f"SELECT * FROM {name} ORDER BY 1")
            ).all()
            snapshot[name] = [columns, [tuple(r) for r in rows]]
    return snapshot


def test_t2_upgrade_with_legacy_state(engine: sa.Engine, alembic_cfg) -> None:
    before = _seed_legacy_state(engine)
    assert before["goa_ziffern"][1], "Legacy-Seed fehlgeschlagen"

    command.upgrade(alembic_cfg, "head")

    tables = _tables(engine)
    assert LEGACY_TABLES <= tables
    assert REFERENCE_TABLES <= tables
    assert _legacy_snapshot(engine) == before, "Legacy-Daten/-Spalten wurden veraendert"
    assert _alembic_version_rows(engine) == [REVISION]


# ---------------------------------------------------------------------------
# T3 - Downgrade (inkl. Idempotenz)
# ---------------------------------------------------------------------------


def test_t3_downgrade_restores_legacy_only(engine: sa.Engine, alembic_cfg) -> None:
    before = _seed_legacy_state(engine)
    command.upgrade(alembic_cfg, "head")

    command.downgrade(alembic_cfg, "base")
    tables = _tables(engine)
    assert not (tables & REFERENCE_TABLES), "Reference-Core-Tabellen wurden nicht entfernt"
    assert LEGACY_TABLES <= tables
    assert _legacy_snapshot(engine) == before
    assert _alembic_version_rows(engine) == []

    # Zweiter Downgrade ist ein No-op.
    command.downgrade(alembic_cfg, "base")
    assert _tables(engine) == tables
    assert _legacy_snapshot(engine) == before


# ---------------------------------------------------------------------------
# T4 - Modell/Migration-Aequivalenz
# ---------------------------------------------------------------------------


def test_t4_migration_matches_models(clean_db) -> None:
    alembic_cfg = clean_db

    # (a) Struktur nach Alembic-Upgrade
    command.upgrade(alembic_cfg, "head")
    engine_a = _make_engine()
    try:
        from_migration = _reflect_structure(engine_a, REFERENCE_TABLES)

        # (b) Alembic-Vergleich Metadata vs. migrierte DB (nur Reference-Core-Tabellen)
        def include_object(obj, name, type_, reflected, compare_to):  # noqa: ARG001
            # Filtert Metadata- UND DB-Seite auf die 17 Reference-Core-Tabellen.
            if type_ == "table":
                return name in REFERENCE_TABLES
            return True

        with engine_a.connect() as conn:
            ctx = MigrationContext.configure(
                conn,
                opts={"compare_type": False, "include_object": include_object},
            )
            diff = compare_metadata(ctx, Base.metadata)
        assert diff == [], f"Alembic-Metadata-Vergleich meldet Abweichungen: {diff}"
    finally:
        engine_a.dispose()

    # (c) Struktur nach create_all der Modelle (frische DB)
    reset_database()
    engine_b = _make_engine()
    try:
        Base.metadata.create_all(engine_b, tables=_reference_metadata_tables())
        from_models = _reflect_structure(engine_b, REFERENCE_TABLES)
    finally:
        engine_b.dispose()

    for name in sorted(REFERENCE_TABLES):
        assert from_migration[name] == from_models[name], f"Strukturabweichung in {name}"


# ---------------------------------------------------------------------------
# T5 - Constraint-/Index-Inventar
# ---------------------------------------------------------------------------

KEY_CONSTRAINT_NAMES = {
    "uq_reference_releases_edition_sequence",
    "uq_billing_rules_condition_group",
    "uq_source_records_id_class",
    "fk_reference_assertions_source_id_class",
    "fk_billing_rule_codes_entry_id",
    "ck_ra_inv016",
    "ck_ra_source_class_pair",
    "ck_ad_not_self",
    "ck_cg_not_self_parent",
    "ck_aem_finalized_has_hash",
    "ck_fse_verification_date",
    "ck_sr_document_hash_scope",
    "ck_br_temporal_source",
    "ix_goa_reference_entries_release_code",
    "ix_reference_releases_edition_status_released",
    "ix_reference_assertions_release_subject",
}


def test_t5_constraint_inventory(migrated_engine: sa.Engine) -> None:
    insp = sa.inspect(migrated_engine)
    found: set[str] = set()
    for name in rc.REFERENCE_CORE_TABLES:
        for fk in insp.get_foreign_keys(name):
            found.add(fk["name"])
            assert (fk.get("options") or {}).get("ondelete") == "RESTRICT", (
                f"{name}.{fk['name']} muss ON DELETE RESTRICT sein"
            )
        found.update(uq["name"] for uq in insp.get_unique_constraints(name))
        found.update(ck["name"] for ck in insp.get_check_constraints(name))
        found.update(ix["name"] for ix in insp.get_indexes(name))

    expected: set[str] = set()
    for table in _reference_metadata_tables():
        for constraint in table.constraints:
            if isinstance(constraint, sa.PrimaryKeyConstraint):
                continue
            expected.add(constraint.name)
        expected.update(ix.name for ix in table.indexes)

    assert KEY_CONSTRAINT_NAMES <= expected
    missing = expected - found
    assert not missing, f"In der migrierten DB fehlen benannte Constraints/Indizes: {missing}"
    assert len(REFERENCE_TABLES) == 17


# ---------------------------------------------------------------------------
# T6 - UNIQUE (fee_schedule_edition_id, release_sequence)
# ---------------------------------------------------------------------------


def test_t6_release_sequence_unique(migrated_engine: sa.Engine) -> None:
    with Session(migrated_engine) as session:
        edition, _release = _seed_release(session)
        session.commit()
        edition_id = edition.fee_schedule_edition_id

    with Session(migrated_engine) as session:
        edition = session.get(rc.FeeScheduleEdition, edition_id)
        session.add(_new_release(edition, sequence=2))
        session.commit()  # andere Sequenz: erlaubt

    with Session(migrated_engine) as session:
        edition = session.get(rc.FeeScheduleEdition, edition_id)
        session.add(_new_release(edition, sequence=1))  # Duplikat
        with pytest.raises(IntegrityError):
            session.commit()


# ---------------------------------------------------------------------------
# T7 - INV-016 Ableitungssemantik
# ---------------------------------------------------------------------------


def test_t7_inv016_derivation_semantics(migrated_engine: sa.Engine) -> None:
    with Session(migrated_engine) as session:
        edition, release = _seed_release(session)
        source_a = _new_source("SOURCE_A_LEGAL")
        source_e = _new_source("SOURCE_E_PROOFMED")
        session.add_all([source_a, source_e])
        session.flush()
        calc_rule = _new_calc_rule(release, source_a)
        session.add(calc_rule)

        # Gueltige Faelle
        session.add(
            _new_assertion(
                release,
                derivation_type="DIRECT_SOURCE",
                source_id=source_a.source_id,
                source_class="SOURCE_A_LEGAL",
            )
        )
        session.add(
            _new_assertion(
                release,
                derivation_type="CALCULATED",
                calculation_rule_id=calc_rule.calculation_rule_id,
            )
        )
        session.add(
            _new_assertion(
                release,
                derivation_type="CURATED_INTERNAL",
                source_id=source_e.source_id,
                source_class="SOURCE_E_PROOFMED",
            )
        )
        session.commit()
        release_id = release.release_id
        source_a_id = source_a.source_id
        calc_id = calc_rule.calculation_rule_id

    # DIRECT_SOURCE ohne Quelle -> CHECK-Verstoss
    _expect_integrity_error(
        migrated_engine,
        _new_assertion(release_id, derivation_type="DIRECT_SOURCE"),
    )
    # CALCULATED mit Quelle -> CHECK-Verstoss
    _expect_integrity_error(
        migrated_engine,
        _new_assertion(
            release_id,
            derivation_type="CALCULATED",
            source_id=source_a_id,
            source_class="SOURCE_A_LEGAL",
            calculation_rule_id=calc_id,
        ),
    )
    # CALCULATED ohne Berechnungsregel -> CHECK-Verstoss
    _expect_integrity_error(
        migrated_engine,
        _new_assertion(release_id, derivation_type="CALCULATED"),
    )
    # CURATED_INTERNAL mit lokaler Klasse != E -> CHECK-Verstoss
    _expect_integrity_error(
        migrated_engine,
        _new_assertion(
            release_id,
            derivation_type="CURATED_INTERNAL",
            source_id=source_a_id,
            source_class="SOURCE_A_LEGAL",
        ),
    )
    # CURATED_INTERNAL: lokale Klasse E, aber die Quelle ist Klasse A ->
    # zusammengesetzter FK (source_id, source_class) schlaegt fehl (Cross-Table INV-016)
    _expect_integrity_error(
        migrated_engine,
        _new_assertion(
            release_id,
            derivation_type="CURATED_INTERNAL",
            source_id=source_a_id,
            source_class="SOURCE_E_PROOFMED",
        ),
    )


# ---------------------------------------------------------------------------
# T8 - ASSERTION_DEPENDENCY
# ---------------------------------------------------------------------------


def test_t8_assertion_dependency_constraints(migrated_engine: sa.Engine) -> None:
    with Session(migrated_engine) as session:
        edition, release = _seed_release(session)
        source_a = _new_source("SOURCE_A_LEGAL")
        session.add(source_a)
        session.flush()
        calc_rule = _new_calc_rule(release, source_a)
        derived = _new_assertion(
            release, derivation_type="CALCULATED", calculation_rule_id=calc_rule.calculation_rule_id
        )
        input_ = _new_assertion(
            release,
            derivation_type="DIRECT_SOURCE",
            source_id=source_a.source_id,
            source_class="SOURCE_A_LEGAL",
        )
        session.add_all([calc_rule, derived, input_])
        session.commit()
        ids = (release.release_id, derived.assertion_id, input_.assertion_id, calc_rule.calculation_rule_id)

    release_id, derived_id, input_id, calc_id = ids

    def dependency(**overrides) -> rc.AssertionDependency:
        values = dict(
            dependency_id=uuid.uuid4(),
            release_id=release_id,
            derived_assertion_id=derived_id,
            input_assertion_id=input_id,
            dependency_role="OPERAND_1",
            calculation_rule_id=calc_id,
            created_at=UTC_NOW,
        )
        values.update(overrides)
        return rc.AssertionDependency(**values)

    with Session(migrated_engine) as session:
        session.add(dependency())
        session.commit()  # gueltig

    _expect_integrity_error(migrated_engine, dependency(input_assertion_id=None))
    _expect_integrity_error(migrated_engine, dependency(input_assertion_id=derived_id))
    _expect_integrity_error(migrated_engine, dependency(input_assertion_id=uuid.uuid4()))  # FK


# ---------------------------------------------------------------------------
# T9 - CONDITION_GROUP Rekursion
# ---------------------------------------------------------------------------


def test_t9_condition_group_recursion(migrated_engine: sa.Engine) -> None:
    with Session(migrated_engine) as session:
        edition, release = _seed_release(session)
        root = rc.ConditionGroup(
            condition_group_id=uuid.uuid4(),
            release_id=release.release_id,
            logical_operator="AND",
        )
        child = rc.ConditionGroup(
            condition_group_id=uuid.uuid4(),
            release_id=release.release_id,
            logical_operator="OR",
            parent_group_id=root.condition_group_id,
        )
        session.add_all([root, child])
        session.commit()
        child_id, root_id, release_id = child.condition_group_id, root.condition_group_id, release.release_id

    with Session(migrated_engine) as session:
        assert session.get(rc.ConditionGroup, child_id).parent_group_id == root_id

    self_ref_id = uuid.uuid4()
    _expect_integrity_error(
        migrated_engine,
        rc.ConditionGroup(
            condition_group_id=self_ref_id,
            release_id=release_id,
            logical_operator="AND",
            parent_group_id=self_ref_id,
        ),
    )
    _expect_integrity_error(
        migrated_engine,
        rc.ConditionGroup(
            condition_group_id=uuid.uuid4(),
            release_id=release_id,
            logical_operator="XOR",  # nicht in der eingefrorenen Liste
        ),
    )


# ---------------------------------------------------------------------------
# T10 - SOURCE_RECORD Hash/Scope (INV-014)
# ---------------------------------------------------------------------------


def test_t10_source_hash_scope(migrated_engine: sa.Engine) -> None:
    with Session(migrated_engine) as session:
        ok = _new_source("SOURCE_A_LEGAL")
        ok.document_hash = "ab" * 32
        ok.document_hash_algorithm = "SHA256"
        ok.document_hash_scope = "FULL_DOCUMENT"
        session.add(ok)
        session.commit()

    bad = _new_source("SOURCE_A_LEGAL")
    bad.document_hash = "ab" * 32  # ohne Algorithmus/Scope
    _expect_integrity_error(migrated_engine, bad)

    bad_excerpt = _new_source("SOURCE_A_LEGAL")
    bad_excerpt.excerpt_hash_scope = "EXACT_SOURCE_EXCERPT"  # Scope ohne Hash
    _expect_integrity_error(migrated_engine, bad_excerpt)

    bad_class = _new_source("SOURCE_F_UNKNOWN")
    _expect_integrity_error(migrated_engine, bad_class)


# ---------------------------------------------------------------------------
# T11 - Legacy-Isolation
# ---------------------------------------------------------------------------


def _imports_reference_core(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any("reference_core" in alias.name for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and "reference_core" in node.module:
                return True
            if any("reference_core" in alias.name for alias in node.names):
                return True
    return False


def test_t11_legacy_isolation() -> None:
    import app.models as legacy_models

    assert "reference_core" not in legacy_models.__all__
    assert set(legacy_models.__all__) == {
        "EncryptedBackup",
        "GOAZiffer",
        "MedicalClaim",
        "ClaimLineItem",
        "ClaimStatus",
    }

    offenders = [
        p
        for p in (REPO_ROOT / "app").rglob("*.py")
        if p != REPO_ROOT / "app" / "models" / "reference_core.py" and _imports_reference_core(p)
    ]
    assert offenders == [], f"Legacy-Code importiert reference_core: {offenders}"
    assert _imports_reference_core(REPO_ROOT / "alembic" / "env.py")


# ---------------------------------------------------------------------------
# T12 - Downgrade-Schutz fuer finalisierte Manifeste (INV-022)
# ---------------------------------------------------------------------------


def test_t12_downgrade_refuses_finalized_manifest(migrated_engine: sa.Engine, alembic_cfg) -> None:
    with Session(migrated_engine) as session:
        edition, release = _seed_release(session)
        snapshot = rc.AuditReferenceSnapshot(
            snapshot_id=uuid.uuid4(),
            audit_id=uuid.uuid4(),
            service_date=date(2024, 6, 15),
            applicable_fee_schedule_edition_id=edition.fee_schedule_edition_id,
            applicable_reference_release_id=release.release_id,
            captured_at=UTC_NOW,
        )
        session.add(snapshot)
        session.flush()
        # Finalisiert ohne Hash -> CHECK ck_aem_finalized_has_hash
        session.add(
            rc.AuditEvidenceManifest(
                manifest_id=uuid.uuid4(),
                audit_id=snapshot.audit_id,
                snapshot_id=snapshot.snapshot_id,
                fee_schedule_edition_id=edition.fee_schedule_edition_id,
                reference_release_id=release.release_id,
                finalized_at=UTC_NOW,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()

    with Session(migrated_engine) as session:
        edition, release = _seed_release(session)
        snapshot = rc.AuditReferenceSnapshot(
            snapshot_id=uuid.uuid4(),
            audit_id=uuid.uuid4(),
            service_date=date(2024, 6, 15),
            applicable_fee_schedule_edition_id=edition.fee_schedule_edition_id,
            applicable_reference_release_id=release.release_id,
            captured_at=UTC_NOW,
        )
        session.add(snapshot)
        session.flush()
        session.add(
            rc.AuditEvidenceManifest(
                manifest_id=uuid.uuid4(),
                audit_id=snapshot.audit_id,
                snapshot_id=snapshot.snapshot_id,
                fee_schedule_edition_id=edition.fee_schedule_edition_id,
                reference_release_id=release.release_id,
                finalized_at=UTC_NOW,
                manifest_hash="cd" * 32,
                manifest_hash_algorithm="SHA256",
            )
        )
        session.commit()

    with pytest.raises(RuntimeError, match="INV-022"):
        command.downgrade(alembic_cfg, "base")

    assert REFERENCE_TABLES <= _tables(migrated_engine)
    assert _alembic_version_rows(migrated_engine) == [REVISION]


# ---------------------------------------------------------------------------
# S - Sicherheitsschranke fuer den destruktiven PostgreSQL-Reset (fail-closed)
# ---------------------------------------------------------------------------

_OPT_IN_YES = {conftest.RESET_OPT_IN_VAR: "YES"}
_SAFETY_MATCH = "WP-01 destructive-test safety check FAILED"


def test_sa_guard_allows_local_wp01_db_with_explicit_opt_in() -> None:
    for host in ("localhost", "127.0.0.1", "[::1]"):
        assert_pg_reset_allowed(f"postgresql://u:p@{host}:55432/proofmed_wp01", _OPT_IN_YES)
        assert_pg_reset_allowed(
            f"postgresql+psycopg2://u:p@{host}/proofmed_wp01_ci", _OPT_IN_YES
        )


def test_sb_guard_rejects_remote_host() -> None:
    for url in (
        "postgresql://u:p@db.example.com:5432/proofmed_wp01",
        "postgresql://u:p@10.0.0.5/proofmed_wp01",
        "postgresql://u:p@dpg-abc.frankfurt-postgres.render.com/proofmed_wp01",
    ):
        with pytest.raises(RuntimeError, match=_SAFETY_MATCH):
            assert_pg_reset_allowed(url, _OPT_IN_YES)


def test_sc_guard_rejects_wrong_database_name() -> None:
    for database in ("verimed", "proofmed", "proofmed_prod", "wp01", "proofmed_wp0", ""):
        with pytest.raises(RuntimeError, match=_SAFETY_MATCH):
            assert_pg_reset_allowed(f"postgresql://u:p@localhost/{database}", _OPT_IN_YES)


def test_sd_guard_rejects_missing_opt_in() -> None:
    with pytest.raises(RuntimeError, match=_SAFETY_MATCH):
        assert_pg_reset_allowed("postgresql://u:p@localhost/proofmed_wp01", {})


def test_se_guard_rejects_non_yes_opt_in() -> None:
    for value in ("yes", "true", "1", "Y", "NO", " YES", ""):
        with pytest.raises(RuntimeError, match=_SAFETY_MATCH):
            assert_pg_reset_allowed(
                "postgresql://u:p@localhost/proofmed_wp01", {conftest.RESET_OPT_IN_VAR: value}
            )


def test_sf_reset_database_rejects_before_any_engine_or_sql(monkeypatch) -> None:
    """reset_database() muss VOR Engine-Aufbau/reflect/drop_all abbrechen."""
    calls: list[str] = []

    def _forbidden_engine(*args, **kwargs):  # noqa: ARG001
        calls.append("engine")
        raise AssertionError("_make_engine darf bei fehlgeschlagener Schranke nicht laufen")

    monkeypatch.setattr(conftest, "IS_POSTGRES", True)
    monkeypatch.setattr(conftest, "SYNC_URL", "postgresql://u:p@db.example.com/proofmed_wp01")
    monkeypatch.setattr(conftest, "_make_engine", _forbidden_engine)
    monkeypatch.setenv(conftest.RESET_OPT_IN_VAR, "YES")

    with pytest.raises(RuntimeError, match=_SAFETY_MATCH):
        conftest.reset_database()
    assert calls == [], "Es wurde eine Engine aufgebaut, obwohl die Schranke ausloesen musste"

    # Auch bei lokaler Wegwerf-DB, aber ohne Opt-in: keine Engine, keine SQL.
    monkeypatch.setattr(conftest, "SYNC_URL", "postgresql://u:p@localhost/proofmed_wp01")
    monkeypatch.delenv(conftest.RESET_OPT_IN_VAR, raising=False)
    with pytest.raises(RuntimeError, match=_SAFETY_MATCH):
        conftest.reset_database()
    assert calls == []
