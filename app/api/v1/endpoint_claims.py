"""API-Endpunkte (v1) rund um die Validierung medizinischer Rechnungen."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.goa import GOAZiffer
from app.schemas.claim import ClaimValidationReport, ClaimValidationRequest
from app.schemas.goa import GOAZifferRead
from app.services.validator import ClaimValidator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/claims", tags=["claims"])


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


@router.get(
    "/catalog",
    response_model=list[GOAZifferRead],
    summary="Hinterlegten GOAE-Katalog abrufen",
)
async def list_catalog(
    db: AsyncSession = Depends(get_db),
) -> list[GOAZiffer]:
    """Gibt alle im System hinterlegten GOAE-Ziffern zurueck."""
    result = await db.execute(select(GOAZiffer).order_by(GOAZiffer.ziffer))
    return list(result.scalars().all())
