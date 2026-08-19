"""Seed-Logik fuer den GOAE-Katalog.

Befuellt die Datenbank idempotent mit dem kanonischen Katalog aus
``app.goa_catalog`` und aktualisiert bestehende Eintraege, damit Regelzeiten,
Ausschluesse und Kategorien nicht auf veralteten Seed-Daten stehen bleiben.

    python -m app.seed
"""

from __future__ import annotations

import asyncio
import logging

from app.database import AsyncSessionLocal, init_db
from app.goa_catalog import GOA_CATALOG
from app.models.goa import GOAZiffer

logger = logging.getLogger(__name__)

_MODEL_FIELDS = (
    "ziffer",
    "title_official",
    "title_patient",
    "rule_time_minutes",
    "exclusion_ziffern",
    "category",
    "threshold_multiplier",
    "max_multiplier",
    "fee_simple",
    "fee_threshold",
    "fee_max",
    "max_per_session",
    "sort_order",
)


def _row_payload(data: dict) -> dict:
    return {key: data.get(key) for key in _MODEL_FIELDS}


async def seed_goa_catalog() -> int:
    """Fuegt fehlende Ziffern hinzu und aktualisiert vorhandene. Gibt die Zahl neuer Eintraege zurueck."""
    inserted = 0
    updated = 0
    async with AsyncSessionLocal() as session:
        for data in GOA_CATALOG:
            payload = _row_payload(data)
            existing = await session.get(GOAZiffer, payload["ziffer"])
            if existing is None:
                session.add(GOAZiffer(**payload))
                inserted += 1
                continue
            for key, value in payload.items():
                setattr(existing, key, value)
            updated += 1
        await session.commit()
    logger.info(
        "Seed abgeschlossen: %d neue, %d aktualisierte GOAE-Ziffern.",
        inserted,
        updated,
    )
    return inserted


async def _main() -> None:
    from app.config import configure_logging

    configure_logging()
    await init_db()
    count = await seed_goa_catalog()
    logger.info("Standalone-Seed fertig (%d neue Eintraege).", count)


if __name__ == "__main__":
    asyncio.run(_main())
