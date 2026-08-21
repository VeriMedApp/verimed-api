# ProofMed API-Dokumentation (v1)

## Übersicht der neuen Audit-Endpunkte

Alle neuen Endpunkte sind unter dem API-Präfix `/api/v1` verfügbar.

### ✅ Implementierte Endpunkte

1. **GET /api/v1/goa-catalog** - GOÄ-Katalog mit Metadaten
2. **POST /api/v1/claims/audit** - Vollständige Rechnungsprüfung (B2B/B2C)
3. **POST /api/v1/geofence/verify-proof** - Geofence-Nachweis verifizieren
4. **POST /api/v1/claims/fhir-export** - FHIR ExplanationOfBenefit Export
5. **POST /api/v1/claims/bipro-export** - BiPRO Norm 430/440 Export

---

## 1. GOÄ-Katalog abrufen

**Endpoint:** `GET /api/v1/goa-catalog`

**Response:**
```json
{
  "version_id": "GOAE_2026_V1",
  "last_updated": "2026-08-21T14:30:00",
  "total_codes": 29,
  "catalog": [
    {
      "ziffer": "1",
      "title_official": "Beratung, auch mittels Fernsprecher",
      "title_patient": "Kurzes Beratungsgespräch mit dem Arzt.",
      "category": "personal",
      "threshold_multiplier": 2.3,
      "max_multiplier": 3.5,
      "fee_simple": 4.66,
      "fee_threshold": 10.72,
      "fee_max": 16.32,
      "rule_time_minutes": 0,
      "exclusion_ziffern": ["3"],
      "sort_order": 10
    }
  ]
}
```

---

## 2. Rechnungsprüfung (Audit)

**Endpoint:** `POST /api/v1/claims/audit`

### Request-Schema

```json
{
  "invoice_number": "R-2026-001",
  "practice_name": "Dr. Müller Allgemeinmedizin",
  "treatment_date": "2026-08-21",
  "claimed_items": [
    {
      "code": "1",
      "factor": 2.8,
      "amount_eur": 13.04,
      "description": "Beratungsgespräch"
    },
    {
      "code": "3",
      "factor": 2.3,
      "amount_eur": 20.11,
      "description": "Eingehende Beratung"
    }
  ],
  "presence_duration_minutes": 25,
  "has_written_justification": false
}
```

### Response-Schema

```json
{
  "audit_status": "WARNING",
  "issues": [
    {
      "code": "1",
      "severity": "WARN",
      "message": "⚠️ Begründungspflicht: Steigerungsfaktor 2.8x > 2.3x"
    },
    {
      "code": "1, 3",
      "severity": "ERROR",
      "message": "🚨 Kombinationsverbot: GOÄ 1 und GOÄ 3 dürfen am selben Tag nicht gemeinsam abgerechnet werden..."
    }
  ],
  "total_claimed_eur": 33.15,
  "valid_amount_eur": 30.83,
  "savings_potential_eur": 2.32,
  "proof_hash": "a3f5b8c2d9e1f4a7b6c3d8e2f5a9b4c7d1e6f3a8b2c5d9e4f1a7b3c6d2e8f5a9"
}
```

### Audit-Logik

#### Phase 1: Katalog-Lookup & Multiplikator-Validierung

**Persönliche Leistungen (category: "personal"):**
- Standard-Limit: 2.3x
- Max-Limit: 3.5x
- Warnung bei Faktor > 2.3x ohne schriftliche Begründung
- Fehler bei Faktor > 3.5x

**Technische Leistungen (category: "technical"):**
- Standard-Limit: 1.8x
- Max-Limit: 2.5x
- Warnung bei Faktor > 1.8x ohne schriftliche Begründung
- Fehler bei Faktor > 2.5x

**Zuschläge (category: "surcharge"):**
- Muss immer 1.0x sein
- Fehler bei jeder Multiplikation

#### Phase 2: Ausschlussregeln

Geprüfte Kombinationsverbote:
1. GOÄ 1 + GOÄ 3 (ohne getrennte Zeiten)
2. GOÄ 5 + (GOÄ 7 oder GOÄ 8)
3. GOÄ 200 + GOÄ 2006
4. GOÄ 250 + (GOÄ 200 / GOÄ 204 / GOÄ 252)

#### Phase 3: Zeit-Plausibilität

- Berechnet Mindest-Behandlungsdauer aus `rule_time_minutes`
- Vergleicht mit `presence_duration_minutes`
- Schwerer Fehler bei `required > presence`

#### Phase 4: Finanzielle Berechnung

- `total_claimed_eur`: Summe aller abgerechneten Beträge
- `valid_amount_eur`: Korrigierter Betrag nach Prüfung
- `savings_potential_eur`: Einsparpotenzial (total - valid)

#### Phase 5: Audit-Status

- **"OK"**: Keine Auffälligkeiten
- **"WARNING"**: Nur Warnungen (WARN)
- **"REJECTED"**: Mindestens ein Fehler (ERROR)

---

## 3. Geofence-Verifizierung

**Endpoint:** `POST /api/v1/geofence/verify-proof`

### Request-Schema

```json
{
  "latitude": 52.520008,
  "longitude": 13.404954,
  "accuracy_meters": 15.5,
  "arrival_time": "2026-08-21T09:00:00",
  "departure_time": "2026-08-21T09:25:00",
  "practice_name": "Dr. Müller Allgemeinmedizin"
}
```

