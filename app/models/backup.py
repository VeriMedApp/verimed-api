"""ORM-Modelle fuer Zero-Knowledge verschluesselte Cloud-Backups."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EncryptedBackup(Base):
    """Zero-Knowledge verschluesseltes Cloud-Backup.
    
    Enthaelt ausschliesslich unlesbaren Chiffretext, IV und Salt.
    Weder PIN noch Klartextdaten oder Schluessel gelangen an das Backend.
    """

    __tablename__ = "encrypted_backups"

    user_id_hash: Mapped[str] = mapped_column(
        String(128), primary_key=True, index=True
    )
    ciphertext_base64: Mapped[str] = mapped_column(Text, nullable=False)
    iv_base64: Mapped[str] = mapped_column(String(128), nullable=False)
    salt_base64: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<EncryptedBackup user_id_hash={self.user_id_hash[:8]}... updated_at={self.updated_at}>"
