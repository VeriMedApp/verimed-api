"""Kanonischer GOAE-Katalog fuer ProofMed (Allgemeinmedizin bis Paediatrie).

Enthaelt die gaengigsten Ziffern inkl. Unzeit-/Notfall-Zuschlaege sowie die
kategoriespezifischen Schwellen- und Hoechstsätze. Validator, Seed, OCR und
das Frontend nutzen diese Daten als gemeinsame Quelle.
"""

from __future__ import annotations

from typing import Any

CATEGORY_PERSONAL = "personal"
CATEGORY_TECHNICAL = "technical"
CATEGORY_SURCHARGE = "surcharge"

# Persönliche Leistungen: Schwellenwert 2,3x, Höchstsatz 3,5x.
_PERSONAL = dict(
    category=CATEGORY_PERSONAL,
    threshold_multiplier=2.3,
    max_multiplier=3.5,
    max_per_session=None,
)

# Medizinisch-technische Leistungen: Schwellenwert 1,8x, Höchstsatz 2,5x.
_TECHNICAL = dict(
    category=CATEGORY_TECHNICAL,
    threshold_multiplier=1.8,
    max_multiplier=2.5,
    max_per_session=None,
)

# Unzeit-/Notfall-Zuschläge: immer ungesteigert (1,0x).
_SURCHARGE = dict(
    category=CATEGORY_SURCHARGE,
    threshold_multiplier=1.0,
    max_multiplier=1.0,
    max_per_session=None,
    rule_time_minutes=0,
    exclusion_ziffern=[],
)


def _entry(
    ziffer: str,
    title_official: str,
    title_patient: str,
    fee_simple: float,
    fee_threshold: float,
    fee_max: float,
    *,
    sort_order: int,
    base: dict[str, Any],
    rule_time_minutes: int = 0,
    exclusion_ziffern: list[str] | None = None,
    max_per_session: int | None = None,
) -> dict[str, Any]:
    row = {
        "ziffer": ziffer,
        "title_official": title_official,
        "title_patient": title_patient,
        "rule_time_minutes": rule_time_minutes,
        "exclusion_ziffern": list(exclusion_ziffern or []),
        "fee_simple": fee_simple,
        "fee_threshold": fee_threshold,
        "fee_max": fee_max,
        "sort_order": sort_order,
        **base,
    }
    if max_per_session is not None:
        row["max_per_session"] = max_per_session
    return row


