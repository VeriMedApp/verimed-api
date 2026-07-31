"""ORM-Modelle fuer Patientenbesuche, Geofencing-Logs und Rechnungen."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.services.crypto import EncryptedString


class ClaimStatus(str, enum.Enum):
    """Verarbeitungsstatus einer eingereichten Rechnung."""

    PENDING = "pending"
    PROCESSED_FLAGGED = "processed_flagged"
    PROCESSED_CLEAN = "processed_clean"


class MedicalClaim(Base):
    """Eine eingescannte Rechnung, verknuepft mit einem Geofence-Besuch."""

    __tablename__ = "medical_claims"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    # PII: wird transparent verschluesselt (Encryption at Rest). Da der
    # Chiffretext bei Fernet nicht deterministisch ist, sind Gleichheits-
    # Suchen/Indizes auf diesen Spalten nicht sinnvoll.
    patient_id: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    praxis_name: Mapped[str] = mapped_column(EncryptedString, nullable=False)

    geofence_arrival: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    geofence_departure: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    total_billed_amount: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    status: Mapped[ClaimStatus] = mapped_column(
        SAEnum(ClaimStatus, name="claim_status"),
        nullable=False,
        default=ClaimStatus.PENDING,
    )

    line_items: Mapped[list["ClaimLineItem"]] = relationship(
        back_populates="claim",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover - reine Debug-Hilfe
        return f"<MedicalClaim id={self.id!r} status={self.status.value!r}>"


class ClaimLineItem(Base):
    """Eine einzelne abgerechnete GOAE-Position innerhalb einer Rechnung."""

    __tablename__ = "claim_line_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("medical_claims.id", ondelete="CASCADE"), index=True
    )
    ziffer: Mapped[str] = mapped_column(
        String(16), ForeignKey("goa_ziffern.ziffer"), nullable=False
    )
    multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=2.3)
    # Schriftliche Begruendung fuer Steigerungsfaktoren > 2,3 (GOAE-Pflichtangabe).
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)

    claim: Mapped["MedicalClaim"] = relationship(back_populates="line_items")

    def __repr__(self) -> str:  # pragma: no cover - reine Debug-Hilfe
        return (
            f"<ClaimLineItem ziffer={self.ziffer!r} "
            f"multiplier={self.multiplier}>"
        )
