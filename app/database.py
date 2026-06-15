"""Datenbank-Setup mit asynchronem SQLAlchemy 2.0.

Stellt die async Engine, eine Session-Factory sowie die deklarative Basis
bereit. Eine FastAPI-Dependency `get_db` liefert sauber gescopte Sessions.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

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


async def init_db() -> None:
    """Erstellt alle Tabellen (fuer lokale Entwicklung ohne Migrationen)."""
    # Import sorgt dafuer, dass alle Modelle bei der Metadata registriert sind.
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Datenbankschema initialisiert (create_all).")
