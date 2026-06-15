"""Pydantic v2 Schemas fuer Rechnungen, Validierungsanfragen und -berichte."""

from __future__ import annotations

import enum
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


# --- Eingehende Anfrage ------------------------------------------------------
class BilledZiffer(BaseModel):
    """Eine vom Nutzer eingereichte, abgerechnete GOAE-Position."""

    ziffer: str = Field(..., description="GOAE-Ziffer, z.B. '1'.")
    multiplier: float = Field(
        1.0, gt=0, description="Steigerungsfaktor, z.B. 2.3 oder 3.5."
    )


class ClaimValidationRequest(BaseModel):
    """Payload zum Validieren einer Rechnung anhand der Geofence-Zeiten."""

    patient_id: str = Field(..., description="Eindeutige Patienten-ID.")
    praxis_name: str = Field(..., description="Name der Praxis / des Leistungserbringers.")
    geofence_arrival: datetime = Field(..., description="Ankunftszeit (Geofence).")
    geofence_departure: datetime = Field(..., description="Abfahrtszeit (Geofence).")
    total_billed_amount: float = Field(
        0.0, ge=0, description="Gesamtbetrag der Rechnung in Euro."
    )
    billed_ziffern: list[BilledZiffer] = Field(
        ..., min_length=1, description="Liste der abgerechneten Ziffern."
    )

    @model_validator(mode="after")
    def _check_timeline(self) -> "ClaimValidationRequest":
        if self.geofence_departure <= self.geofence_arrival:
            raise ValueError(
                "geofence_departure muss nach geofence_arrival liegen."
            )
        return self


# --- Validierungsbericht -----------------------------------------------------
class AnomalyType(str, enum.Enum):
    """Kategorien moeglicher Auffaelligkeiten."""

    TIME = "time_anomaly"
    EXCLUSION = "exclusion_anomaly"
    UNKNOWN_ZIFFER = "unknown_ziffer"


class Anomaly(BaseModel):
    """Eine einzelne erkannte Auffaelligkeit im Validierungsbericht."""

    type: AnomalyType
    severity: str = Field("warning", description="'warning' oder 'critical'.")
    message: str = Field(..., description="Patientenfreundliche Erklaerung.")
    related_ziffern: list[str] = Field(default_factory=list)


class ZifferReport(BaseModel):
    """Detailangaben zu einer geprueften Ziffer im Bericht."""

    ziffer: str
    multiplier: float
    title_patient: str | None = None
    title_official: str | None = None
    rule_time_minutes: int | None = None
    known: bool = Field(
        True, description="Ob die Ziffer im GOAE-Katalog gefunden wurde."
    )


class ClaimValidationReport(BaseModel):
    """Umfassender Bericht ueber das Ergebnis der Plausibilitaetspruefung."""

    model_config = ConfigDict(use_enum_values=True)

    is_valid: bool = Field(..., description="True, wenn keine Anomalien gefunden wurden.")
    status: str = Field(..., description="Resultierender Verarbeitungsstatus.")
    patient_id: str
    praxis_name: str

    actual_duration_minutes: float = Field(
        ..., description="Tatsaechliche Aufenthaltsdauer laut Geofence."
    )
    required_treatment_time_minutes: float = Field(
        ..., description="Summe der Regelzeiten aller abgerechneten Ziffern."
    )
    time_tolerance_minutes: int = Field(
        ..., description="Angewandter Toleranzpuffer in Minuten."
    )

    anomalies: list[Anomaly] = Field(default_factory=list)
    ziffer_details: list[ZifferReport] = Field(default_factory=list)
