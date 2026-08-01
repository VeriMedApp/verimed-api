"""FastAPI-Einstiegspunkt fuer ProofMed."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import api_router_v1
from app.config import configure_logging, settings
from app.database import init_db
from app.seed import seed_goa_catalog

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


@app.get("/docs", include_in_schema=False)
@app.get("/redoc", include_in_schema=False)
async def redirect_to_dashboard() -> RedirectResponse:
    """Leitet veraltete Swagger-URLs zum interaktiven Dashboard um."""
    return RedirectResponse(url="/", status_code=302)


# Statisches Dashboard (Interaktiver Simulator).
# WICHTIG: Der Mount erfolgt NACH den API-Routern, damit "/" das Dashboard
# liefert, die API-Routen (/api/v1/...) und /health aber Vorrang behalten.
_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
