"""FastAPI-Einstiegspunkt fuer ProofMed."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import api_router_v1
from app.config import configure_logging, settings
from app.database import get_db, init_db
from app.models.backup import EncryptedBackup
from app.schemas.backup import (
    RestoreBackupRequest,
    RestoreBackupResponse,
    SaveBackupRequest,
    SaveBackupResponse,
)
from app.schemas.objection import SendObjectionRequest, SendObjectionResponse
from app.seed import seed_goa_catalog
from app.services.mailer import dispatch_objection_email

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialisiert DB-Schema und Seed-Daten beim Start der Anwendung."""
    logger.info("Starte %s ...", settings.PROJECT_NAME)
    await init_db()
    inserted = await seed_goa_catalog()
    logger.info("Startup abgeschlossen (%d neue Seed-Eintraege).", inserted)
    yield
    logger.info("Fahre %s herunter.", settings.PROJECT_NAME)


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    description=(
        "ProofMed - automatische GOAE-Rechnungspruefung & Geofencing-Nachweis: "
        "Backend zur Pruefung privataerztlicher GOAE-Rechnungen mittels "
        "deterministischer Regeln sowie Geofencing-/Zeit-Plausibilitaet."
    ),
    lifespan=lifespan,
    # Swagger/ReDoc nicht unter /docs – dort leitet das Dashboard um.
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router_v1, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["system"], summary="Health-Check")
async def health() -> dict[str, str]:
    """Einfacher Health-Check fuer Monitoring und Deployments."""
    return {"status": "ok", "project": settings.PROJECT_NAME}


@app.post(
    "/api/v1/backup/save",
    response_model=SaveBackupResponse,
    tags=["backup"],
    summary="Zero-Knowledge E2EE Backup auf Hetzner speichern",
)
async def save_backup(
    payload: SaveBackupRequest,
    db: AsyncSession = Depends(get_db),
) -> SaveBackupResponse:
    """Speichert oder ueberschreibt das verschluesselte E2EE-Tagebuch-Backup.
    
    Das Backend empfaengt und speichert ausschliesslich unlesbaren Chiffretext.
    Weder die PIN noch Klartext-Tagebucheintraege oder kryptographische Schluessel
    werden an das Backend uebertragen oder dort gespeichert.
    """
    stmt = select(EncryptedBackup).where(
        EncryptedBackup.user_id_hash == payload.user_id_hash
    )
    result = await db.execute(stmt)
    backup_entry = result.scalar_one_or_none()
    now_utc = datetime.now(timezone.utc)

    if backup_entry is not None:
        backup_entry.ciphertext_base64 = payload.ciphertext_base64
        backup_entry.iv_base64 = payload.iv_base64
        backup_entry.salt_base64 = payload.salt_base64
        backup_entry.updated_at = now_utc
    else:
        backup_entry = EncryptedBackup(
            user_id_hash=payload.user_id_hash,
            ciphertext_base64=payload.ciphertext_base64,
            iv_base64=payload.iv_base64,
            salt_base64=payload.salt_base64,
            updated_at=now_utc,
        )
        db.add(backup_entry)

    await db.commit()
    await db.refresh(backup_entry)

    logger.info(
        "Zero-Knowledge Backup erfolgreich gespeichert (user_id_hash: %s...).",
        payload.user_id_hash[:10],
    )

    return SaveBackupResponse(
        success=True,
        message="Backup erfolgreich auf Hetzner gespeichert!",
        timestamp=backup_entry.updated_at.isoformat(),
    )


@app.post(
    "/api/v1/backup/restore",
    response_model=RestoreBackupResponse,
    tags=["backup"],
    summary="Zero-Knowledge E2EE Backup von Hetzner abrufen",
)
async def restore_backup(
    payload: RestoreBackupRequest,
    db: AsyncSession = Depends(get_db),
) -> RestoreBackupResponse:
    """Ruft das verschluesselte E2EE-Tagebuch-Backup anhand des user_id_hash ab.
    
    Gibt HTTP 404 zurueck, falls kein Backup fuer den Hash existiert.
    """
    stmt = select(EncryptedBackup).where(
        EncryptedBackup.user_id_hash == payload.user_id_hash
    )
    result = await db.execute(stmt)
    backup_entry = result.scalar_one_or_none()

    if backup_entry is None:
        logger.warning(
            "Backup-Wiederherstellung fehlgeschlagen: Kein Eintrag fuer user_id_hash %s...",
            payload.user_id_hash[:10],
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Kein Backup für diese PIN auf Hetzner gefunden.",
        )

    logger.info(
        "Zero-Knowledge Backup erfolgreich abgerufen (user_id_hash: %s...).",
        payload.user_id_hash[:10],
    )

    return RestoreBackupResponse(
        success=True,
        ciphertext_base64=backup_entry.ciphertext_base64,
        iv_base64=backup_entry.iv_base64,
        salt_base64=backup_entry.salt_base64,
        timestamp=backup_entry.updated_at.isoformat(),
    )


@app.post(
    "/api/v1/send-objection",
    response_model=SendObjectionResponse,
    tags=["objections"],
    summary="Formellen Einwand per E-Mail versenden",
)
async def send_objection(
    payload: SendObjectionRequest,
    background_tasks: BackgroundTasks,
) -> SendObjectionResponse:
    """Sendet den Einwand per SMTP oder gibt einen erfolgreichen Mock zurueck."""
    return dispatch_objection_email(payload, background_tasks)


@app.get("/docs", include_in_schema=False)
@app.get("/redoc", include_in_schema=False)
async def redirect_to_dashboard() -> RedirectResponse:
    """Leitet veraltete Swagger-URLs zum interaktiven Dashboard um."""
    return RedirectResponse(url="/", status_code=302)


# PWA-Routen: Explizit bereitstellen für korrekte MIME-Types und Install-Prompt
_STATIC_DIR = Path(__file__).resolve().parent / "static"


@app.get("/manifest.json", include_in_schema=False)
async def serve_manifest() -> FileResponse:
    """Stellt das PWA-Manifest mit korrektem Content-Type bereit."""
    manifest_path = _STATIC_DIR / "manifest.json"
    return FileResponse(
        path=manifest_path,
        media_type="application/json",
        headers={
            "Cache-Control": "public, max-age=600",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.get("/service-worker.js", include_in_schema=False)
async def serve_service_worker() -> FileResponse:
    """Stellt den Service Worker mit korrektem Content-Type bereit."""
    sw_path = _STATIC_DIR / "service-worker.js"
    return FileResponse(
        path=sw_path,
        media_type="application/javascript",
        headers={
            "Cache-Control": "public, max-age=0",
            "Service-Worker-Allowed": "/",
            "Access-Control-Allow-Origin": "*",
        },
    )


# Statisches Dashboard (Interaktiver Simulator).
# WICHTIG: Der Mount erfolgt NACH den API-Routern, damit "/" das Dashboard
# liefert, die API-Routen (/api/v1/...) und /health aber Vorrang behalten.
app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
