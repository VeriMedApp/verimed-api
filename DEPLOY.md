# VeriMed auf Render deployen

Schritt-für-Schritt-Anleitung für das FastAPI-Backend auf [Render](https://render.com).

---

## Voraussetzungen

- [ ] Render-Konto (bereits vorhanden)
- [ ] GitHub-Repo mit diesem Code
- [ ] Optional: `ENCRYPTION_KEY` lokal generiert und sicher notiert

---

## Option A: Blueprint (empfohlen, 1 Klick)

Erstellt automatisch **Web Service + PostgreSQL** aus `render.yaml`.

### 1. Code auf GitHub pushen

```powershell
cd "C:\Project VeriMed"
git init
git add .
git commit -m "Add Render deployment config"
git remote add origin https://github.com/DEIN-USER/verimed-api.git
git branch -M main
git push -u origin main
```

### 2. Blueprint auf Render anlegen

1. [dashboard.render.com](https://dashboard.render.com) → **New +** → **Blueprint**
2. GitHub-Repo `verimed-api` verbinden/auswählen
3. Render erkennt `render.yaml` → **Apply**
4. Warten bis Deploy grün ist (ca. 3–5 Min.)

### 3. URL notieren

Nach erfolgreichem Deploy:

```
https://verimed-api.onrender.com
```

(Der exakte Name hängt von deinem Service-Namen ab.)

---

## Option B: Manuell (ohne Blueprint)

### 1. PostgreSQL anlegen

1. **New +** → **PostgreSQL**
2. Name: `verimed-db`, Plan: **Free**
3. Nach Erstellung: **Internal Database URL** kopieren

### 2. Web Service anlegen

1. **New +** → **Web Service**
2. Repo verbinden
3. Einstellungen:

| Feld | Wert |
|------|------|
| **Name** | `verimed-api` |
| **Runtime** | Python 3 |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| **Health Check Path** | `/health` |

### 3. Umgebungsvariablen setzen

Im Web Service unter **Environment**:

| Variable | Wert |
|----------|------|
| `DATABASE_URL` | Internal URL von PostgreSQL (Render setzt `postgresql://...` – wird automatisch zu `+asyncpg` konvertiert) |
| `DEBUG` | `false` |
| `LOG_LEVEL` | `INFO` |
| `TIME_TOLERANCE_MINUTES` | `10` |
| `ENCRYPTION_KEY` | Sicherer Schlüssel (siehe unten) |
| `ALLOWED_ORIGINS` | `*` (später auf Lovable-URL einschränken) |

**ENCRYPTION_KEY generieren** (PowerShell, einmalig):

```powershell
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> **Wichtig:** Notiere den Key sicher. Bei Verlust sind verschlüsselte PII-Daten nicht mehr lesbar.

### 4. Deploy starten

**Manual Deploy** → **Deploy latest commit**

---

## Nach dem Deploy testen

Ersetze `DEINE-URL` durch deine Render-Domain:

```text
GET  https://DEINE-URL.onrender.com/health
GET  https://DEINE-URL.onrender.com/api/v1/claims/catalog
GET  https://DEINE-URL.onrender.com/
POST https://DEINE-URL.onrender.com/api/v1/claims/validate
```

Swagger (API-Doku): `https://DEINE-URL.onrender.com/api/docs`

**Erwartung bei `/health`:**

```json
{"status":"ok","project":"Project VeriMed"}
```

**Erwartung bei `/api/v1/claims/catalog`:** 5 GOÄ-Ziffern

---

## Für Lovable (Frontend)

In Lovable als Umgebungsvariable:

```env
VITE_API_URL=https://DEINE-URL.onrender.com
```

Wenn das Lovable-Frontend live ist, CORS auf Render einschränken:

```env
ALLOWED_ORIGINS=https://deine-app.lovable.app,http://localhost:5173
```

---

## Hinweise zum Free Tier

| Thema | Verhalten |
|-------|-----------|
| **Cold Start** | Web Service schläft nach ~15 Min. Inaktivität → erster Request dauert 30–60 Sek. |
| **PostgreSQL Free** | Läuft 90 Tage, dann Verlängerung oder Upgrade nötig |
| **SQLite** | Nicht auf Render nutzen – Daten gehen bei Neustart verloren |

---

## Troubleshooting

| Problem | Lösung |
|---------|--------|
| Build schlägt fehl | Logs prüfen; Python 3.12 via `runtime.txt` |
| `connection refused` DB | `DATABASE_URL` = **Internal** URL, nicht External |
| 502 Bad Gateway | Start Command prüfen: `--host 0.0.0.0 --port $PORT` |
| Leerer Katalog | Logs: „Seed abgeschlossen“ suchen; DB-Verbindung prüfen |
| CORS-Fehler im Frontend | `ALLOWED_ORIGINS` um Lovable-URL ergänzen |

---

## Checkliste (dein To-do)

```
□ Code auf GitHub gepusht
□ Render Blueprint angewendet (oder manuell Web + DB)
□ ENCRYPTION_KEY gesetzt (bei Blueprint: auto-generiert)
□ Deploy erfolgreich (grüner Status)
□ /health → ok
□ /api/v1/claims/catalog → 5 Einträge
□ URL an Lovable als VITE_API_URL übergeben
```
