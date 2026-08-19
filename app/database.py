"""Datenbank-Setup mit asynchronem SQLAlchemy 2.0.

Stellt die async Engine, eine Session-Factory sowie die deklarative Basis
bereit. Eine FastAPI-Dependency `get_db` liefert sauber gescopte Sessions.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Gemeinsame deklarative Basisklasse fuer alle ORM-Modelle."""


_db_url = settings.async_database_url

# SQLite benoetigt fuer Multithreading-Zugriffe ein angepasstes connect_args.
_connect_args: dict[str, object] = {}
if _db_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine: AsyncEngine = create_async_engine(
    _db_url,
    echo=settings.DEBUG,
    future=True,
    connect_args=_connect_args,
)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI-Dependency: liefert eine Session und schliesst sie sauber."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            logger.exception("DB-Session wurde nach einem Fehler zurueckgerollt.")
            raise
        finally:
            await session.close()


_GOA_EXTRA_COLUMNS: tuple[tuple[str, str], ...] = (
    ("category", "VARCHAR(32) NOT NULL DEFAULT 'personal'"),
    ("threshold_multiplier", "FLOAT NOT NULL DEFAULT 2.3"),
    ("max_multiplier", "FLOAT NOT NULL DEFAULT 3.5"),
    ("fee_simple", "FLOAT NOT NULL DEFAULT 0"),
    ("fee_threshold", "FLOAT NOT NULL DEFAULT 0"),
    ("fee_max", "FLOAT NOT NULL DEFAULT 0"),
    ("max_per_session", "INTEGER"),
    ("sort_order", "INTEGER NOT NULL DEFAULT 0"),
)


def _ensure_goa_catalog_columns(sync_conn) -> None:
    """Ergaenzt fehlende GOAE-Spalten in bestehenden SQLite-DBs ohne Alembic."""
    inspector = inspect(sync_conn)
    if "goa_ziffern" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("goa_ziffern")}
    added = 0
    for name, ddl in _GOA_EXTRA_COLUMNS:
        if name in existing:
            continue
        sync_conn.execute(text(f"ALTER TABLE goa_ziffern ADD COLUMN {name} {ddl}"))
        added += 1
    if added:
        logger.info("GOAE-Katalogschema erweitert: %d neue Spalte(n).", added)


async def init_db() -> None:
    """Erstellt alle Tabellen (fuer lokale Entwicklung ohne Migrationen)."""
    # Import sorgt dafuer, dass alle Modelle bei der Metadata registriert sind.
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_goa_catalog_columns)
    logger.info("Datenbankschema initialisiert (create_all).")
