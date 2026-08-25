"""Pydantic-Schemas fuer Zero-Knowledge E2EE Cloud-Backup."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SaveBackupRequest(BaseModel):
    """Payload zum Speichern eines verschluesselten Backups.
    
    Das Backend erhaelt ausschliesslich unlesbaren Chiffretext. Weder die PIN
    noch Klartext-Tagebucheintraege oder Schluessel werden uebertragen.
    """

    user_id_hash: str = Field(
        ...,
        description="SHA-256 Hash aus PIN und Salt zur eindeutigen Zuordnung ohne PIN-Klartext.",
        min_length=16,
        max_length=128,
    )
    ciphertext_base64: str = Field(
        ...,
        description="Mit AES-GCM-256 verschluesselter JSON-String des Tagebuchs (Base64).",
    )
    iv_base64: str = Field(
        ...,
        description="Zufaelliger 12-Byte Initialisierungsvektor fuer AES-GCM (Base64).",
    )
    salt_base64: str = Field(
        ...,
        description="Zufaelliger 16-Byte Salt fuer PBKDF2-Schluesselableitung (Base64).",
    )


class SaveBackupResponse(BaseModel):
    """Antwort nach erfolgreichem Speichern."""

    success: bool = True
    message: str = "Backup erfolgreich auf Hetzner gespeichert!"
    timestamp: str


class RestoreBackupRequest(BaseModel):
    """Anfrage zum Wiederherstellen eines verschluesselten Backups."""

    user_id_hash: str = Field(
        ...,
        description="SHA-256 Hash aus PIN und Salt zur Abfrage des verschluesselten Backups.",
    )


class RestoreBackupResponse(BaseModel):
    """Antwort mit verschluesseltem Backup-Payload."""

    success: bool = True
    ciphertext_base64: str
    iv_base64: str
    salt_base64: str
    timestamp: str
