"""Reference Core V1.1.2 - WP-01 Schema-Skelett (17 kanonische Entitaeten).

Dieses Modul bildet die eingefrorene Reference-Core-Architektur V1.1.2
(Mechanical Freeze, 2026-09-02) 1:1 als SQLAlchemy-ORM-Modelle ab.

WP-01-Grenzen (bewusst):

* Nur Schema. Keine GOAE-Inhalte, keine Seed-Zeilen, keine Laufzeitlogik.
* Dieses Modul wird NICHT von ``app.models.__init__`` importiert. Damit legt
  ``init_db()`` / ``Base.metadata.create_all()`` beim normalen Anwendungsstart
  weiterhin ausschliesslich das Legacy-Schema an. Die Registrierung fuer
  Alembic erfolgt ausschliesslich in ``alembic/env.py``.
* Alle Constraints tragen explizite Namen (SQLite-Batch-Modus, PostgreSQL).
* Portable Typen: ``Uuid`` (CHAR(32)/UUID), ``JSON`` mit JSONB-Variante,
  ``String`` + benannte CHECK-Constraints statt nativer Enum-Typen,
  ``DateTime(timezone=True)``, ``Numeric`` statt Float.
* ``user_id``-Felder: String(128) ohne Fremdschluessel (Entscheidung N-3).
* ``audit_id``: Uuid ohne Fremdschluessel (Entscheidung N-4; Bindung in WP-08).

Zeitstempel muessen als zeitzonenbewusste UTC-Werte geschrieben werden; SQLite
speichert sie als naiven Text (Normalisierung ist Aufgabe spaeterer WPs).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database import Base

# ---------------------------------------------------------------------------
# Portable Typ-Bausteine
# ---------------------------------------------------------------------------

PortableJSON = JSON().with_variant(JSONB(), "postgresql")
HashColumn = String(128)  # Hex-Digest, ausreichend fuer SHA-256 und SHA-512
UserRef = String(128)  # user_id ohne FK (N-3)
DecimalColumn = Numeric(18, 7)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _enum_check(table: str, column: str, values: Sequence[str]) -> CheckConstraint:
    """Benannter CHECK fuer eine geschlossene, eingefrorene Enum-Liste."""
    quoted = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} IN ({quoted})", name=f"ck_{table}_{column}")


def _fk(target: str, table: str, column: str) -> ForeignKey:
    """Benannter RESTRICT-Fremdschluessel ``fk_<table>_<column>``."""
    return ForeignKey(target, name=f"fk_{table}_{column}", ondelete="RESTRICT")


# ---------------------------------------------------------------------------
# Eingefrorene Enum-Listen (nur geschlossene Listen erhalten CHECKs)
# ---------------------------------------------------------------------------

SOURCE_CLASSES = (
    "SOURCE_A_LEGAL",
    "SOURCE_B_OFFICIAL_GUIDANCE",
    "SOURCE_C_JURISPRUDENCE",
    "SOURCE_D_INTERPRETIVE",
    "SOURCE_E_PROOFMED",
)
HASH_ALGORITHMS = ("SHA256", "SHA512")
VERIFICATION_STATUSES = (
    "UNVERIFIED",
    "SOURCE_VERIFIED",
    "PROFESSIONALLY_REVIEWED",
    "LEGALLY_REVIEWED",
)
VERIFICATION_STATUSES_3 = ("UNVERIFIED", "SOURCE_VERIFIED", "PROFESSIONALLY_REVIEWED")
VERIFICATION_STATUSES_2 = ("UNVERIFIED", "SOURCE_VERIFIED")
EDITION_VERIFICATION_STATUSES = ("DRAFT", "VERIFIED")
EDITION_LEGAL_STATUSES = ("CURRENT", "HISTORICAL", "SUPERSEDED", "RETIRED")
RELEASE_STATUSES = (
    "DRAFT",
    "SOURCE_VERIFIED",
    "REVIEWED",
    "RELEASED",
    "SUPERSEDED",
    "RETIRED",
)
DOCUMENT_HASH_SCOPES = ("FULL_DOCUMENT", "ARCHIVED_ARTIFACT")
EXCERPT_HASH_SCOPES = ("EXACT_SOURCE_EXCERPT",)
ARCHIVE_HASH_SCOPES = ("ARCHIVE_ARTIFACT",)
ARCHIVE_STATUSES = ("NOT_ARCHIVED", "ARCHIVED", "ARCHIVED_EXTERNALLY")
SOURCE_VERIFICATION_METHODS = ("PRIMARY_SOURCE_MATCH", "MANUAL_PROFESSIONAL_REVIEW")
ASSERTION_SUBJECT_TYPES = (
    "GOA_ENTRY",
    "FACTOR_RULE",
    "FEE_CALCULATION",
    "BILLING_RULE",
    "ANALOG_REFERENCE",
)
ASSERTION_VALUE_TYPES = ("INTEGER", "DECIMAL", "STRING", "DATE", "ENUM", "BOOLEAN")
DERIVATION_TYPES = ("DIRECT_SOURCE", "CALCULATED", "CURATED_INTERNAL")
ASSERTION_LEGAL_STRENGTHS = (
    "STATUTORY_EXPLICIT",
    "STATUTORY_DERIVED",
    "OFFICIAL_GUIDANCE",
    "INTERPRETIVE",
    "SOURCE_NOT_FOUND",
)
ASSERTION_VERIFICATION_METHODS = ("PRIMARY_SOURCE_MATCH", "MANUAL_REVIEW")
ENTRY_CATEGORIES = ("PERSONAL", "TECHNICAL", "SURCHARGE", "ANALOG")
FACTOR_SCOPE_TYPES = (
    "STATUTE_SECTION",
    "STATUTORY_GROUP",
    "EXPLICIT_CODE_LIST",
    "INDIVIDUAL_CODE",
    "FUTURE_STRUCTURE",
)
FACTOR_LEGAL_STRENGTHS = ("STATUTORY_EXPLICIT", "STATUTORY_DERIVED", "OFFICIAL_GUIDANCE")
FORMULA_TYPES = (
    "DIRECT_MULTIPLICATION",
    "PUBLISHED_AMOUNT",
    "ALTERNATE_METHOD",
    "FUTURE_STRUCTURE",
)
ROUNDING_MODES = ("HALF_UP", "HALF_DOWN", "BANKER_ROUNDING", "TRUNCATE", "CEILING", "FLOOR")
ROUNDING_PRECISIONS = ("CENT", "EURO", "HALF_CENT", "TENTH_CENT")
ROUNDING_STAGES = ("BEFORE_THRESHOLD", "AFTER_THRESHOLD", "AFTER_MAX", "FINAL_RESULT")
CALCULATION_LEGAL_STRENGTHS = ("STATUTORY_EXPLICIT", "OFFICIAL_GUIDANCE", "INTERPRETIVE")
BILLING_RULE_TYPES = (
    "EXCLUSION",
    "TIME_MINIMUM",
    "FREQUENCY_MAX",
    "JUSTIFICATION_REQUIRED",
    "COMBINATION_PROHIBITED",
    "ORDERING_DEPENDENCY",
    "ANALOG_RESTRICTION",
    "SURCHARGE_RESTRICTION",
    "CONTEXT_REQUIREMENT",
)
TEMPORAL_SCOPES = ("SOURCE_DEFINED", "NOT_APPLICABLE", "UNKNOWN")
BILLING_LEGAL_STRENGTHS = (
    "STATUTORY_EXPLICIT",
    "STATUTORY_DERIVED",
    "OFFICIAL_GUIDANCE",
    "INTERPRETIVE",
)
LOGICAL_OPERATORS = ("AND", "OR")
RULE_CODE_ROLES = ("PRIMARY", "REQUIRED", "EXCLUDED", "RELATED", "ALTERNATE")
RECOMMENDATION_TYPES = ("STATUTORY_EQUIVALENT", "BAK_RECOMMENDED", "QUESTIONABLE", "UNRESOLVED")
ANALOG_LEGAL_STRENGTHS = (
    "STATUTORY_ANALOG_RULE",
    "BAK_RECOMMENDATION",
    "LOCAL_PRACTICE",
    "UNRESOLVED",
)
VERIFICATION_ENTITY_TYPES = (
    "SOURCE_RECORD",
    "REFERENCE_ASSERTION",
    "FACTOR_RULE",
    "FEE_CALCULATION_RULE",
    "BILLING_RULE",
    "ANALOG_REFERENCE",
)
CONFIDENCE_LEVELS = ("HIGH", "MEDIUM", "LOW", "CONFLICTING_EVIDENCE")
FINDING_TYPES = (
    "NO_FINDING",
    "REVIEW_NOTE",
    "JUSTIFICATION_REQUIRED",
    "OFFICIAL_GUIDANCE_NOTE",
    "SUPPORTED_CONFLICT",
    "NOT_CONCLUSIVELY_ASSESSABLE",
)
EVIDENCE_LEVELS = ("STATUTORY_FACT", "OFFICIAL_GUIDANCE", "PROFESSIONAL_REVIEW", "UNRESOLVED")
RECOMMENDED_TONES = ("INFORMATIONAL", "ADVISORY", "NEUTRAL")


# ---------------------------------------------------------------------------
# 1. FEE_SCHEDULE_EDITION
# ---------------------------------------------------------------------------


class FeeScheduleEdition(Base):
    """1. FEE_SCHEDULE_EDITION - rechtliche/normative Gebuehrenordnungs-Edition."""

    __tablename__ = "fee_schedule_editions"
    __table_args__ = (
        _enum_check("fee_schedule_editions", "verification_status", EDITION_VERIFICATION_STATUSES),
        _enum_check("fee_schedule_editions", "legal_status", EDITION_LEGAL_STATUSES),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_fse_effective_range",
        ),
        CheckConstraint(
            "(verification_status = 'DRAFT' AND verification_date IS NULL) "
            "OR (verification_status = 'VERIFIED' AND verification_date IS NOT NULL)",
            name="ck_fse_verification_date",
        ),
        CheckConstraint(
            "supersedes_edition_id IS NULL OR supersedes_edition_id != fee_schedule_edition_id",
            name="ck_fse_no_self_supersedes",
        ),
        CheckConstraint(
            "superseded_by_edition_id IS NULL "
            "OR superseded_by_edition_id != fee_schedule_edition_id",
            name="ck_fse_no_self_superseded_by",
        ),
        Index("ix_fee_schedule_editions_effective", "effective_from", "effective_to"),
        Index("ix_fee_schedule_editions_verification_status", "verification_status"),
        Index("ix_fee_schedule_editions_primary_legal_source_id", "primary_legal_source_id"),
        Index("ix_fee_schedule_editions_supersedes_edition_id", "supersedes_edition_id"),
        Index("ix_fee_schedule_editions_superseded_by_edition_id", "superseded_by_edition_id"),
    )

    fee_schedule_edition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    fee_schedule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(64), nullable=False)
    legal_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    edition_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'DRAFT'")
    )
    verification_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    legal_status: Mapped[str] = mapped_column(String(16), nullable=False)
    primary_legal_source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        _fk("source_records.source_id", "fee_schedule_editions", "primary_legal_source_id"),
        nullable=True,
    )
    supersedes_edition_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        _fk(
            "fee_schedule_editions.fee_schedule_edition_id",
            "fee_schedule_editions",
            "supersedes_edition_id",
        ),
        nullable=True,
    )
    superseded_by_edition_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        _fk(
            "fee_schedule_editions.fee_schedule_edition_id",
            "fee_schedule_editions",
            "superseded_by_edition_id",
        ),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# 2. REFERENCE_RELEASE
# ---------------------------------------------------------------------------


class ReferenceRelease(Base):
    """2. REFERENCE_RELEASE - kuratiertes ProofMed-Release einer Edition."""

    __tablename__ = "reference_releases"
    __table_args__ = (
        UniqueConstraint(
            "fee_schedule_edition_id",
            "release_sequence",
            name="uq_reference_releases_edition_sequence",
        ),
        _enum_check("reference_releases", "status", RELEASE_STATUSES),
        CheckConstraint(
            "status != 'RELEASED' OR released_at IS NOT NULL",
            name="ck_rr_released_at",
        ),
        Index("ix_reference_releases_fee_schedule_edition_id", "fee_schedule_edition_id"),
        Index(
            "ix_reference_releases_edition_status_released",
            "fee_schedule_edition_id",
            "status",
            "released_at",
        ),
    )

    release_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    fee_schedule_edition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk(
            "fee_schedule_editions.fee_schedule_edition_id",
            "reference_releases",
            "fee_schedule_edition_id",
        ),
        nullable=False,
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    release_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    release_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_bundle_hash: Mapped[str | None] = mapped_column(HashColumn, nullable=True)
    assertion_bundle_hash: Mapped[str | None] = mapped_column(HashColumn, nullable=True)
    rule_bundle_hash: Mapped[str | None] = mapped_column(HashColumn, nullable=True)
    condition_bundle_hash: Mapped[str | None] = mapped_column(HashColumn, nullable=True)
    content_change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(UserRef, nullable=False)
    verified_by: Mapped[str | None] = mapped_column(UserRef, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(UserRef, nullable=True)


# ---------------------------------------------------------------------------
# 3. SOURCE_RECORD
# ---------------------------------------------------------------------------


class SourceRecord(Base):
    """3. SOURCE_RECORD - autoritative Quelle mit explizitem Hash-Modell."""

    __tablename__ = "source_records"
    __table_args__ = (
        # Redundant zum PK, aber Ziel des zusammengesetzten FK aus
        # reference_assertions (source_id, source_class) - INV-016 ohne Trigger.
        UniqueConstraint("source_id", "source_class", name="uq_source_records_id_class"),
        _enum_check("source_records", "source_class", SOURCE_CLASSES),
        _enum_check("source_records", "document_hash_algorithm", HASH_ALGORITHMS),
        _enum_check("source_records", "document_hash_scope", DOCUMENT_HASH_SCOPES),
        _enum_check("source_records", "excerpt_hash_scope", EXCERPT_HASH_SCOPES),
        _enum_check("source_records", "archive_status", ARCHIVE_STATUSES),
        _enum_check("source_records", "archive_hash_scope", ARCHIVE_HASH_SCOPES),
        _enum_check("source_records", "verification_status", VERIFICATION_STATUSES),
        _enum_check("source_records", "verification_method", SOURCE_VERIFICATION_METHODS),
        CheckConstraint(
            "(document_hash IS NULL AND document_hash_algorithm IS NULL "
            "AND document_hash_scope IS NULL) "
            "OR (document_hash IS NOT NULL AND document_hash_algorithm IS NOT NULL "
            "AND document_hash_scope IS NOT NULL)",
            name="ck_sr_document_hash_scope",
        ),
        CheckConstraint(
            "(excerpt_hash IS NULL AND excerpt_hash_scope IS NULL) "
            "OR (excerpt_hash IS NOT NULL AND excerpt_hash_scope IS NOT NULL)",
            name="ck_sr_excerpt_hash_scope",
        ),
        CheckConstraint(
            "(archive_hash IS NULL AND archive_hash_scope IS NULL) "
            "OR (archive_hash IS NOT NULL AND archive_hash_scope IS NOT NULL)",
            name="ck_sr_archive_hash_scope",
        ),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_class: Mapped[str] = mapped_column(String(32), nullable=False)
    issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    document_title: Mapped[str] = mapped_column(String(512), nullable=False)
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_locator: Mapped[str | None] = mapped_column(String(512), nullable=True)
    document_hash: Mapped[str | None] = mapped_column(HashColumn, nullable=True)
    document_hash_algorithm: Mapped[str | None] = mapped_column(String(16), nullable=True)
    document_hash_scope: Mapped[str | None] = mapped_column(String(32), nullable=True)
    canonicalization_method: Mapped[str | None] = mapped_column(String(255), nullable=True)
    excerpt_hash: Mapped[str | None] = mapped_column(HashColumn, nullable=True)
    excerpt_hash_scope: Mapped[str | None] = mapped_column(String(32), nullable=True)
    excerpt_text: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    archive_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'NOT_ARCHIVED'")
    )
    archive_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    archive_hash: Mapped[str | None] = mapped_column(HashColumn, nullable=True)
    archive_hash_scope: Mapped[str | None] = mapped_column(String(32), nullable=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'UNVERIFIED'")
    )
    verification_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(UserRef, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# 4. REFERENCE_ASSERTION
# ---------------------------------------------------------------------------


class ReferenceAssertion(Base):
    """4. REFERENCE_ASSERTION - feldgenaue Provenienz mit Ableitungssemantik."""

    __tablename__ = "reference_assertions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "source_class"],
            ["source_records.source_id", "source_records.source_class"],
            name="fk_reference_assertions_source_id_class",
            ondelete="RESTRICT",
        ),
        _enum_check("reference_assertions", "subject_type", ASSERTION_SUBJECT_TYPES),
        _enum_check("reference_assertions", "value_type", ASSERTION_VALUE_TYPES),
        _enum_check("reference_assertions", "derivation_type", DERIVATION_TYPES),
        _enum_check("reference_assertions", "source_class", SOURCE_CLASSES),
        _enum_check("reference_assertions", "legal_strength", ASSERTION_LEGAL_STRENGTHS),
        _enum_check("reference_assertions", "verification_status", VERIFICATION_STATUSES),
        _enum_check(
            "reference_assertions", "verification_method", ASSERTION_VERIFICATION_METHODS
        ),
        CheckConstraint(
            "(source_id IS NULL AND source_class IS NULL) "
            "OR (source_id IS NOT NULL AND source_class IS NOT NULL)",
            name="ck_ra_source_class_pair",
        ),
        # INV-016
        CheckConstraint(
            "(derivation_type = 'DIRECT_SOURCE' AND source_id IS NOT NULL "
            "AND calculation_rule_id IS NULL) "
            "OR (derivation_type = 'CALCULATED' AND source_id IS NULL "
            "AND calculation_rule_id IS NOT NULL) "
            "OR (derivation_type = 'CURATED_INTERNAL' AND source_id IS NOT NULL "
            "AND source_class = 'SOURCE_E_PROOFMED')",
            name="ck_ra_inv016",
        ),
        Index(
            "ix_reference_assertions_release_subject",
            "release_id",
            "subject_type",
            "subject_id",
        ),
        Index("ix_reference_assertions_source_id", "source_id"),
        Index("ix_reference_assertions_calculation_rule_id", "calculation_rule_id"),
    )

    assertion_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk("reference_releases.release_id", "reference_assertions", "release_id"),
        nullable=False,
    )
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    field_name: Mapped[str] = mapped_column(String(128), nullable=False)
    assertion_value: Mapped[Any] = mapped_column(PortableJSON, nullable=False)
    normalized_value: Mapped[Any | None] = mapped_column(PortableJSON, nullable=True)
    value_type: Mapped[str] = mapped_column(String(16), nullable=False)
    derivation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    calculation_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        _fk(
            "fee_calculation_rules.calculation_rule_id",
            "reference_assertions",
            "calculation_rule_id",
        ),
        nullable=True,
    )
    source_locator: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_class: Mapped[str | None] = mapped_column(String(32), nullable=True)
    legal_strength: Mapped[str | None] = mapped_column(String(32), nullable=True)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'UNVERIFIED'")
    )
    verification_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(UserRef, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assertion_hash: Mapped[str | None] = mapped_column(HashColumn, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# 5. ASSERTION_DEPENDENCY
# ---------------------------------------------------------------------------


class AssertionDependency(Base):
    """5. ASSERTION_DEPENDENCY - explizite Ableitungskette berechneter Assertions."""

    __tablename__ = "assertion_dependencies"
    __table_args__ = (
        CheckConstraint(
            "derived_assertion_id != input_assertion_id",
            name="ck_ad_not_self",
        ),
        Index("ix_assertion_dependencies_release_id", "release_id"),
        Index("ix_assertion_dependencies_derived_assertion_id", "derived_assertion_id"),
        Index("ix_assertion_dependencies_input_assertion_id", "input_assertion_id"),
        Index("ix_assertion_dependencies_calculation_rule_id", "calculation_rule_id"),
    )

    dependency_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk("reference_releases.release_id", "assertion_dependencies", "release_id"),
        nullable=False,
    )
    derived_assertion_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk(
            "reference_assertions.assertion_id",
            "assertion_dependencies",
            "derived_assertion_id",
        ),
        nullable=False,
    )
    input_assertion_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk(
            "reference_assertions.assertion_id",
            "assertion_dependencies",
            "input_assertion_id",
        ),
        nullable=False,
    )
    # Offene Liste (OPERAND_1, OPERAND_2, OPERAND_3, OPERAND_N, DIVISOR, MULTIPLIER, ...);
    # ROUNDING_RULE_REF ist laut V1.1.2 nicht zulaessig (Anwendungsregel, WP-06).
    dependency_role: Mapped[str] = mapped_column(String(32), nullable=False)
    calculation_rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk(
            "fee_calculation_rules.calculation_rule_id",
            "assertion_dependencies",
            "calculation_rule_id",
        ),
        nullable=False,
    )
    ordering: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


# ---------------------------------------------------------------------------
# 6. GOA_REFERENCE_ENTRY
# ---------------------------------------------------------------------------


class GoaReferenceEntry(Base):
    """6. GOA_REFERENCE_ENTRY - materialisierte Projektion eines GOAE-Codes."""

    __tablename__ = "goa_reference_entries"
    __table_args__ = (
        _enum_check("goa_reference_entries", "category", ENTRY_CATEGORIES),
        _enum_check("goa_reference_entries", "verification_status", VERIFICATION_STATUSES),
        CheckConstraint(
            "superseded_by_entry_id IS NULL OR superseded_by_entry_id != entry_id",
            name="ck_gre_not_self_superseded",
        ),
        Index("ix_goa_reference_entries_release_code", "release_id", "code"),
        Index("ix_goa_reference_entries_factor_rule_id", "factor_rule_id"),
        Index("ix_goa_reference_entries_fee_calculation_rule_id", "fee_calculation_rule_id"),
        Index("ix_goa_reference_entries_duration_rule_id", "duration_rule_id"),
        Index("ix_goa_reference_entries_frequency_rule_id", "frequency_rule_id"),
        Index("ix_goa_reference_entries_primary_source_id", "primary_source_id"),
        Index("ix_goa_reference_entries_superseded_by_entry_id", "superseded_by_entry_id"),
    )

    entry_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk("reference_releases.release_id", "goa_reference_entries", "release_id"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    official_title: Mapped[str] = mapped_column(String(512), nullable=False)
    patient_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    section: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subsection: Mapped[str | None] = mapped_column(String(64), nullable=True)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    point_value_eur: Mapped[Decimal | None] = mapped_column(DecimalColumn, nullable=True)
    simple_fee: Mapped[Decimal | None] = mapped_column(DecimalColumn, nullable=True)
    threshold_factor: Mapped[Decimal | None] = mapped_column(DecimalColumn, nullable=True)
    max_factor: Mapped[Decimal | None] = mapped_column(DecimalColumn, nullable=True)
    threshold_fee: Mapped[Decimal | None] = mapped_column(DecimalColumn, nullable=True)
    max_fee: Mapped[Decimal | None] = mapped_column(DecimalColumn, nullable=True)
    factor_rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk("factor_rules.factor_rule_id", "goa_reference_entries", "factor_rule_id"),
        nullable=False,
    )
    fee_calculation_rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk(
            "fee_calculation_rules.calculation_rule_id",
            "goa_reference_entries",
            "fee_calculation_rule_id",
        ),
        nullable=False,
    )
    duration_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        _fk("billing_rules.rule_id", "goa_reference_entries", "duration_rule_id"),
        nullable=True,
    )
    frequency_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        _fk("billing_rules.rule_id", "goa_reference_entries", "frequency_rule_id"),
        nullable=True,
    )
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    superseded_by_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        _fk("goa_reference_entries.entry_id", "goa_reference_entries", "superseded_by_entry_id"),
        nullable=True,
    )
    primary_source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk("source_records.source_id", "goa_reference_entries", "primary_source_id"),
        nullable=False,
    )
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'UNVERIFIED'")
    )
    verified_by: Mapped[str | None] = mapped_column(UserRef, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    entry_hash: Mapped[str | None] = mapped_column(HashColumn, nullable=True)


# ---------------------------------------------------------------------------
# 7. FACTOR_RULE
# ---------------------------------------------------------------------------


class FactorRule(Base):
    """7. FACTOR_RULE - Multiplikator-Rahmen (Schwellen-/Hoechstfaktor)."""

    __tablename__ = "factor_rules"
    __table_args__ = (
        _enum_check("factor_rules", "scope_type", FACTOR_SCOPE_TYPES),
        _enum_check("factor_rules", "legal_strength", FACTOR_LEGAL_STRENGTHS),
        _enum_check("factor_rules", "verification_status", VERIFICATION_STATUSES),
        Index("ix_factor_rules_release_id", "release_id"),
        Index("ix_factor_rules_source_id", "source_id"),
    )

    factor_rule_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk("reference_releases.release_id", "factor_rules", "release_id"),
        nullable=False,
    )
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    threshold_factor: Mapped[Decimal] = mapped_column(DecimalColumn, nullable=False)
    max_factor: Mapped[Decimal] = mapped_column(DecimalColumn, nullable=False)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scope_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk("source_records.source_id", "factor_rules", "source_id"),
        nullable=False,
    )
    source_locator: Mapped[str | None] = mapped_column(String(512), nullable=True)
    legal_strength: Mapped[str] = mapped_column(String(32), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'UNVERIFIED'")
    )
    verified_by: Mapped[str | None] = mapped_column(UserRef, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_hash: Mapped[str | None] = mapped_column(HashColumn, nullable=True)


# ---------------------------------------------------------------------------
# 8. FEE_CALCULATION_RULE
# ---------------------------------------------------------------------------


class FeeCalculationRule(Base):
    """8. FEE_CALCULATION_RULE - Gebuehrenberechnungsmechanik mit Hash-Tracking."""

    __tablename__ = "fee_calculation_rules"
    __table_args__ = (
        _enum_check("fee_calculation_rules", "formula_type", FORMULA_TYPES),
        _enum_check("fee_calculation_rules", "rounding_mode", ROUNDING_MODES),
        _enum_check("fee_calculation_rules", "rounding_precision", ROUNDING_PRECISIONS),
        _enum_check("fee_calculation_rules", "rounding_stage", ROUNDING_STAGES),
        _enum_check("fee_calculation_rules", "rule_hash_algorithm", HASH_ALGORITHMS),
        _enum_check("fee_calculation_rules", "legal_strength", CALCULATION_LEGAL_STRENGTHS),
        _enum_check("fee_calculation_rules", "verification_status", VERIFICATION_STATUSES_3),
        Index("ix_fee_calculation_rules_release_id", "release_id"),
        Index("ix_fee_calculation_rules_source_id", "source_id"),
    )

    calculation_rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    release_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk("reference_releases.release_id", "fee_calculation_rules", "release_id"),
        nullable=False,
    )
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    formula_type: Mapped[str] = mapped_column(String(32), nullable=False)
    formula_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    rounding_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    rounding_precision: Mapped[str] = mapped_column(String(16), nullable=False)
    rounding_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_hash: Mapped[str | None] = mapped_column(HashColumn, nullable=True)
    rule_hash_algorithm: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk("source_records.source_id", "fee_calculation_rules", "source_id"),
        nullable=False,
    )
    source_locator: Mapped[str | None] = mapped_column(String(512), nullable=True)
    legal_strength: Mapped[str] = mapped_column(String(32), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'UNVERIFIED'")
    )
    verified_by: Mapped[str | None] = mapped_column(UserRef, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# 9. BILLING_RULE
# ---------------------------------------------------------------------------


class BillingRule(Base):
    """9. BILLING_RULE - maschinenlesbare Ausschluss-/Kombinations-/Restriktionsregel."""

    __tablename__ = "billing_rules"
    __table_args__ = (
        UniqueConstraint("condition_group_id", name="uq_billing_rules_condition_group"),
        _enum_check("billing_rules", "rule_type", BILLING_RULE_TYPES),
        _enum_check("billing_rules", "temporal_scope", TEMPORAL_SCOPES),
        _enum_check("billing_rules", "legal_strength", BILLING_LEGAL_STRENGTHS),
        _enum_check("billing_rules", "verification_status", VERIFICATION_STATUSES_3),
        CheckConstraint(
            "temporal_scope_source_id IS NULL OR temporal_scope = 'SOURCE_DEFINED'",
            name="ck_br_temporal_source",
        ),
        Index("ix_billing_rules_release_id", "release_id"),
        Index("ix_billing_rules_source_id", "source_id"),
        Index("ix_billing_rules_temporal_scope_source_id", "temporal_scope_source_id"),
        Index("ix_billing_rules_patient_message_policy_id", "patient_message_policy_id"),
    )

    rule_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk("reference_releases.release_id", "billing_rules", "release_id"),
        nullable=False,
    )
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    rule_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    condition_group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk("condition_groups.condition_group_id", "billing_rules", "condition_group_id"),
        nullable=False,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk("source_records.source_id", "billing_rules", "source_id"),
        nullable=False,
    )
    source_locator: Mapped[str | None] = mapped_column(String(512), nullable=True)
    temporal_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    temporal_scope_source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        _fk("source_records.source_id", "billing_rules", "temporal_scope_source_id"),
        nullable=True,
    )
    legal_strength: Mapped[str] = mapped_column(String(32), nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'UNVERIFIED'")
    )
    verified_by: Mapped[str | None] = mapped_column(UserRef, nullable=True)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    patient_message_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        _fk(
            "patient_message_policies.policy_id",
            "billing_rules",
            "patient_message_policy_id",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    rule_hash: Mapped[str | None] = mapped_column(HashColumn, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# 10. CONDITION_GROUP
# ---------------------------------------------------------------------------


class ConditionGroup(Base):
    """10. CONDITION_GROUP - rekursiv verschachtelte Boolesche Bedingungsgruppe."""

    __tablename__ = "condition_groups"
    __table_args__ = (
        _enum_check("condition_groups", "logical_operator", LOGICAL_OPERATORS),
        _enum_check("condition_groups", "verification_status", VERIFICATION_STATUSES),
        CheckConstraint(
            "parent_group_id IS NULL OR parent_group_id != condition_group_id",
            name="ck_cg_not_self_parent",
        ),
        Index("ix_condition_groups_release_id", "release_id"),
        Index("ix_condition_groups_parent_group_id", "parent_group_id"),
        Index("ix_condition_groups_source_id", "source_id"),
    )

    condition_group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    release_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk("reference_releases.release_id", "condition_groups", "release_id"),
        nullable=False,
    )
    logical_operator: Mapped[str] = mapped_column(String(8), nullable=False)
    parent_group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        _fk("condition_groups.condition_group_id", "condition_groups", "parent_group_id"),
        nullable=True,
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        _fk("source_records.source_id", "condition_groups", "source_id"),
        nullable=True,
    )
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'UNVERIFIED'")
    )


# ---------------------------------------------------------------------------
# 11. BILLING_RULE_CONDITION
# ---------------------------------------------------------------------------


class BillingRuleCondition(Base):
    """11. BILLING_RULE_CONDITION - einzelne Bedingung innerhalb einer Gruppe."""

    __tablename__ = "billing_rule_conditions"
    __table_args__ = (
        _enum_check("billing_rule_conditions", "verification_status", VERIFICATION_STATUSES_2),
        Index("ix_billing_rule_conditions_condition_group_id", "condition_group_id"),
        Index("ix_billing_rule_conditions_source_id", "source_id"),
    )

    condition_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    condition_group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk(
            "condition_groups.condition_group_id",
            "billing_rule_conditions",
            "condition_group_id",
        ),
        nullable=False,
    )
    # Offene Operator-Liste (EQUALS, IN, GREATER_THAN, ..., FREQUENCY_LIMIT, ...): kein CHECK.
    operator: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str] = mapped_column(String(128), nullable=False)
    operand: Mapped[Any | None] = mapped_column(PortableJSON, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        _fk("source_records.source_id", "billing_rule_conditions", "source_id"),
        nullable=True,
    )
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'UNVERIFIED'")
    )


# ---------------------------------------------------------------------------
# 12. BILLING_RULE_CODE
# ---------------------------------------------------------------------------


class BillingRuleCode(Base):
    """12. BILLING_RULE_CODE - normalisierte Regel-zu-Eintrag-Zuordnung (entry_id FK)."""

    __tablename__ = "billing_rule_codes"
    __table_args__ = (
        _enum_check("billing_rule_codes", "role", RULE_CODE_ROLES),
        Index("ix_billing_rule_codes_rule_id", "rule_id"),
        Index("ix_billing_rule_codes_entry_id", "entry_id"),
    )

    rule_code_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk("billing_rules.rule_id", "billing_rule_codes", "rule_id"),
        nullable=False,
    )
    entry_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk("goa_reference_entries.entry_id", "billing_rule_codes", "entry_id"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


# ---------------------------------------------------------------------------
# 13. ANALOG_REFERENCE
# ---------------------------------------------------------------------------


class AnalogReference(Base):
    """13. ANALOG_REFERENCE - wiederverwendbare Analog-Referenzfakten (keine Rechnungsdaten)."""

    __tablename__ = "analog_references"
    __table_args__ = (
        _enum_check("analog_references", "recommendation_type", RECOMMENDATION_TYPES),
        _enum_check("analog_references", "legal_strength", ANALOG_LEGAL_STRENGTHS),
        _enum_check("analog_references", "verification_status", VERIFICATION_STATUSES_3),
        Index("ix_analog_references_release_id", "release_id"),
        Index("ix_analog_references_recommendation_source_id", "recommendation_source_id"),
        Index("ix_analog_references_patient_message_policy_id", "patient_message_policy_id"),
    )

    analog_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk("reference_releases.release_id", "analog_references", "release_id"),
        nullable=False,
    )
    analog_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    analog_equivalent_reference_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    analog_equivalent_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    recommendation_source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        _fk("source_records.source_id", "analog_references", "recommendation_source_id"),
        nullable=True,
    )
    legal_strength: Mapped[str] = mapped_column(String(32), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'UNVERIFIED'")
    )
    verified_by: Mapped[str | None] = mapped_column(UserRef, nullable=True)
    patient_message_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        _fk(
            "patient_message_policies.policy_id",
            "analog_references",
            "patient_message_policy_id",
        ),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# 14. VERIFICATION_RECORD
# ---------------------------------------------------------------------------


class VerificationRecord(Base):
    """14. VERIFICATION_RECORD - Verifikations-/Review-Historie (polymorph, ohne FK)."""

    __tablename__ = "verification_records"
    __table_args__ = (
        _enum_check("verification_records", "entity_type", VERIFICATION_ENTITY_TYPES),
        _enum_check("verification_records", "verification_level", VERIFICATION_STATUSES),
        _enum_check("verification_records", "confidence_level", CONFIDENCE_LEVELS),
        Index("ix_verification_records_entity", "entity_type", "entity_id"),
    )

    verification_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    verification_level: Mapped[str] = mapped_column(String(32), nullable=False)
    verification_date: Mapped[date] = mapped_column(Date, nullable=False)
    verified_by: Mapped[str] = mapped_column(UserRef, nullable=False)
    verification_method: Mapped[str | None] = mapped_column(String(512), nullable=True)
    findings: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_level: Mapped[str | None] = mapped_column(String(32), nullable=True)


# ---------------------------------------------------------------------------
# 15. PATIENT_MESSAGE_POLICY
# ---------------------------------------------------------------------------


class PatientMessagePolicy(Base):
    """15. PATIENT_MESSAGE_POLICY - neutrale Patienten-Formulierungsrichtlinie."""

    __tablename__ = "patient_message_policies"
    __table_args__ = (
        _enum_check("patient_message_policies", "finding_type", FINDING_TYPES),
        _enum_check("patient_message_policies", "evidence_level", EVIDENCE_LEVELS),
        _enum_check("patient_message_policies", "recommended_tone", RECOMMENDED_TONES),
    )

    policy_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    finding_type: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_level: Mapped[str] = mapped_column(String(32), nullable=False)
    safe_message_template: Mapped[str] = mapped_column(Text, nullable=False)
    should_reference_source: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    source_reference_format: Mapped[str | None] = mapped_column(String(512), nullable=True)
    recommended_tone: Mapped[str] = mapped_column(String(16), nullable=False)
    avoid_language: Mapped[Any | None] = mapped_column(PortableJSON, nullable=True)


# ---------------------------------------------------------------------------
# 16. AUDIT_REFERENCE_SNAPSHOT
# ---------------------------------------------------------------------------


class AuditReferenceSnapshot(Base):
    """16. AUDIT_REFERENCE_SNAPSHOT - leichtgewichtiger Referenzzustand zu Audit-Beginn."""

    __tablename__ = "audit_reference_snapshots"
    __table_args__ = (
        Index("ix_audit_reference_snapshots_audit_id", "audit_id"),
        Index(
            "ix_audit_reference_snapshots_applicable_fee_schedule_edition_id",
            "applicable_fee_schedule_edition_id",
        ),
        Index(
            "ix_audit_reference_snapshots_applicable_reference_release_id",
            "applicable_reference_release_id",
        ),
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    audit_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)  # kein FK (N-4)
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    applicable_fee_schedule_edition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk(
            "fee_schedule_editions.fee_schedule_edition_id",
            "audit_reference_snapshots",
            "applicable_fee_schedule_edition_id",
        ),
        nullable=False,
    )
    applicable_reference_release_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk(
            "reference_releases.release_id",
            "audit_reference_snapshots",
            "applicable_reference_release_id",
        ),
        nullable=False,
    )
    audit_engine_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    entries_used_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rules_used_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assertions_used_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------------------
# 17. AUDIT_EVIDENCE_MANIFEST
# ---------------------------------------------------------------------------


class AuditEvidenceManifest(Base):
    """17. AUDIT_EVIDENCE_MANIFEST - materialisierte, unveraenderliche Evidenz (nur Struktur)."""

    __tablename__ = "audit_evidence_manifests"
    __table_args__ = (
        _enum_check("audit_evidence_manifests", "manifest_hash_algorithm", HASH_ALGORITHMS),
        CheckConstraint(
            "finalized_at IS NULL OR manifest_hash IS NOT NULL",
            name="ck_aem_finalized_has_hash",
        ),
        Index("ix_audit_evidence_manifests_audit_id", "audit_id"),
        Index("ix_audit_evidence_manifests_snapshot_id", "snapshot_id"),
        Index("ix_audit_evidence_manifests_fee_schedule_edition_id", "fee_schedule_edition_id"),
        Index("ix_audit_evidence_manifests_reference_release_id", "reference_release_id"),
    )

    manifest_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    audit_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)  # kein FK (N-4)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk(
            "audit_reference_snapshots.snapshot_id",
            "audit_evidence_manifests",
            "snapshot_id",
        ),
        nullable=False,
    )
    fee_schedule_edition_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk(
            "fee_schedule_editions.fee_schedule_edition_id",
            "audit_evidence_manifests",
            "fee_schedule_edition_id",
        ),
        nullable=False,
    )
    reference_release_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        _fk(
            "reference_releases.release_id",
            "audit_evidence_manifests",
            "reference_release_id",
        ),
        nullable=False,
    )
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entries_used: Mapped[Any] = mapped_column(
        PortableJSON, nullable=False, server_default=text("'[]'")
    )
    assertions_used: Mapped[Any] = mapped_column(
        PortableJSON, nullable=False, server_default=text("'[]'")
    )
    fee_calculation_rules_used: Mapped[Any] = mapped_column(
        PortableJSON, nullable=False, server_default=text("'[]'")
    )
    conditions_used: Mapped[Any] = mapped_column(
        PortableJSON, nullable=False, server_default=text("'[]'")
    )
    rules_applied: Mapped[Any] = mapped_column(
        PortableJSON, nullable=False, server_default=text("'[]'")
    )
    sources_used: Mapped[Any] = mapped_column(
        PortableJSON, nullable=False, server_default=text("'[]'")
    )
    structured_findings: Mapped[Any | None] = mapped_column(PortableJSON, nullable=True)
    manifest_hash: Mapped[str | None] = mapped_column(HashColumn, nullable=True)
    manifest_hash_algorithm: Mapped[str | None] = mapped_column(String(16), nullable=True)


# Kanonische Tabellenliste in FK-Abhaengigkeitsreihenfolge (Erzeugung).
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

__all__ = [
    "REFERENCE_CORE_TABLES",
    "FeeScheduleEdition",
    "ReferenceRelease",
    "SourceRecord",
    "ReferenceAssertion",
    "AssertionDependency",
    "GoaReferenceEntry",
    "FactorRule",
    "FeeCalculationRule",
    "BillingRule",
    "ConditionGroup",
    "BillingRuleCondition",
    "BillingRuleCode",
    "AnalogReference",
    "VerificationRecord",
    "PatientMessagePolicy",
    "AuditReferenceSnapshot",
    "AuditEvidenceManifest",
]
