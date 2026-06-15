"""Verschluesselungs-Schicht (Security-by-Design) fuer PII.

Implementiert das Fernet-Muster (symmetrische Authenticated Encryption auf
AES-Basis, AES-128-CBC + HMAC-SHA256) zur transparenten Ver- und
Entschluesselung personenbezogener Daten (PII) "at rest".

Zentrale Bausteine:

* :class:`CryptoService` - kapselt Fernet und bietet ``encrypt``/``decrypt``.
* :class:`EncryptedString` - SQLAlchemy ``TypeDecorator``, der Spaltenwerte
  beim Schreiben automatisch verschluesselt und beim Lesen entschluesselt.
  In der Datenbank liegt damit ausschliesslich der Chiffretext.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.config import settings

logger = logging.getLogger(__name__)

# Platzhalter-Default aus der Konfiguration: nur fuer lokale Entwicklung.
_INSECURE_DEFAULT_KEY = "A-32-Byte-Base64-Encoded-Key-For-Local-Dev="


def _derive_fernet_key(secret: str) -> bytes:
    """Leitet aus einem beliebigen Secret einen gueltigen Fernet-Key ab.

    Fernet erwartet einen url-safe base64-kodierten 32-Byte-Schluessel. Damit
    jeder konfigurierte String funktioniert, wird er per SHA-256 auf exakt
    32 Byte normalisiert und anschliessend base64-kodiert.
    """
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def generate_key() -> str:
    """Erzeugt einen frischen, sicheren Fernet-Schluessel (z.B. fuer .env)."""
    return Fernet.generate_key().decode("utf-8")


class CryptoService:
    """Kapselt symmetrische Ver-/Entschluesselung nach dem Fernet-Muster."""

    def __init__(self, key: str | None = None) -> None:
        secret = key or settings.ENCRYPTION_KEY
        if secret == _INSECURE_DEFAULT_KEY:
            logger.warning(
                "ENCRYPTION_KEY nutzt den unsicheren Entwicklungs-Default. "
                "In Produktion zwingend ENCRYPTION_KEY als Umgebungsvariable "
                "setzen (z.B. via app.services.crypto.generate_key())."
            )
        self._fernet = Fernet(_derive_fernet_key(secret))

    def encrypt(self, plaintext: str) -> str:
        """Verschluesselt einen Klartext und gibt den Chiffretext (str) zurueck."""
        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt(self, token: str) -> str:
        """Entschluesselt einen Chiffretext.

        Faellt auf den Rohwert zurueck, falls dieser (noch) nicht
        verschluesselt war - so bleiben evtl. vorhandene Altdaten lesbar.
        """
        try:
            return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError):
            logger.debug("Wert war nicht (gueltig) verschluesselt - Rohwert genutzt.")
            return token


@lru_cache
def get_crypto() -> CryptoService:
    """Gecachte Singleton-Instanz des CryptoService."""
    return CryptoService()


class EncryptedString(TypeDecorator):
    """SQLAlchemy-Typ, der String-Spalten transparent ver-/entschluesselt.

    * ``process_bind_param``: Klartext -> Chiffretext (beim Schreiben)
    * ``process_result_value``: Chiffretext -> Klartext (beim Lesen)

    Die zugrunde liegende Spalte ist ``Text``, da Chiffretexte deutlich laenger
    sind als der urspruengliche Klartext.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:  # noqa: ANN001
        if value is None:
            return None
        return get_crypto().encrypt(str(value))

    def process_result_value(self, value: str | None, dialect) -> str | None:  # noqa: ANN001
        if value is None:
            return None
        return get_crypto().decrypt(value)
