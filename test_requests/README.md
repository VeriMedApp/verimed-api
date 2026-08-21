# ProofMed API Test-Requests

Dieses Verzeichnis enthält JSON-Dateien für manuelle API-Tests.

## Verfügbare Test-Dateien

### 1. `claim_audit_with_errors.json`
Enthält eine Rechnung mit mehreren GOÄ-Verstößen:

**Erwartete Issues:**
- ⚠️ **WARN**: GOÄ 1 - Begründungspflicht (Faktor 2.8x > 2.3x)
- 🚨 **ERROR**: GOÄ 1 + GOÄ 3 - Ausschlusskonflikt
- 🚨 **ERROR**: GOÄ 5 + GOÄ 8 - Ausschlusskonflikt
- ⚠️ **WARN**: GOÄ 250 - Begründungspflicht (Faktor 2.0x > 1.8x für technische Leistung)
- 🚨 **ERROR**: GOÄ A - Zuschlag darf nicht multipliziert werden
- 🚨 **ERROR**: Zeit-Konflikt (benötigt: 30 Min, anwesend: 15 Min)

**Erwartetes Ergebnis:**
- `audit_status`: "REJECTED"
- `savings_potential_eur`: > 0 EUR

### 2. `claim_audit_clean.json`
Saubere Rechnung ohne Verstöße:

**Erwartetes Ergebnis:**
- `audit_status`: "OK"
- `issues`: []
- `savings_potential_eur`: 0.00 EUR

### 3. `geofence_verify.json`
Geofence-Verifizierung mit GPS-Daten:

**Erwartetes Ergebnis:**
- `proof_valid`: true
- `duration_minutes`: 45
- `audit_hash`: SHA-256 Hash

## Test-Befehle

### Claims Audit (mit Fehlern)
```bash
curl -X POST http://localhost:8000/api/v1/claims/audit \
  -H "Content-Type: application/json" \
  -d @test_requests/claim_audit_with_errors.json
```

### Claims Audit (clean)
```bash
curl -X POST http://localhost:8000/api/v1/claims/audit \
  -H "Content-Type: application/json" \
  -d @test_requests/claim_audit_clean.json
```

### Geofence Verify
```bash
curl -X POST http://localhost:8000/api/v1/geofence/verify-proof \
  -H "Content-Type: application/json" \
  -d @test_requests/geofence_verify.json
```

### GOÄ-Katalog abrufen
```bash
curl -X GET http://localhost:8000/api/v1/goa-catalog
```

### FHIR Export
```bash
curl -X POST http://localhost:8000/api/v1/claims/fhir-export \
  -H "Content-Type: application/json" \
  -d @test_requests/claim_audit_clean.json
```

### BiPRO Export
```bash
curl -X POST http://localhost:8000/api/v1/claims/bipro-export \
  -H "Content-Type: application/json" \
  -d @test_requests/claim_audit_clean.json
```

## PowerShell-Befehle (Windows)

### Claims Audit
```powershell
$body = Get-Content "test_requests\claim_audit_with_errors.json" -Raw
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/claims/audit" `
  -Method POST `
  -Body $body `
  -ContentType "application/json"
```

### Geofence Verify
```powershell
$body = Get-Content "test_requests\geofence_verify.json" -Raw
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/geofence/verify-proof" `
  -Method POST `
  -Body $body `
  -ContentType "application/json"
```

## Erwartete Antworten

### claim_audit_with_errors.json Response (gekürzt)
```json
{
  "audit_status": "REJECTED",
  "issues": [
    {
      "code": "1",
      "severity": "WARN",
      "message": "⚠️ Begründungspflicht: Steigerungsfaktor 2.8x > 2.3x"
    },
    {
      "code": "1, 3",
      "severity": "ERROR",
      "message": "🚨 Kombinationsverbot: GOÄ 1 und GOÄ 3..."
    }
  ],
  "total_claimed_eur": 91.91,
  "valid_amount_eur": 85.79,
  "savings_potential_eur": 6.12,
  "proof_hash": "..."
}
```

### claim_audit_clean.json Response
```json
{
  "audit_status": "OK",
  "issues": [],
  "total_claimed_eur": 97.70,
  "valid_amount_eur": 97.70,
  "savings_potential_eur": 0.00,
  "proof_hash": "..."
}
```

### geofence_verify.json Response
```json
{
  "proof_valid": true,
  "duration_minutes": 45,
  "audit_hash": "b8f3a5c9d2e7f1a4b6c8d3e9f2a5b7c4d1e8f6a3b9c2d5e1f7a4b3c6d9e2f8",
  "verified_at": "2026-08-21T14:30:00.123456"
}
```

## Server starten

```bash
cd "c:\Project VeriMed"
python -m uvicorn app.main:app --reload --port 8000
```

Swagger UI: http://localhost:8000/api/docs