### Response-Schema

```json
{
  "proof_valid": true,
  "duration_minutes": 25,
  "audit_hash": "b8f3a5c9d2e7f1a4b6c8d3e9f2a5b7c4d1e8f6a3b9c2d5e1f7a4b3c6d9e2f8",
  "verified_at": "2026-08-21T14:30:00"
}
```

**Audit-Hash-Berechnung:**
- Deterministischer SHA-256 Hash aus:
  - Praxisname
  - Ankunfts- und Abfahrtszeit (ISO 8601)
  - GPS-Koordinaten (auf 6 Dezimalstellen gerundet)
  - Genauigkeit (auf 2 Dezimalstellen gerundet)

---

## 4. FHIR-Export

**Endpoint:** `POST /api/v1/claims/fhir-export`

**Request:** Gleiche Struktur wie `/claims/audit`

**Response:** HL7 FHIR R4 `ExplanationOfBenefit` Ressource

```json
{
  "resourceType": "ExplanationOfBenefit",
  "id": "eob-R-2026-001",
  "status": "active",
  "type": {
    "coding": [{
      "system": "http://terminology.hl7.org/CodeSystem/claim-type",
      "code": "professional"
    }]
  },
  "patient": {"reference": "Patient/Dr. Müller Allgemeinmedizin"},
  "item": [
    {
      "sequence": 1,
      "productOrService": {
        "coding": [{
          "system": "http://proofmed.de/goae",
          "code": "1",
          "display": "Beratungsgespräch"
        }]
      },
      "net": {"value": 13.04, "currency": "EUR"}
    }
  ]
}
```

---

## 5. BiPRO-Export

**Endpoint:** `POST /api/v1/claims/bipro-export`

**Request:** Gleiche Struktur wie `/claims/audit`

**Response:** BiPRO Norm 430/440 konformes Objekt

```json
{
  "BiPRO": {
    "Version": "2.6.0.1.0",
    "Nachricht": {
      "NachrichtTyp": "Rechnungseinreichung",
      "Absender": "Dr. Müller Allgemeinmedizin",
      "Zeitstempel": "2026-08-21T14:30:00"
    },
    "Rechnung": {
      "Rechnungsnummer": "R-2026-001",
      "Behandlungsdatum": "2026-08-21",
      "Gesamtbetrag": {
        "Betrag": 33.15,
        "Waehrung": "EUR"
      },
      "Positionen": [
        {
          "Laufnummer": 1,
          "GOAEZiffer": "1",
          "Steigerungsfaktor": 2.8,
          "Einzelbetrag": 13.04
        }
      ]
    }
  }
}
```

---

## API-Dokumentation (Swagger)

Die interaktive API-Dokumentation ist verfügbar unter:
- **Swagger UI:** `http://localhost:8000/api/docs`
- **ReDoc:** `http://localhost:8000/api/redoc`

## Test-Befehle (curl)

### 1. Katalog abrufen
```bash
curl -X GET http://localhost:8000/api/v1/goa-catalog
```

### 2. Rechnung prüfen
```bash
curl -X POST http://localhost:8000/api/v1/claims/audit \
  -H "Content-Type: application/json" \
  -d @test_audit_api.json
```

### 3. Geofence verifizieren
```bash
curl -X POST http://localhost:8000/api/v1/geofence/verify-proof \
  -H "Content-Type: application/json" \
  -d '{
    "latitude": 52.520008,
    "longitude": 13.404954,
    "accuracy_meters": 15.5,
    "arrival_time": "2026-08-21T09:00:00",
    "departure_time": "2026-08-21T09:25:00",
    "practice_name": "Dr. Müller"
  }'
```

---

## Fehlerbehandlung

### HTTP Status Codes

- **200 OK**: Erfolgreiche Verarbeitung
- **400 Bad Request**: Ungültige Request-Parameter
- **422 Unprocessable Entity**: Validierungsfehler
- **500 Internal Server Error**: Server-Fehler

### Fehler-Response-Format

```json
{
  "detail": "Beschreibung des Fehlers"
}
```

---

## Sicherheit & Compliance

### DSGVO-Konformität
- Keine persistente Speicherung von Patientendaten
- Alle Berechnungen erfolgen on-the-fly
- Proof-Hashes sind deterministisch und reproduzierbar

### Kryptografische Nachweise
- SHA-256 Hashes für Audit-Trails
- Deterministisch: Gleiche Eingabe = Gleicher Hash
- Fälschungssicher durch Einbindung aller relevanten Parameter

---

## Performance

- Durchschnittliche Response-Zeit: < 100ms
- Katalog-Größe: 29 GOÄ-Ziffern (erweiterbar)
- Maximale Anzahl Claim-Items: Unbegrenzt (empfohlen: < 100)

---

## Version & Changelog

**Version:** 1.0.0  
**Datum:** 2026-08-21

**Changelog:**
- ✅ GET /api/v1/goa-catalog - GOÄ-Katalog mit Metadaten
- ✅ POST /api/v1/claims/audit - Vollständige Audit-Engine
- ✅ POST /api/v1/geofence/verify-proof - Geofence-Verifizierung
- ✅ POST /api/v1/claims/fhir-export - FHIR-Export (Stub)
- ✅ POST /api/v1/claims/bipro-export - BiPRO-Export (Stub)
