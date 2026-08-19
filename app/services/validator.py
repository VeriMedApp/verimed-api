"""Kern der Plausibilitaets- und Zeitvalidierungs-Engine.

Die `ClaimValidator`-Klasse fuehrt deterministische Pruefungen durch:

1. Zeit-Plausibilitaet: Summe der GOAE-Mindestdauern vs. Geofence-Anwesenheit.
2. Ausschlusspruefung: Kombinationsverbote (z. B. GOAE 1+3, 5+7/8).
3. Steigerungsfaktor: kategoriespezifische Schwellen- und Hoechstsaetze.
4. Mengengrenzen: z. B. GOAE 420 hoechstens 3x je Sitzung.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.goa_catalog import (
    CATEGORY_PERSONAL,
    CATEGORY_SURCHARGE,
    CATEGORY_TECHNICAL,
    EXCLUSION_RULES,
    GOA_BY_ZIFFER,
    lookup as catalog_lookup,
    normalize_ziffer,
)
from app.models.claim import ClaimStatus
from app.models.goa import GOAZiffer
from app.schemas.claim import (
    Anomaly,
    AnomalyType,
    BilledZiffer,
    ClaimValidationReport,
    ClaimValidationRequest,
    ZifferReport,
)

logger = logging.getLogger(__name__)

_EPS = 1e-6

MSG_JUSTIFICATION_PERSONAL = (
    "⚠️ Begründungspflicht: Steigerungsfaktor > 2,3x"
)
MSG_JUSTIFICATION_TECHNICAL = (
    "⚠️ Begründungspflicht: Steigerungsfaktor > 1,8x (Technische Leistung)"
)
MSG_ILLEGAL_FACTOR = "🚨 Unzulässiger Überschreitungsfaktor (§ 2 GOÄ)"
MSG_TIME_IMPOSSIBLE = (
    "🚨 Zeit-Konflikt: Physische Unmöglichkeit der Leistungserbringung"
)


class ClaimValidator:
    """Fuehrt die regelbasierte Validierung einer Rechnung durch."""

    def __init__(
        self,
        db: AsyncSession,
        time_tolerance_minutes: int | None = None,
    ) -> None:
        self._db = db
        # Mindestdauer vs. Anwesenheit: strikter Vergleich ohne Puffer
        # (physische Unmoeglichkeit). Der Config-Wert bleibt im Bericht sichtbar.
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

    @staticmethod
    def _resolve_meta(ziffer: str, db_catalog: dict[str, GOAZiffer]) -> dict[str, Any] | None:
        """Python-Katalog hat Vorrang; DB dient als Fallback fuer Sonderziffern."""
        py_entry = catalog_lookup(ziffer)
        if py_entry is not None:
            return py_entry
        db_entry = db_catalog.get(ziffer) or db_catalog.get(normalize_ziffer(ziffer))
        if db_entry is None:
            return None
        return {
            "ziffer": db_entry.ziffer,
            "title_official": db_entry.title_official,
            "title_patient": db_entry.title_patient,
            "rule_time_minutes": db_entry.rule_time_minutes,
            "exclusion_ziffern": db_entry.exclusion_ziffern or [],
            "category": getattr(db_entry, "category", CATEGORY_PERSONAL) or CATEGORY_PERSONAL,
            "threshold_multiplier": float(
                getattr(db_entry, "threshold_multiplier", 2.3) or 2.3
            ),
            "max_multiplier": float(getattr(db_entry, "max_multiplier", 3.5) or 3.5),
            "max_per_session": getattr(db_entry, "max_per_session", None),
        }

    async def validate(
        self, request: ClaimValidationRequest
    ) -> ClaimValidationReport:
        """Validiert eine Rechnung und erzeugt einen umfassenden Bericht."""
        billed_items = [
            item.model_copy(update={"ziffer": normalize_ziffer(item.ziffer)})
            for item in request.billed_ziffern
        ]
        billed_ziffern = [item.ziffer for item in billed_items]
        catalog = await self._load_catalog(billed_ziffern)

        anomalies: list[Anomaly] = []
        ziffer_details: list[ZifferReport] = []

        required_treatment_time = 0.0
        for item in billed_items:
            meta = self._resolve_meta(item.ziffer, catalog)
            anomalies.extend(self._check_multiplier(item, meta))

            if meta is None:
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
                        justification=item.justification,
                        known=False,
                    )
                )
                continue

            required_treatment_time += float(meta.get("rule_time_minutes") or 0)
            ziffer_details.append(
                ZifferReport(
                    ziffer=str(meta["ziffer"]),
                    multiplier=item.multiplier,
                    justification=item.justification,
                    title_patient=str(meta.get("title_patient") or ""),
                    title_official=str(meta.get("title_official") or ""),
                    rule_time_minutes=int(meta.get("rule_time_minutes") or 0),
                    known=True,
                )
            )

        actual_duration_minutes = self._compute_duration_minutes(request)
        anomalies.extend(
            self._check_time_plausibility(
                actual_duration_minutes, required_treatment_time
            )
        )
        anomalies.extend(self._check_exclusions(billed_items))
        anomalies.extend(self._check_session_limits(billed_ziffern))

        is_valid = not any(
            a.type in (AnomalyType.TIME, AnomalyType.EXCLUSION, AnomalyType.MULTIPLIER)
            for a in anomalies
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
            time_tolerance_minutes=0,
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
        """Markiert eine Anomalie, wenn die Mindestdauer die Anwesenheit uebersteigt."""
        if required_minutes <= actual_minutes + _EPS:
            return []
        return [
            Anomaly(
                type=AnomalyType.TIME,
                severity="critical",
                message=(
                    f"{MSG_TIME_IMPOSSIBLE}. Die abgerechneten Leistungen "
                    f"erfordern mindestens {required_minutes:.0f} Minuten, "
                    f"der Praxisbesuch dauerte laut Geofencing jedoch nur "
                    f"{actual_minutes:.0f} Minuten."
                ),
            )
        ]

    @staticmethod
    def _has_justification(item: BilledZiffer) -> bool:
        return bool(item.justification and item.justification.strip())

    def _check_multiplier(
        self, item: BilledZiffer, meta: dict[str, Any] | None
    ) -> list[Anomaly]:
        """Prueft Schwellenwert, Hoechstsatz und Zuschlags-Faktoren."""
        category = (meta or {}).get("category") or CATEGORY_PERSONAL
        threshold = float((meta or {}).get("threshold_multiplier") or 2.3)
        max_factor = float((meta or {}).get("max_multiplier") or 3.5)
        factor = float(item.multiplier)

        if category == CATEGORY_SURCHARGE:
            if abs(factor - 1.0) > 0.05:
                return [
                    Anomaly(
                        type=AnomalyType.MULTIPLIER,
                        severity="critical",
                        message=MSG_ILLEGAL_FACTOR,
                        related_ziffern=[item.ziffer],
                    )
                ]
            return []

        if factor > max_factor + _EPS:
            return [
                Anomaly(
                    type=AnomalyType.MULTIPLIER,
                    severity="critical",
                    message=MSG_ILLEGAL_FACTOR,
                    related_ziffern=[item.ziffer],
                )
            ]

        if factor > threshold + _EPS and not self._has_justification(item):
            warning = (
                MSG_JUSTIFICATION_TECHNICAL
                if category == CATEGORY_TECHNICAL
                else MSG_JUSTIFICATION_PERSONAL
            )
            return [
                Anomaly(
                    type=AnomalyType.MULTIPLIER,
                    severity="warning",
                    message=warning,
                    related_ziffern=[item.ziffer],
                )
            ]
        return []

    @staticmethod
    def _check_exclusions(billed_items: list[BilledZiffer]) -> list[Anomaly]:
        """Erkennt gegenseitig ausschliessende Ziffern auf der Rechnung."""
        anomalies: list[Anomaly] = []
        billed_set = {item.ziffer for item in billed_items}
        times_by_ziffer: dict[str, set[str]] = {}
        for item in billed_items:
            stamp = (item.service_time or "").strip()
            if stamp:
                times_by_ziffer.setdefault(item.ziffer, set()).add(stamp)

        reported: set[frozenset[str]] = set()
        allowed_with_times: set[frozenset[str]] = set()
        for rule in EXCLUSION_RULES:
            left: frozenset[str] = rule["left"]
            right: frozenset[str] = rule["right"]
            hit_left = billed_set & left
            hit_right = billed_set & right
            if not hit_left or not hit_right:
                continue
            related = frozenset(hit_left | hit_right)
            if related in reported:
                continue
            if rule.get("require_separate_times"):
                left_times = set().union(
                    *(times_by_ziffer.get(z, set()) for z in hit_left)
                )
                right_times = set().union(
                    *(times_by_ziffer.get(z, set()) for z in hit_right)
                )
                if left_times and right_times and left_times.isdisjoint(right_times):
                    allowed_with_times.add(related)
                    continue
            reported.add(related)
            anomalies.append(
                Anomaly(
                    type=AnomalyType.EXCLUSION,
                    severity="critical",
                    message=str(rule["message"]),
                    related_ziffern=sorted(related),
                )
            )

        # Katalog-Ausschluesse als Auffangnetz (ohne Doppelmeldung derselben Paare).
        for ziffer in billed_set:
            entry = GOA_BY_ZIFFER.get(ziffer)
            if entry is None:
                continue
            for excluded in entry.get("exclusion_ziffern") or []:
                if excluded not in billed_set:
                    continue
                pair = frozenset({ziffer, excluded})
                if pair in reported or pair in allowed_with_times:
                    continue
                if any(
                    pair <= known or known <= pair
                    for known in reported | allowed_with_times
                ):
                    continue
                reported.add(pair)
                anomalies.append(
                    Anomaly(
                        type=AnomalyType.EXCLUSION,
                        severity="critical",
                        message=(
                            f"🚨 Kombinationsverbot: Die Ziffern '{ziffer}' "
                            f"und '{excluded}' dürfen nicht gemeinsam auf "
                            "derselben Rechnung abgerechnet werden."
                        ),
                        related_ziffern=sorted(pair),
                    )
                )
        return anomalies

    @staticmethod
    def _check_session_limits(billed_ziffern: list[str]) -> list[Anomaly]:
        """Prueft Mengengrenzen je Sitzung (z. B. GOAE 420 max. 3x)."""
        anomalies: list[Anomaly] = []
        counts = Counter(billed_ziffern)
        for ziffer, count in counts.items():
            entry = GOA_BY_ZIFFER.get(ziffer)
            if not entry:
                continue
            limit = entry.get("max_per_session")
            if limit is None or count <= int(limit):
                continue
            anomalies.append(
                Anomaly(
                    type=AnomalyType.EXCLUSION,
                    severity="critical",
                    message=(
                        f"🚨 Mengenüberschreitung: GOÄ {ziffer} darf höchstens "
                        f"{int(limit)}× je Sitzung abgerechnet werden "
                        f"(hier {count}×)."
                    ),
                    related_ziffern=[ziffer],
                )
            )
        return anomalies
