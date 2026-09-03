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

**Alembic ist die einzige Schema-Autoritaet** (seit WP-INFRA-1). Die Anwendung
erzeugt beim Start **kein** Schema mehr (kein `create_all()`, keine ad-hoc
`ALTER TABLE`). Stattdessen prueft `init_db()` beim Start fail-closed, dass die
Datenbank exakt auf dem erwarteten Alembic-Head steht und alle 21 verwalteten
Tabellen existieren; andernfalls startet die Anwendung **nicht**
(`app/schema_guard.py`, Fehlerklassen `SchemaGuardError`). Der Seed des
GOAE-Katalogs laeuft unveraendert nach erfolgreicher Pruefung.

Revisionsgraph:

```
None -> 0000_legacy_baseline -> 0001_reference_core
```

* `0000_legacy_baseline`: die vier Legacy-Tabellen (`goa_ziffern`,
  `encrypted_backups`, `medical_claims`, `claim_line_items`) inkl. PostgreSQL-Enum
  `claim_status` und der acht frueher per ALTER ergaenzten `goa_ziffern`-Spalten.
* `0001_reference_core`: die 17 Reference-Core-Tabellen (WP-01).

```bash
# Neue (leere) Datenbank vollstaendig anlegen:
alembic upgrade head

# Bestehende Datenbank, die noch per create_all() entstanden ist (kein alembic_version):
python -m app.schema_guard stamp-legacy   # fail-closed Struktur-Preflight, dann Stamp
alembic upgrade head

# Nur pruefen (rein lesend, identisch zur Startpruefung):
python -m app.schema_guard check

# Reference-Core-Tabellen wieder entfernen (verweigert bei finalisierten Manifesten):
alembic downgrade 0000_legacy_baseline

# SQL vorab pruefen, ohne eine Datenbank anzufassen:
alembic upgrade head --sql
```

`stamp-legacy` schreibt `alembic_version` nur, wenn Tabellen, Spalten, Typen,
Nullability, Primaerschluessel, Fremdschluessel (inkl. ON DELETE), Indizes und
auf PostgreSQL die Enum-Labels von `claim_status` exakt der Baseline entsprechen,
keine Reference-Core-Tabelle existiert und `alembic_version` leer/abwesend ist.
Historische Server-Defaults auf den acht `goa_ziffern`-Zusatzspalten werden
toleriert. `alembic downgrade base` verweigert, solange Legacy-Tabellen Daten
enthalten (`PROOFMED_ALLOW_LEGACY_DROP=YES` nur fuer Wegwerf-Datenbanken).

> Migrationen werden **ausserhalb** der Anwendung ausgefuehrt (lokal von Hand,
> im Deployment vor dem Start der neuen Instanz). Die Anwendung migriert nie
> selbst.

> **Nicht** `alembic revision --autogenerate` verwenden: Revisionen werden von
> Hand geschrieben und ueber die Tests gegen die Modelle abgeglichen.

> Hinweis: Alembic nutzt automatisch eine synchrone DB-URL, die aus
> `DATABASE_URL` abgeleitet wird (siehe `app/config.py`). Auch reine
> Lese-Kommandos (`alembic current`, `alembic check`) legen auf der Ziel-DB die
> Tabelle `alembic_version` an - niemals gegen Produktion ausfuehren.

### Schema-Tests (WP-01)

```bash
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest
```

Die Tests laufen gegen eine isolierte temporaere SQLite-Datei. Fuer den
PostgreSQL-Lauf (vor einem Merge erforderlich) `PROOFMED_TEST_PG_URL` auf eine
Wegwerf-Datenbank setzen, z.B.:

```bash
docker run -d --name proofmed-wp01-pg -e POSTGRES_USER=wp01 -e POSTGRES_PASSWORD=wp01 -e POSTGRES_DB=proofmed_wp01 -p 55432:5432 postgres:16-alpine
PROOFMED_TEST_PG_URL=postgresql://wp01:wp01@localhost:55432/proofmed_wp01 PROOFMED_ALLOW_TEST_DB_RESET=YES .venv\Scripts\python.exe -m pytest
```

## Seed-Ziffern

| Ziffer | Leistung | Regelzeit | Ausschluss |
|--------|----------|-----------|------------|
| 1 | Beratung | 10 Min | – |
| 3 | Eingehende Beratung (>10 Min) | 20 Min | 1 |
| 5 | Symptombezogene Untersuchung | 15 Min | – |
| 8 | Ganzkörperstatus | 30 Min | 5 |
| 250 | Blutentnahme | 5 Min | – |