GOA_CATALOG: list[dict[str, Any]] = [
    # --- A) Persönliche Leistungen ------------------------------------------
    _entry(
        "1",
        "Beratung, auch mittels Fernsprecher",
        "Kurzes Beratungsgespräch mit dem Arzt.",
        4.66, 10.72, 16.32,
        sort_order=10, base=_PERSONAL, exclusion_ziffern=["3"],
    ),
    _entry(
        "3",
        "Eingehende, das gewöhnliche Maß übersteigende Beratung (Dauer mindestens 10 Minuten)",
        "Ausführliches Beratungsgespräch von mindestens 10 Minuten.",
        8.74, 20.11, 30.48,
        sort_order=20, base=_PERSONAL, rule_time_minutes=10, exclusion_ziffern=["1"],
    ),
    _entry(
        "4",
        "Erhebung der Fremdanamnese über einen Kranken oder Unterweisung der Bezugspersonen",
        "Gespräch mit Angehörigen oder Bezugspersonen zur Vorgeschichte bzw. Anleitung.",
        12.82, 29.49, 44.88,
        sort_order=30, base=_PERSONAL,
    ),
    _entry(
        "34",
        "Erörterung der Auswirkungen einer lebensverändernden Erkrankung (Dauer mindestens 20 Minuten)",
        "Ausführliches Gespräch über eine schwerwiegende Diagnose, mindestens 20 Minuten.",
        17.49, 40.22, 61.20,
        sort_order=40, base=_PERSONAL, rule_time_minutes=20,
    ),
    _entry(
        "5",
        "Symptombezogene Untersuchung",
        "Körperliche Untersuchung bezogen auf Ihre aktuellen Beschwerden.",
        4.66, 10.72, 16.32,
        sort_order=50, base=_PERSONAL, exclusion_ziffern=["7", "8"],
    ),
    _entry(
        "7",
        "Vollständige körperliche Untersuchung eines Organsystems",
        "Gründliche Untersuchung eines Organsystems (z. B. Herz/Kreislauf oder Bewegungsapparat).",
        9.33, 21.45, 32.64,
        sort_order=60, base=_PERSONAL, exclusion_ziffern=["5"],
    ),
    _entry(
        "8",
        "Untersuchung zur Erhebung des Ganzkörperstatus",
        "Vollständige körperliche Untersuchung (Ganzkörperstatus), mindestens 20 Minuten.",
        14.57, 33.52, 51.00,
        sort_order=70, base=_PERSONAL, rule_time_minutes=20, exclusion_ziffern=["5"],
    ),
    _entry(
        "11",
        "Digitaluntersuchung des Enddarms und/oder der Prostata",
        "Tastuntersuchung des Enddarms (rektale Untersuchung).",
        5.25, 12.07, 18.36,
        sort_order=80, base=_PERSONAL,
    ),
    _entry(
        "50",
        "Besuch, einschließlich Beratung und symptombezogener Untersuchung",
        "Hausbesuch durch den Arzt.",
        18.65, 42.90, 65.28,
        sort_order=90, base=_PERSONAL,
    ),
    _entry(
        "60",
        "Konsiliarische Erörterung zwischen zwei Ärzten",
        "Fachlicher Austausch des Arztes mit einem anderen Arzt zu Ihrem Fall.",
        9.33, 21.45, 32.64,
        sort_order=100, base=_PERSONAL,
    ),
    _entry(
        "70",
        "Kurze Bescheinigung, kurzes Zeugnis, Arbeitsunfähigkeitsbescheinigung",
        "Kurzes Attest oder kurze Bescheinigung.",
        2.33, 5.36, 8.16,
        sort_order=110, base=_PERSONAL,
    ),
    _entry(
        "75",
        "Ausführlicher schriftlicher Krankheits- und Befundbericht",
        "Ausführlicher schriftlicher Befund- oder Arztbrief.",
        7.58, 17.43, 26.52,
        sort_order=120, base=_PERSONAL,
    ),
    # --- B) Medizinisch-technische Leistungen -------------------------------
    _entry(
        "200",
        "Verband, groß, außer Verbände mit Spezialsalben",
        "Anlegen eines Verbandes.",
        2.62, 4.72, 6.56,
        sort_order=200, base=_TECHNICAL, exclusion_ziffern=["2006", "250"],
    ),
    _entry(
        "250",
        "Blutentnahme mittels Spritze oder Kanüle aus der Vene",
        "Abnahme einer Blutprobe aus der Vene.",
        2.33, 4.20, 5.83,
        sort_order=210, base=_TECHNICAL, exclusion_ziffern=["200", "204", "252"],
    ),
    _entry(
        "252",
        "Injektion, subkutan, submukös, intrakutan oder intramuskulär",
        "Spritze unter die Haut oder in den Muskel.",
        2.33, 4.20, 5.83,
        sort_order=220, base=_TECHNICAL, exclusion_ziffern=["250"],
    ),
    _entry(
        "271",
        "Infusion, intravenös, bis 30 Minuten Dauer",
        "Venöse Infusion von bis zu 30 Minuten.",
        5.83, 10.49, 14.57,
        sort_order=230, base=_TECHNICAL,
    ),
    _entry(
        "410",
        "Ultraschalluntersuchung eines Organs",
        "Ultraschalluntersuchung eines Organs.",
        16.32, 29.38, 40.80,
        sort_order=240, base=_TECHNICAL,
    ),
    _entry(
        "420",
        "Ultraschalluntersuchung jedes weiteren Organs",
        "Ultraschall jedes weiteren Organs (höchstens dreimal je Sitzung).",
        5.83, 10.49, 14.57,
        sort_order=250, base=_TECHNICAL, max_per_session=3,
    ),
    _entry(
        "650",
        "Elektrokardiographische Untersuchung in Ruhe – Standard",
        "Ruhe-EKG (Herzstromkurve in Ruhe).",
        14.75, 26.54, 36.87,
        sort_order=260, base=_TECHNICAL,
    ),
    _entry(
        "651",
        "Elektrokardiographische Untersuchung unter Belastung (Ergometrie)",
        "Belastungs-EKG / Ergometrie.",
        33.22, 59.80, 83.06,
        sort_order=270, base=_TECHNICAL,
    ),
    _entry(
        "2006",
        "Behandlung einer Wunde, die nicht primär heilt oder infiziert ist",
        "Behandlung einer infizierten oder schlecht heilenden Wunde.",
        7.87, 14.16, 19.67,
        sort_order=280, base=_TECHNICAL, exclusion_ziffern=["200"],
    ),
    # --- C) Unzeit- & Notfall-Zuschläge (fest, 1,0x) ------------------------
    _entry(
        "A",
        "Zuschlag A – außerhalb der Sprechstunde",
        "Zuschlag für Behandlung außerhalb der Sprechstunde.",
        4.08, 4.08, 4.08,
        sort_order=400, base=_SURCHARGE,
    ),
    _entry(
        "B",
        "Zuschlag B – in der Zeit von 20 bis 22 Uhr oder 6 bis 8 Uhr",
        "Zuschlag für Behandlung im Spätbereich (20–22 Uhr bzw. 6–8 Uhr).",
        10.49, 10.49, 10.49,
        sort_order=410, base=_SURCHARGE,
    ),
    _entry(
        "C",
        "Zuschlag C – in der Zeit von 22 bis 6 Uhr",
        "Zuschlag für Behandlung in der Nacht (22–6 Uhr).",
        18.65, 18.65, 18.65,
        sort_order=420, base=_SURCHARGE,
    ),
    _entry(
        "D",
        "Zuschlag D – an Samstagen, Sonn- oder Feiertagen",
        "Zuschlag für Behandlung an Samstagen, Sonn- oder Feiertagen.",
        12.82, 12.82, 12.82,
        sort_order=430, base=_SURCHARGE,
    ),
    _entry(
        "K1",
        "Zuschlag K1 – bei Kindern bis zum vollendeten 4. Lebensjahr",
        "Zuschlag für die Behandlung von Kleinkindern bis 4 Jahre.",
        6.99, 6.99, 6.99,
        sort_order=440, base=_SURCHARGE,
    ),
]

