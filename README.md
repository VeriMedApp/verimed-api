# Project VeriMed

Backend zur Pruefung privataerztlicher Rechnungen nach der **GOÄ**
(Gebührenordnung für Ärzte) in Deutschland. VeriMed kombiniert
deterministische medizinische Regeln mit Geofencing-/Zeit-Plausibilitätsprüfungen,
um Abrechnungsfehler und Betrug zu erkennen.

## Tech-Stack

- **Framework:** FastAPI (Python 3.11+)
- **ORM:** SQLAlchemy 2.0 (async)
- **Datenbank:** SQLite (lokal) / PostgreSQL (Produktion, via `asyncpg`)
- **Migrationen:** Alembic
- **Validierung:** Pydantic v2

## Projektstruktur

```
app/
├── main.py              # FastAPI-App + Lifespan (DB-Init & Seed)
├── config.py            # Pydantic-Settings (Umgebungsvariablen)
├── database.py          # Async Engine, Session-Factory, Base
├── models/              # SQLAlchemy-Modelle (GOÄ-Katalog, Claims)
├── schemas/             # Pydantic v2 Request/Response-Schemas
├── services/            # Geschäftslogik (ClaimValidator)
├── api/v1/              # Versionierte API-Endpunkte
└── seed.py              # Idempotentes Seeding des GOÄ-Katalogs
alembic/                 # Migrationskonfiguration
```

## Schnellstart

### 1. Virtuelle Umgebung & Abhängigkeiten

```bash
python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Konfiguration (optional)

```bash
cp .env.example .env
```

Ohne `.env` wird automatisch die lokale SQLite-Datei `verimed.db` verwendet.

### 3. Anwendung starten

```bash
uvicorn app.main:app --reload
```

Beim Start werden das Datenbankschema angelegt und der GOÄ-Katalog
automatisch mit Standard-Ziffern befüllt.

- Swagger UI: http://127.0.0.1:8000/docs
- Health-Check: http://127.0.0.1:8000/health

### 4. Seed manuell ausführen (optional)

```bash
python -m app.seed
```

## API

### `POST /api/v1/claims/validate`

Validiert eine Rechnung anhand der Geofence-Zeiten und der abgerechneten Ziffern.

**Beispiel-Request:**

```json
{
  "patient_id": "patient-001",
  "praxis_name": "Praxis Dr. Mustermann",
  "geofence_arrival": "2026-06-14T09:00:00+02:00",
  "geofence_departure": "2026-06-14T09:12:00+02:00",
  "total_billed_amount": 84.5,
  "billed_ziffern": [
    { "ziffer": "1", "multiplier": 2.3 },
    { "ziffer": "3", "multiplier": 2.3 },
    { "ziffer": "5", "multiplier": 1.8 }
  ]
}
```

Die Engine führt zwei Prüfungen durch:

1. **Zeit-Plausibilität** – Summe der Regelzeiten vs. tatsächliche
   Aufenthaltsdauer (zzgl. Toleranzpuffer, Standard 10 Min.).
2. **Ausschlussprüfung** – erkennt gegenseitig nicht abrechenbare Ziffern.

Der Bericht enthält den Gültigkeitsstatus, alle erkannten Anomalien und
patientenfreundliche Übersetzungen je Ziffer.

### `GET /api/v1/claims/catalog`

Gibt den hinterlegten GOÄ-Katalog zurück.

## Migrationen (Alembic)

```bash
# Erste Migration aus den Modellen generieren:
alembic revision --autogenerate -m "initial schema"

# Migrationen anwenden:
alembic upgrade head
```

> Hinweis: Alembic nutzt automatisch eine synchrone DB-URL, die aus
> `DATABASE_URL` abgeleitet wird (siehe `app/config.py`).

## Seed-Ziffern

| Ziffer | Leistung | Regelzeit | Ausschluss |
|--------|----------|-----------|------------|
| 1 | Beratung | 10 Min | – |
| 3 | Eingehende Beratung (>10 Min) | 20 Min | 1 |
| 5 | Symptombezogene Untersuchung | 15 Min | – |
| 8 | Ganzkörperstatus | 30 Min | 5 |
| 250 | Blutentnahme | 5 Min | – |
