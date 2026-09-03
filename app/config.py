"""Zentrale Anwendungskonfiguration fuer ProofMed.

Die Konfiguration wird ueber Umgebungsvariablen bzw. eine optionale `.env`
Datei gesteuert (Pydantic Settings v2). So lassen sich lokale SQLite-Setups
und produktive PostgreSQL-Deployments ohne Codeaenderung umschalten.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typisierte Anwendungseinstellungen."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Allgemein -----------------------------------------------------------
    PROJECT_NAME: str = "ProofMed"
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = True

    # --- Datenbank -----------------------------------------------------------
    # Standardmaessig lokale SQLite-Datei. Fuer PostgreSQL z.B.:
    #   postgresql+asyncpg://user:pass@host:5432/verimed
    DATABASE_URL: str = "sqlite+aiosqlite:///./verimed.db"

    # Synchrone URL fuer Alembic-Migrationen (ohne async-Treiber).
    # Wird automatisch aus DATABASE_URL abgeleitet, falls nicht gesetzt.
    SYNC_DATABASE_URL: str | None = None

    # --- Geschaeftslogik / Validierung --------------------------------------
    # Toleranzpuffer in Minuten fuer die Zeit-Plausibilitaetspruefung.
    TIME_TOLERANCE_MINUTES: int = 10

    # --- Sicherheit / Verschluesselung --------------------------------------
    # Schluessel fuer die PII-Verschluesselung (Encryption at Rest).
    # WICHTIG: In Produktion zwingend ueber die Umgebungsvariable ENCRYPTION_KEY
    # setzen. Der Default dient ausschliesslich der lokalen Entwicklung.
    # Aus diesem Wert wird per SHA-256 ein gueltiger 32-Byte Fernet-Key abgeleitet.
    ENCRYPTION_KEY: str = "A-32-Byte-Base64-Encoded-Key-For-Local-Dev="

    # --- CORS (Frontend / Lovable) ------------------------------------------
    # Kommagetrennte Origins, z.B. "https://meine-app.lovable.app,http://localhost:5173"
    # "*" erlaubt alle Origins (nur fuer Entwicklung empfohlen).
    ALLOWED_ORIGINS: str = "*"

    # --- Logging -------------------------------------------------------------
    LOG_LEVEL: str = "INFO"

    # --- SMTP / Einwand-Versand ---------------------------------------------
    # Ohne SMTP_HOST und SMTP_FROM antwortet /api/v1/send-objection mit einem
    # erfolgreichen Mock (kein echter Versand).
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_STARTTLS: bool = True

    @property
    def async_database_url(self) -> str:
        """Normalisiert DATABASE_URL fuer SQLAlchemy async (Render liefert postgresql://)."""
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        if url.startswith("postgresql://") and "+asyncpg" not in url:
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    @property
    def cors_origins(self) -> list[str]:
        """Parst ALLOWED_ORIGINS in eine Liste fuer CORSMiddleware."""
        raw = (self.ALLOWED_ORIGINS or "*").strip()
        if raw == "*":
            return ["*"]
        return [origin.strip() for origin in raw.split(",") if origin.strip()]

    @property
    def effective_sync_database_url(self) -> str:
        """Liefert eine synchrone DB-URL fuer Tools wie Alembic."""
        url = self.SYNC_DATABASE_URL or self.DATABASE_URL

        # Legacy-Render/Postgres-URLs fuer SQLAlchemy 2.x normalisieren.
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+psycopg2://", 1)

        # Async-Treiber-Hinweise entfernen, um eine synchrone URL zu erhalten.
        return (
            url.replace("+aiosqlite", "")
            .replace("+asyncpg", "+psycopg2")
        )

    @property
    def smtp_configured(self) -> bool:
        """True, wenn ein echter SMTP-Versand moeglich ist."""
        return bool((self.SMTP_HOST or "").strip() and (self.SMTP_FROM or "").strip())


@lru_cache
def get_settings() -> Settings:
    """Gecachte Settings-Instanz (Singleton)."""
    return Settings()


def configure_logging(level: str | None = None) -> None:
    """Initialisiert strukturiertes Logging fuer die gesamte Anwendung."""
    log_level = (level or get_settings().LOG_LEVEL).upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format=(
            "%(asctime)s | %(levelname)-8s | %(name)s | "
            "%(funcName)s:%(lineno)d | %(message)s"
        ),
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )


settings = get_settings()
