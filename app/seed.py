"""Seed-Logik fuer den GOAE-Katalog.

Befuellt die Datenbank idempotent mit einem Satz Standard-Ziffern, damit die
Validierungs-Engine sofort getestet werden kann. Kann sowohl beim
Anwendungsstart als auch als eigenstaendiges Skript ausgefuehrt werden:

    python -m app.seed
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.database import AsyncSessionLocal, init_db
from app.models.goa import GOAZiffer

logger = logging.getLogger(__name__)

# Standard-GOAE-Ziffern fuer Tests und lokale Entwicklung.
SEED_ZIFFERN: list[dict[str, object]] = [
    {
        "ziffer": "1",
        "title_official": "Beratung, auch mittels Fernsprecher",
        "title_patient": "Kurzes Beratungsgespraech mit dem Arzt.",
        "rule_time_minutes": 10,
        "exclusion_ziffern": [],
    },
    {
        "ziffer": "3",
        "title_official": "Eingehende Beratung (Dauer mindestens 10 Minuten)",
        "title_patient": "Ausfuehrliches Beratungsgespraech von mehr als 10 Minuten.",
        "rule_time_minutes": 20,
        "exclusion_ziffern": ["1"],
    },
    {
        "ziffer": "5",
        "title_official": "Symptombezogene Untersuchung",
        "title_patient": "Koerperliche Untersuchung bezogen auf Ihre Beschwerden.",
        "rule_time_minutes": 15,
        "exclusion_ziffern": [],
    },
    {
        "ziffer": "250",
        "title_official": "Blutentnahme mittels Spritze oder Kanuele",
        "title_patient": "Abnahme einer Blutprobe.",
        "rule_time_minutes": 5,
        "exclusion_ziffern": [],
    },
    {
        "ziffer": "8",
        "title_official": "Untersuchung zur Erhebung des Ganzkoerperstatus",
        "title_patient": "Vollstaendige koerperliche Untersuchung (Ganzkoerper).",
        "rule_time_minutes": 30,
        "exclusion_ziffern": ["5"],
    },
]


async def seed_goa_catalog() -> int:
    """Fuegt fehlende Standard-Ziffern hinzu. Gibt die Zahl neuer Eintraege zurueck."""
    inserted = 0
    async with AsyncSessionLocal() as session:
        for data in SEED_ZIFFERN:
            existing = await session.get(GOAZiffer, data["ziffer"])
            if existing is not None:
                continue
            session.add(GOAZiffer(**data))
            inserted += 1
        if inserted:
            await session.commit()
    logger.info("Seed abgeschlossen: %d neue GOAE-Ziffern hinzugefuegt.", inserted)
    return inserted


async def _main() -> None:
    from app.config import configure_logging

    configure_logging()
    await init_db()
    count = await seed_goa_catalog()
    logger.info("Standalone-Seed fertig (%d neue Eintraege).", count)


if __name__ == "__main__":
    asyncio.run(_main())