GOA_BY_ZIFFER: dict[str, dict[str, Any]] = {row["ziffer"]: row for row in GOA_CATALOG}

SURCHARGE_ZIFFERN = frozenset(
    row["ziffer"] for row in GOA_CATALOG if row["category"] == CATEGORY_SURCHARGE
)

# Harte Kombinationsverbote, die über die Katalog-Listen hinaus eine klare
# Patientenmeldung brauchen (inkl. 204, auch wenn 204 nicht selbst katalogisiert ist).
EXCLUSION_RULES: list[dict[str, Any]] = [
    {
        "left": frozenset({"1"}),
        "right": frozenset({"3"}),
        "require_separate_times": True,
        "message": (
            "🚨 Kombinationsverbot: GOÄ 1 und GOÄ 3 dürfen am selben Tag nicht "
            "gemeinsam abgerechnet werden, sofern keine getrennten Uhrzeiten "
            "angegeben sind."
        ),
    },
    {
        "left": frozenset({"5"}),
        "right": frozenset({"7", "8"}),
        "require_separate_times": False,
        "message": (
            "🚨 Kombinationsverbot: GOÄ 5 darf nicht gemeinsam mit GOÄ 7 oder "
            "GOÄ 8 am selben Tag abgerechnet werden (Doppeluntersuchung)."
        ),
    },
    {
        "left": frozenset({"200"}),
        "right": frozenset({"2006"}),
        "require_separate_times": False,
        "message": (
            "🚨 Kombinationsverbot: GOÄ 200 und GOÄ 2006 dürfen nicht gemeinsam "
            "abgerechnet werden (Wundverband ist im Leistungsinhalt von 2006 enthalten)."
        ),
    },
    {
        "left": frozenset({"250"}),
        "right": frozenset({"200", "204", "252"}),
        "require_separate_times": False,
        "message": (
            "🚨 Kombinationsverbot: GOÄ 250 darf nicht gemeinsam mit GOÄ 200, "
            "204 oder 252 abgerechnet werden."
        ),
    },
]


def normalize_ziffer(raw: str) -> str:
    """Normalisiert OCR-/UI-Ziffern (z. B. 'k 1' -> 'K1', '01' -> '1')."""
    token = (raw or "").strip().upper().replace(" ", "")
    if token in SURCHARGE_ZIFFERN or token == "K1":
        return "K1" if token in {"K1", "K01"} else token
    if token.isdigit():
        return str(int(token))
    return token


def lookup(ziffer: str) -> dict[str, Any] | None:
    """Liefert den Katalogeintrag oder None."""
    return GOA_BY_ZIFFER.get(normalize_ziffer(ziffer))


def default_multiplier(ziffer: str) -> float:
    """Üblicher Abrechnungsfaktor, falls OCR keinen Faktor findet."""
    entry = lookup(ziffer)
    if entry is None:
        return 2.3
    if entry["category"] == CATEGORY_SURCHARGE:
        return 1.0
    return float(entry["threshold_multiplier"])


def is_surcharge(ziffer: str) -> bool:
    entry = lookup(ziffer)
    return bool(entry and entry["category"] == CATEGORY_SURCHARGE)
