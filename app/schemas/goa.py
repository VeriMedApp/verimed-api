"""Pydantic v2 Schemas fuer GOAE-Katalogeintraege."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GOAZifferBase(BaseModel):
    """Gemeinsame Felder eines GOAE-Katalogeintrags."""

    ziffer: str = Field(..., description="GOAE-Ziffer, z.B. '1', '5', '250'.")
    title_official: str = Field(
        ..., description="Offizieller, rechtlich verbindlicher Leistungstext."
    )
    title_patient: str = Field(
        ..., description="Patientenfreundliche Uebersetzung in einfacher Sprache."
    )
    rule_time_minutes: int = Field(
        0, ge=0, description="Regelzeit der Leistung in Minuten."
    )
    exclusion_ziffern: list[str] = Field(
        default_factory=list,
        description="Ziffern, die nicht gemeinsam abgerechnet werden duerfen.",
    )


class GOAZifferCreate(GOAZifferBase):
    """Schema zum Anlegen eines Katalogeintrags."""


class GOAZifferRead(GOAZifferBase):
    """Schema zur Rueckgabe eines Katalogeintrags."""

    model_config = ConfigDict(from_attributes=True)
