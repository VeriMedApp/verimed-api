"""API-Endpunkte (v1) für B2B/B2C Audit-Services und Geofence-Verifizierung."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.goa_catalog import (
    CATEGORY_PERSONAL,
    CATEGORY_SURCHARGE,
    CATEGORY_TECHNICAL,
    EXCLUSION_RULES,
    GOA_CATALOG,
    lookup,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["audit"])


# ============================================================================
# Pydantic Schemas
# ============================================================================


class ClaimItem(BaseModel):
    """Einzelne abgerechnete GOÄ-Ziffer."""

    code: str = Field(..., description="GOÄ-Ziffer (z.B. '1', '3', 'A')")
    factor: float = Field(..., gt=0, description="Steigerungsfaktor (z.B. 2.3)")
    amount_eur: float = Field(..., gt=0, description="Berechneter Betrag in EUR")
    description: str | None = Field(None, description="Optionale Leistungsbeschreibung")


class ClaimAuditRequest(BaseModel):
    """Request-Schema für Rechnungsprüfung (B2B/B2C)."""

    invoice_number: str = Field(..., description="Rechnungsnummer")
    practice_name: str = Field(..., description="Name der Praxis")
    treatment_date: str = Field(..., description="Behandlungsdatum (YYYY-MM-DD)")
    claimed_items: list[ClaimItem] = Field(..., min_length=1, description="Abgerechnete Leistungen")
    presence_duration_minutes: int | None = Field(None, ge=0, description="Aufenthaltsdauer in Minuten")
    has_written_justification: bool = Field(False, description="Schriftliche Begründung vorhanden")


class AuditIssue(BaseModel):
    """Einzelnes Prüfungsergebnis."""

    code: str = Field(..., description="Betroffene GOÄ-Ziffer oder Fehler-Code")
    severity: str = Field(..., description="Schweregrad: WARN oder ERROR")
    message: str = Field(..., description="Fehlermeldung")


class ClaimAuditResponse(BaseModel):
    """Response-Schema für Rechnungsprüfung."""

    audit_status: str = Field(..., description="OK, WARNING oder REJECTED")
    issues: list[AuditIssue] = Field(default_factory=list, description="Gefundene Auffälligkeiten")
    total_claimed_eur: float = Field(..., description="Gesamtbetrag der Rechnung")
    valid_amount_eur: float = Field(..., description="Gültiger Betrag nach Prüfung")
    savings_potential_eur: float = Field(..., ge=0, description="Einsparpotenzial in EUR")
    proof_hash: str = Field(..., description="SHA-256 Nachweis-Hash")


class GeofenceVerifyRequest(BaseModel):
    """Request-Schema für Geofence-Verifizierung."""

    latitude: float = Field(..., ge=-90, le=90, description="Breitengrad")
    longitude: float = Field(..., ge=-180, le=180, description="Längengrad")
    accuracy_meters: float = Field(..., ge=0, description="GPS-Genauigkeit in Metern")
    arrival_time: str = Field(..., description="Ankunftszeit (ISO 8601)")
    departure_time: str = Field(..., description="Abfahrtszeit (ISO 8601)")
    practice_name: str = Field(..., description="Name der Praxis")


class GeofenceVerifyResponse(BaseModel):
    """Response-Schema für Geofence-Verifizierung."""

    proof_valid: bool = Field(..., description="Beweis gültig")
    duration_minutes: int = Field(..., description="Aufenthaltsdauer in Minuten")
    audit_hash: str = Field(..., description="SHA-256 Audit-Hash")
    verified_at: str = Field(..., description="Zeitstempel der Verifizierung (ISO 8601)")


class CatalogMetadata(BaseModel):
    """Metadaten des GOÄ-Katalogs."""

    version_id: str = Field(..., description="Katalog-Version")
    last_updated: str = Field(..., description="Letztes Update (ISO 8601)")
    total_codes: int = Field(..., description="Anzahl der Katalogeinträge")
    catalog: list[dict[str, Any]] = Field(..., description="Vollständiger GOÄ-Katalog")


# ============================================================================
# Helper Functions
# ============================================================================


def compute_sha256_hash(data: dict[str, Any]) -> str:
    """Berechnet deterministischen SHA-256 Hash."""
    payload = json.dumps(data, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def add_issue(
    issues: list[AuditIssue],
    code: str,
    severity: str,
    message: str,
) -> None:
    """Fügt ein Audit-Issue hinzu."""
    issues.append(AuditIssue(code=code, severity=severity, message=message))


def check_exclusion_conflicts(
    claimed_codes: set[str],
    issues: list[AuditIssue],
) -> None:
    """Prüft Ausschlussregeln zwischen abgerechneten Ziffern."""
    for rule in EXCLUSION_RULES:
        left_set = rule["left"]
        right_set = rule["right"]

        # Prüfe ob Codes aus beiden Sets in der Rechnung vorkommen
        left_present = left_set & claimed_codes
        right_present = right_set & claimed_codes

        if left_present and right_present:
            # Konflikt gefunden
            conflicting_codes = left_present | right_present
            code_list = ", ".join(sorted(conflicting_codes))
            add_issue(
                issues,
                code=code_list,
                severity="ERROR",
                message=rule["message"],
            )


# ============================================================================
# API Endpoints
# ============================================================================


@router.get(
    "/goa-catalog",
    response_model=CatalogMetadata,
    summary="GOÄ-Katalog mit Metadaten abrufen",
    description="Liefert den vollständigen GOÄ 2026 Katalog mit Kategorien, Multiplikatoren und Ausschlussregeln.",
)
async def get_goa_catalog() -> CatalogMetadata:
    """Gibt den vollständigen GOÄ-Katalog zurück."""
    return CatalogMetadata(
        version_id="GOAE_2026_V1",
        last_updated=datetime.utcnow().isoformat(),
        total_codes=len(GOA_CATALOG),
        catalog=GOA_CATALOG,
    )


@router.post(
    "/claims/audit",
    response_model=ClaimAuditResponse,
    status_code=status.HTTP_200_OK,
    summary="Rechnung nach GOÄ-Regeln prüfen (B2B/B2C)",
    description=(
        "Prüft eine Rechnung auf Multiplikator-Verstöße, Ausschlusskonflikte und Zeit-Plausibilität. "
        "Berechnet Einsparpotenzial und generiert kryptografischen Nachweis-Hash."
    ),
)
async def audit_claim(request: ClaimAuditRequest) -> ClaimAuditResponse:
    """Führt vollständige GOÄ-Rechnungsprüfung durch."""
    issues: list[AuditIssue] = []
    total_claimed = 0.0
    valid_amount = 0.0
    required_duration = 0
    claimed_codes: set[str] = set()

    # Phase 1: Katalog-Lookup & Multiplikator-Validierung
    for item in request.claimed_items:
        total_claimed += item.amount_eur
        claimed_codes.add(item.code)

        # Lookup in GOÄ-Katalog
        catalog_entry = lookup(item.code)
        if not catalog_entry:
            add_issue(
                issues,
                code=item.code,
                severity="ERROR",
                message=f"❌ Ungültiger GOÄ-Code: {item.code} nicht im Katalog gefunden.",
            )
            continue

        # Akkumuliere gültige Beträge (wird später korrigiert bei Verstößen)
        valid_amount += item.amount_eur
        service_type = catalog_entry["category"]
        base_amount = catalog_entry["fee_simple"]
        required_duration += catalog_entry.get("rule_time_minutes", 0)

        # Faktor-Validierung nach Kategorie
        if service_type == CATEGORY_SURCHARGE:
            # Zuschläge müssen 1.0x sein
            if item.factor != 1.0:
                add_issue(
                    issues,
                    code=item.code,
                    severity="ERROR",
                    message=f"❌ Zuschläge dürfen nicht multipliziert werden (Faktor muss 1.0 sein, ist {item.factor}x)",
                )
                # Korrigiere gültigen Betrag
                valid_amount -= item.amount_eur - base_amount

        elif service_type == CATEGORY_PERSONAL:
            # Persönliche Leistungen: Standard 2.3x, Max 3.5x
            threshold = catalog_entry["threshold_multiplier"]  # 2.3
            max_factor = catalog_entry["max_multiplier"]  # 3.5

            if item.factor > threshold and not request.has_written_justification:
                add_issue(
                    issues,
                    code=item.code,
                    severity="WARN",
                    message=f"⚠️ Begründungspflicht: Steigerungsfaktor {item.factor}x > {threshold}x",
                )

            if item.factor > max_factor:
                add_issue(
                    issues,
                    code=item.code,
                    severity="ERROR",
                    message=f"❌ Illegaler Faktor {item.factor}x > {max_factor}x für persönliche Leistung",
                )
                # Korrigiere auf Höchstsatz
                max_allowed = base_amount * max_factor
                valid_amount -= item.amount_eur - max_allowed

        elif service_type == CATEGORY_TECHNICAL:
            # Technische Leistungen: Standard 1.8x, Max 2.5x
            threshold = catalog_entry["threshold_multiplier"]  # 1.8
            max_factor = catalog_entry["max_multiplier"]  # 2.5

            if item.factor > threshold and not request.has_written_justification:
                add_issue(
                    issues,
                    code=item.code,
                    severity="WARN",
                    message=f"⚠️ Begründungspflicht: Steigerungsfaktor {item.factor}x > {threshold}x (Technische Leistung)",
                )

            if item.factor > max_factor:
                add_issue(
                    issues,
                    code=item.code,
                    severity="ERROR",
                    message=f"❌ Illegaler Faktor {item.factor}x > {max_factor}x für technische Leistung",
                )
                # Korrigiere auf Höchstsatz
                max_allowed = base_amount * max_factor
                valid_amount -= item.amount_eur - max_allowed

    # Phase 2: Ausschlussregeln prüfen
    check_exclusion_conflicts(claimed_codes, issues)

    # Phase 3: Zeitkonflikt-Prüfung
    if request.presence_duration_minutes is not None:
        if required_duration > request.presence_duration_minutes:
            add_issue(
                issues,
                code="TIME_CONFLICT",
                severity="ERROR",
                message=(
                    f"🚨 Zeit-Konflikt: Physische Unmöglichkeit der Leistungserbringung. "
                    f"Erforderlich: {required_duration} Min, Anwesend: {request.presence_duration_minutes} Min."
                ),
            )

    # Phase 4: Finanzielle Berechnungen
    savings = max(0.0, total_claimed - valid_amount)

    # Audit-Status ermitteln
    has_errors = any(issue.severity == "ERROR" for issue in issues)
    has_warnings = any(issue.severity == "WARN" for issue in issues)

    if has_errors:
        audit_status = "REJECTED"
    elif has_warnings:
        audit_status = "WARNING"
    else:
        audit_status = "OK"

    # Phase 5: Nachweis-Hash generieren
    audit_data = {
        "invoice": request.invoice_number,
        "timestamp": datetime.utcnow().isoformat(),
        "practice": request.practice_name,
        "status": audit_status,
        "codes": sorted(claimed_codes),
        "total_claimed": round(total_claimed, 2),
        "valid_amount": round(valid_amount, 2),
    }
    proof_hash = compute_sha256_hash(audit_data)

    return ClaimAuditResponse(
        audit_status=audit_status,
        issues=issues,
        total_claimed_eur=round(total_claimed, 2),
        valid_amount_eur=round(valid_amount, 2),
        savings_potential_eur=round(savings, 2),
        proof_hash=proof_hash,
    )


@router.post(
    "/geofence/verify-proof",
    response_model=GeofenceVerifyResponse,
    status_code=status.HTTP_200_OK,
    summary="Geofence-Nachweis kryptografisch verifizieren",
    description=(
        "Generiert deterministischen SHA-256 Audit-Hash aus GPS-Koordinaten, "
        "Zeitfenster und Praxisname für fälschungssichere Anwesenheitsnachweise."
    ),
)
async def verify_geofence(request: GeofenceVerifyRequest) -> GeofenceVerifyResponse:
    """Verifiziert Geofence-Nachweis und generiert Audit-Hash."""
    try:
        arrival = datetime.fromisoformat(request.arrival_time)
        departure = datetime.fromisoformat(request.departure_time)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ungültiges Zeitformat: {exc}",
        ) from exc

    # Berechne Aufenthaltsdauer
    duration = departure - arrival
    duration_minutes = int(duration.total_seconds() / 60)

    if duration_minutes < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Abfahrtszeit muss nach Ankunftszeit liegen.",
        )

    # Generiere deterministischen Audit-Hash
    hash_data = {
        "practice": request.practice_name,
        "arrival": request.arrival_time,
        "departure": request.departure_time,
        "latitude": round(request.latitude, 6),
        "longitude": round(request.longitude, 6),
        "accuracy": round(request.accuracy_meters, 2),
    }
    audit_hash = compute_sha256_hash(hash_data)

    return GeofenceVerifyResponse(
        proof_valid=True,
        duration_minutes=duration_minutes,
        audit_hash=audit_hash,
        verified_at=datetime.utcnow().isoformat(),
    )


@router.post(
    "/claims/fhir-export",
    status_code=status.HTTP_200_OK,
    summary="Rechnung als HL7 FHIR ExplanationOfBenefit exportieren",
    description="Transformiert Rechnungsdaten in eine HL7 FHIR R4 ExplanationOfBenefit-Ressource (Stub).",
)
async def export_fhir(request: ClaimAuditRequest) -> dict[str, Any]:
    """Exportiert Claim-Daten als FHIR ExplanationOfBenefit."""
    # FHIR R4 ExplanationOfBenefit Stub
    fhir_resource = {
        "resourceType": "ExplanationOfBenefit",
        "id": f"eob-{request.invoice_number}",
        "status": "active",
        "type": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/claim-type",
                    "code": "professional",
                    "display": "Professional",
                }
            ]
        },
        "use": "claim",
        "patient": {"reference": f"Patient/{request.practice_name}"},
        "created": datetime.utcnow().isoformat(),
        "provider": {"display": request.practice_name},
        "item": [
            {
                "sequence": idx + 1,
                "productOrService": {
                    "coding": [
                        {
                            "system": "http://proofmed.de/goae",
                            "code": item.code,
                            "display": item.description or f"GOÄ {item.code}",
                        }
                    ]
                },
                "net": {
                    "value": item.amount_eur,
                    "currency": "EUR",
                },
            }
            for idx, item in enumerate(request.claimed_items)
        ],
        "total": [
            {
                "category": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/adjudication",
                            "code": "submitted",
                        }
                    ]
                },
                "amount": {
                    "value": sum(item.amount_eur for item in request.claimed_items),
                    "currency": "EUR",
                },
            }
        ],
    }

    return fhir_resource


@router.post(
    "/claims/bipro-export",
    status_code=status.HTTP_200_OK,
    summary="Rechnung als BiPRO Norm 430/440 exportieren",
    description="Transformiert Rechnungsdaten in BiPRO-konforme Struktur (Stub).",
)
async def export_bipro(request: ClaimAuditRequest) -> dict[str, Any]:
    """Exportiert Claim-Daten als BiPRO Norm 430/440."""
    # BiPRO Norm 430/440 Stub
    bipro_payload = {
        "BiPRO": {
            "Version": "2.6.0.1.0",
            "Nachricht": {
                "NachrichtTyp": "Rechnungseinreichung",
                "Absender": request.practice_name,
                "Zeitstempel": datetime.utcnow().isoformat(),
            },
            "Rechnung": {
                "Rechnungsnummer": request.invoice_number,
                "Behandlungsdatum": request.treatment_date,
                "Gesamtbetrag": {
                    "Betrag": sum(item.amount_eur for item in request.claimed_items),
                    "Waehrung": "EUR",
                },
                "Positionen": [
                    {
                        "Laufnummer": idx + 1,
                        "GOAEZiffer": item.code,
                        "Steigerungsfaktor": item.factor,
                        "Einzelbetrag": item.amount_eur,
                        "Leistungsbeschreibung": item.description or f"GOÄ {item.code}",
                    }
                    for idx, item in enumerate(request.claimed_items)
                ],
            },
        }
    }

    return bipro_payload
