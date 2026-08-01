"""Service-Schicht (Geschaeftslogik) fuer ProofMed.

``ClaimValidator`` wird lazy via PEP 562 bereitgestellt, um einen zirkulaeren
Import zu vermeiden (models.claim -> services.crypto -> services-Paket).
"""

from typing import TYPE_CHECKING, Any

from app.services.crypto import CryptoService, EncryptedString, get_crypto

if TYPE_CHECKING:  # nur fuer Typpruefer, kein Laufzeit-Import
    from app.services.validator import ClaimValidator

__all__ = [
    "ClaimValidator",
    "CryptoService",
    "EncryptedString",
    "get_crypto",
]


def __getattr__(name: str) -> Any:
    if name == "ClaimValidator":
        from app.services.validator import ClaimValidator

        return ClaimValidator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
