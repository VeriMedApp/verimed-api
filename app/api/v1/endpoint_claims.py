"""API-Endpunkte (v1) rund um die Validierung medizinischer Rechnungen."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.goa import GOAZiffer
from app.schemas.claim import (
    BilledZiffer,
    ClaimValidationReport,
    ClaimValidationRequest,
    ParseAndValidateResponse,
)
from app.schemas.goa import GOAZifferRead
from app.services import ocr as ocr_service
from app.services.validator import ClaimValidator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/claims", tags=["claims"])

_RAW_TEXT_EXCERPT_LIMIT = 2000


@router.post(
    "/validate",
    response_model=ClaimValidationReport,
    status_code=status.HTTP_200_OK,
    summary="Rechnung anhand von GOAE-Regeln und Geofence-Zeiten validieren",
)
async def validate_claim(
    payload: ClaimValidationRequest,
    db: AsyncSession = Depends(get_db),
) -> ClaimValidationReport:
    """Fuehrt die regelbasierte Plausibilitaetspruefung einer Rechnung durch.

    Es werden eine Zeit-Plausibilitaetspruefung (Geofence-Dauer vs. Regelzeiten)
    sowie eine Ausschlusspruefung (gegenseitig nicht abrechenbare Ziffern)
    durchgefuehrt. Zurueckgegeben wird ein umfassender Bericht inklusive
    patientenfreundlicher Uebersetzungen.
    """
    try:
        validator = ClaimValidator(db)
        report = await validator.validate(payload)
    except Exception as exc:  # defensive: unerwartete Engine-Fehler abfangen
        logger.exception("Validierung fehlgeschlagen fuer Patient %s", payload.patient_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Die Validierung konnte nicht abgeschlossen werden.",
        ) from exc
    return report


@router.post(
    "/parse-and-validate",
    response_model=ParseAndValidateResponse,
    status_code=status.HTTP_200_OK,
    summary="Rechnungsfoto/-PDF automatisch auslesen und sofort validieren",
)
async def parse_and_validate_claim(
    geofence_arrival: datetime = Form(..., description="Ankunftszeit (Geofence)."),
    geofence_departure: datetime = Form(..., description="Abfahrtszeit (Geofence)."),
    patient_id: str = Form("mobile-scan", description="Eindeutige Patienten-ID."),
    praxis_name: str = Form("Unbekannte Praxis", description="Name der Praxis."),
    total_billed_amount: float = Form(0.0, description="Gesamtbetrag in Euro."),
    file: UploadFile = File(..., description="Foto (JPEG/PNG) oder PDF der Rechnung."),
    db: AsyncSession = Depends(get_db),
) -> ParseAndValidateResponse:
    """Liest eine fotografierte/gescannte Rechnung aus und validiert sie direkt.

    Extrahiert per Regex-Heuristik GOAE-Ziffern, Steigerungsfaktoren und
    Begruendungstexte aus dem hochgeladenen Bild oder PDF und fuehrt
    anschliessend dieselbe Plausibilitaetspruefung wie `/claims/validate` durch.
    """
    data = await file.read()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Die hochgeladene Datei ist leer.",
        )

    try:
        parsed = ocr_service.parse_uploaded_invoice(file.filename, file.content_type, data)
    except ocr_service.UnsupportedFileTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        ) from exc
    except ocr_service.OCREngineUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except ocr_service.OCRError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    if not parsed.ziffern:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Es konnten keine GOAE-Ziffern auf der Rechnung erkannt "
                "werden. Bitte die Ziffern manuell auswaehlen."
            ),
        )

    billed_ziffern = [
        BilledZiffer(
            ziffer=item.ziffer,
            multiplier=item.multiplier,
            justification=item.justification,
            service_time=item.service_time,
        )
        for item in parsed.ziffern
    ]

    try:
        payload = ClaimValidationRequest(
            patient_id=patient_id,
            praxis_name=praxis_name,
            geofence_arrival=geofence_arrival,
            geofence_departure=geofence_departure,
            total_billed_amount=total_billed_amount,
            billed_ziffern=billed_ziffern,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=exc.errors()
        ) from exc

    try:
        validator = ClaimValidator(db)
        report = await validator.validate(payload)
    except Exception as exc:  # defensiv: unerwartete Engine-Fehler abfangen
        logger.exception(
            "Validierung nach OCR-Parsing fehlgeschlagen fuer Patient %s", patient_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Die Validierung konnte nicht abgeschlossen werden.",
        ) from exc

    return ParseAndValidateResponse(
        parsed_ziffern=billed_ziffern,
        raw_text_excerpt=parsed.raw_text[:_RAW_TEXT_EXCERPT_LIMIT],
        extracted_treatment_date=parsed.treatment_date,
        extracted_praxis_name=parsed.praxis_name,
        extracted_practice_email=parsed.practice_email,
        extracted_invoice_number=parsed.invoice_number,
        report=report,
    )


@router.get(
    "/catalog",
    response_model=list[GOAZifferRead],
    summary="Hinterlegten GOAE-Katalog abrufen",
)
async def list_catalog(
    db: AsyncSession = Depends(get_db),
) -> list[GOAZiffer]:
    """Gibt alle im System hinterlegten GOAE-Ziffern zurueck."""
    result = await db.execute(select(GOAZiffer).order_by(GOAZiffer.sort_order, GOAZiffer.ziffer))
    return list(result.scalars().all())
