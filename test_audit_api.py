"""Test-Script für die neuen Audit-API-Endpunkte."""

import json
from datetime import datetime

# Beispiel-Request für Claim Audit
claim_audit_request = {
    "invoice_number": "R-2026-001",
    "practice_name": "Dr. Müller Allgemeinmedizin",
    "treatment_date": "2026-08-21",
    "claimed_items": [
        {
            "code": "1",
            "factor": 2.8,
            "amount_eur": 13.04,
            "description": "Beratungsgespräch",
        },
        {
            "code": "3",
            "factor": 2.3,
            "amount_eur": 20.11,
            "description": "Eingehende Beratung",
        },
        {
            "code": "250",
            "factor": 1.8,
            "amount_eur": 4.20,
            "description": "Blutentnahme",
        },
        {
            "code": "A",
            "factor": 1.5,  # FEHLER: Zuschlag darf nicht multipliziert werden
            "amount_eur": 6.12,
            "description": "Zuschlag außerhalb Sprechstunde",
        },
    ],
    "presence_duration_minutes": 25,
    "has_written_justification": False,
}

# Beispiel-Request für Geofence Verify
geofence_request = {
    "latitude": 52.520008,
    "longitude": 13.404954,
    "accuracy_meters": 15.5,
    "arrival_time": "2026-08-21T09:00:00",
    "departure_time": "2026-08-21T09:25:00",
    "practice_name": "Dr. Müller Allgemeinmedizin",
}

print("=" * 80)
print("CLAIM AUDIT REQUEST")
print("=" * 80)
print(json.dumps(claim_audit_request, indent=2, ensure_ascii=False))

print("\n" + "=" * 80)
print("GEOFENCE VERIFY REQUEST")
print("=" * 80)
print(json.dumps(geofence_request, indent=2, ensure_ascii=False))

print("\n" + "=" * 80)
print("EXPECTED ISSUES:")
print("=" * 80)
print("1. ⚠️ WARN: GOÄ 1 - Begründungspflicht (Faktor 2.8x > 2.3x)")
print("2. 🚨 ERROR: GOÄ 1 + GOÄ 3 - Ausschlusskonflikt ohne getrennte Zeiten")
print("3. ❌ ERROR: GOÄ A - Zuschlag darf nicht multipliziert werden (Faktor muss 1.0)")
print("4. Status: REJECTED (wegen ERROR-Issues)")
print("\n")
