"""Kern der Plausibilitaets- und Zeitvalidierungs-Engine.

Die `ClaimValidator`-Klasse fuehrt zwei deterministische Pruefungen durch:

1. Zeit-Plausibilitaet: Vergleicht die per Geofence gemessene Aufenthaltsdauer
   mit der Summe der GOAE-Regelzeiten (zzgl. Toleranzpuffer).
2. Ausschlusspruefung: Erkennt gegenseitig ausschliessende Ziffern auf einer
   Rechnung.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.claim import ClaimStatus
from app.models.goa import GOAZiffer
from app.schemas.claim import (
    Anomaly,
    AnomalyType,
    ClaimValidationReport,
    ClaimValidationRequest,
    ZifferReport,
)

logger = logging.getLogger(__name__)


class ClaimValidator:
    """Fuehrt die regelbasierte Validierung einer Rechnung durch."""

    def __init__(
        self,
        db: AsyncSession,
        time_tolerance_minutes: int | None = None,
    ) -> None:
        self._db = db
        self._tolerance = (
            time_tolerance_minutes
            if time_tolerance_minutes is not None
            else settings.TIME_TOLERANCE_MINUTES
        )

    async def _load_catalog(
        self, ziffern: list[str]
    ) -> dict[str, GOAZiffer]:
        """Laedt die relevanten Katalogeintraege gebuendelt aus der DB."""
        if not ziffern:
            return {}
        result = await self._db.execute(
            select(GOAZiffer).where(GOAZiffer.ziffer.in_(ziffern))
        )
        catalog = {entry.ziffer: entry for entry in result.scalars().all()}
        logger.debug(
            "Katalog geladen: %d von %d angefragten Ziffern gefunden.",
            len(catalog),
            len(set(ziffern)),
        )
        return catalog

    async def validate(
        self, request: ClaimValidationRequest
    ) -> ClaimValidationReport:
        """Validiert eine Rechnung und erzeugt einen umfassenden Bericht."""
        billed_ziffern = [item.ziffer for item in request.billed_ziffern]
        catalog = await self._load_catalog(billed_ziffern)

        anomalies: list[Anomaly] = []
        ziffer_details: list[ZifferReport] = []

        # --- Detailliste + unbekannte Ziffern aufbauen ----------------------
        required_treatment_time = 0.0
        for item in request.billed_ziffern:
            entry = catalog.get(item.ziffer)
            if entry is None:
                anomalies.append(
                    Anomaly(
                        type=AnomalyType.UNKNOWN_ZIFFER,
                        severity="warning",
                        message=(
                            f"Die abgerechnete Ziffer '{item.ziffer}' ist im "
                            "GOAE-Katalog nicht hinterlegt und konnte nicht "
                            "geprueft werden."
                        ),
                        related_ziffern=[item.ziffer],
                    )
                )
                ziffer_details.append(
                    ZifferReport(
                        ziffer=item.ziffer,
                        multiplier=item.multiplier,
                        known=False,
                    )
                )
                continue

            required_treatment_time += float(entry.rule_time_minutes)
            ziffer_details.append(
                ZifferReport(
                    ziffer=entry.ziffer,
                    multiplier=item.multiplier,
                    title_patient=entry.title_patient,
                    title_official=entry.title_official,
                    rule_time_minutes=entry.rule_time_minutes,
                    known=True,
                )
            )

        # --- Pruefung 1: Zeit-Plausibilitaet --------------------------------
        actual_duration_minutes = self._compute_duration_minutes(request)
        anomalies.extend(
            self._check_time_plausibility(
                actual_duration_minutes, required_treatment_time
            )
        )

        # --- Pruefung 2: Ausschluss-Konflikte -------------------------------
        anomalies.extend(self._check_exclusions(billed_ziffern, catalog))

        is_valid = not any(
            a.type in (AnomalyType.TIME, AnomalyType.EXCLUSION) for a in anomalies
        )
        status = (
            ClaimStatus.PROCESSED_CLEAN
            if is_valid
            else ClaimStatus.PROCESSED_FLAGGED
        )

        logger.info(
            "Validierung abgeschlossen | patient=%s | praxis=%s | "
            "valid=%s | anomalien=%d",
            request.patient_id,
            request.praxis_name,
            is_valid,
            len(anomalies),
        )

        return ClaimValidationReport(
            is_valid=is_valid,
            status=status.value,
            patient_id=request.patient_id,
            praxis_name=request.praxis_name,
            actual_duration_minutes=round(actual_duration_minutes, 2),
            required_treatment_time_minutes=round(required_treatment_time, 2),
            time_tolerance_minutes=self._tolerance,
            anomalies=anomalies,
            ziffer_details=ziffer_details,
        )

    @staticmethod
    def _compute_duration_minutes(request: ClaimValidationRequest) -> float:
        """Berechnet die Aufenthaltsdauer in Minuten aus den Geofence-Zeiten."""
        delta = request.geofence_departure - request.geofence_arrival
        return delta.total_seconds() / 60.0

    def _check_time_plausibility(
        self, actual_minutes: float, required_minutes: float
    ) -> list[Anomaly]:
        """Markiert eine Anomalie, wenn die Behandlungszeit nicht plausibel ist."""
        anomalies: list[Anomaly] = []
        allowed = actual_minutes + self._tolerance
        if required_minutes > allowed:
            anomalies.append(
                Anomaly(
                    type=AnomalyType.TIME,
                    severity="critical",
                    message=(
                        "Zeit-Auffaelligkeit: Die abgerechneten Leistungen "
                        f"erfordern rechnerisch ca. {required_minutes:.0f} "
                        "Minuten, der Praxisbesuch dauerte laut Standortdaten "
                        f"jedoch nur {actual_minutes:.0f} Minuten "
                        f"(Toleranz {self._tolerance} Min.). Die abgerechnete "
                        "Behandlungszeit erscheint nicht plausibel."
                    ),
                )
            )
        return anomalies

    @staticmethod
    def _check_exclusions(
        billed_ziffern: list[str], catalog: dict[str, GOAZiffer]
    ) -> list[Anomaly]:
        """Erkennt gegenseitig ausschliessende Ziffern auf der Rechnung."""
        anomalies: list[Anomaly] = []
        billed_set = set(billed_ziffern)
        reported_pairs: set[frozenset[str]] = set()

        for ziffer in billed_set:
            entry = catalog.get(ziffer)
            if entry is None:
                continue
            for excluded in entry.exclusion_ziffern or []:
                if excluded in billed_set:
                    pair = frozenset({ziffer, excluded})
                    if pair in reported_pairs:
                        continue
                    reported_pairs.add(pair)
                    anomalies.append(
                        Anomaly(
                            type=AnomalyType.EXCLUSION,
                            severity="critical",
                            message=(
                                f"Ausschluss-Konflikt: Die Ziffern '{ziffer}' "
                                f"und '{excluded}' duerfen nicht gemeinsam auf "
                                "derselben Rechnung abgerechnet werden."
                            ),
                            related_ziffern=sorted(pair),
                        )
                    )
        return anomalies
