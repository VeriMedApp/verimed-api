"""Pydantic v2 Schemas fuer GOAE-Katalogeintraege."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GOAZifferBase(BaseModel):
    """Gemeinsame Felder eines GOAE-Katalogeintrags."""

    ziffer: str = Field(..., description="GOAE-Ziffer, z.B. '1', '5', '250', 'D'.")
    title_official: str = Field(
        ..., description="Offizieller, rechtlich verbindlicher Leistungstext."
    )
    title_patient: str = Field(
        ..., description="Patientenfreundliche Uebersetzung in einfacher Sprache."
    )
    rule_time_minutes: int = Field(
        0, ge=0, description="Mindest-Regelzeit der Leistung in Minuten."
    )
    exclusion_ziffern: list[str] = Field(
        default_factory=list,
        description="Ziffern, die nicht gemeinsam abgerechnet werden duerfen.",
    )
    category: str = Field(
        "personal",
        description="personal | technical | surcharge",
    )
    threshold_multiplier: float = Field(
        2.3, description="Schwellenwert, ab dem eine Begruendung noetig ist."
    )
    max_multiplier: float = Field(
        3.5, description="Zulaessiger Hoechstsatz (§ 5 GOAE) bzw. 1.0 bei Zuschlaegen."
    )
    fee_simple: float = Field(0.0, description="Einfachsatz (1,0x) in Euro.")
    fee_threshold: float = Field(
        0.0, description="Schwellenwert-Betrag (2,3x bzw. 1,8x) in Euro."
    )
    fee_max: float = Field(0.0, description="Hoechstsatz-Betrag in Euro.")
    max_per_session: int | None = Field(
        None, description="Maximale Anzahl je Sitzung, z.B. 3 fuer GOAE 420."
    )
    sort_order: int = Field(0, description="Anzeige-Reihenfolge im Katalog.")


class GOAZifferCreate(GOAZifferBase):
    """Schema zum Anlegen eines Katalogeintrags."""


class GOAZifferRead(GOAZifferBase):
    """Schema zur Rueckgabe eines Katalogeintrags."""

    model_config = ConfigDict(from_attributes=True)
