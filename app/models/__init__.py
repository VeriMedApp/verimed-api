"""SQLAlchemy ORM-Modelle fuer Project VeriMed.

Der zentrale Import stellt sicher, dass alle Modelle bei der gemeinsamen
`Base.metadata` registriert sind (wichtig fuer create_all und Alembic).
"""

from app.models.claim import ClaimLineItem, ClaimStatus, MedicalClaim
from app.models.goa import GOAZiffer

__all__ = [
    "GOAZiffer",
    "MedicalClaim",
    "ClaimLineItem",
    "ClaimStatus",
]
