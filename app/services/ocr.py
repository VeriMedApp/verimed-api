"""OCR- und Text-Parsing-Service fuer eingescannte/fotografierte GOAE-Rechnungen.

Extrahiert aus hochgeladenen Bild- (JPEG/PNG) oder PDF-Dateien die
abgerechneten GOAE-Ziffern, Steigerungsfaktoren und etwaige schriftliche
Begruendungen mittels einfacher Regex-/String-Heuristiken auf dem erkannten
Rohtext. Es kommt bewusst keine schwergewichtige ML-OCR-Pipeline zum Einsatz:

* PDFs mit eingebetteter Textebene werden ueber ``pypdf`` gelesen.
* Fotografierte Bilder (JPEG/PNG) werden ueber ``pytesseract`` (Tesseract
  OCR) in Text umgewandelt, sofern die Tesseract-Systembinary auf dem
  Zielhost verfuegbar ist. Ist sie es nicht (z.B. auf einem einfachen
  Render-Python-Webservice ohne zusaetzliche apt-Pakete), wird ein klarer
  ``OCREngineUnavailableError`` ausgeloest, statt die Anfrage
  stillschweigend fehlschlagen zu lassen oder falsche Daten zu erzeugen.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date

from app.goa_catalog import default_multiplier, is_surcharge, lookup, normalize_ziffer

logger = logging.getLogger(__name__)

try:
    from PIL import Image
except ImportError:  # pragma: no cover - optionale Abhaengigkeit
    Image = None  # type: ignore[assignment]

try:
    import pytesseract
except ImportError:  # pragma: no cover - optionale Abhaengigkeit
    pytesseract = None  # type: ignore[assignment]

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - optionale Abhaengigkeit
    PdfReader = None  # type: ignore[assignment]


class OCRError(Exception):
    """Basisfehler bei der Rechnungs-Texterkennung/-Extraktion."""


class UnsupportedFileTypeError(OCRError):
    """Der hochgeladene Dateityp wird nicht unterstuetzt."""


class OCREngineUnavailableError(OCRError):
    """Die benoetigte OCR-/PDF-Engine ist auf diesem Host nicht verfuegbar."""


SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/jpg", "image/png"}
SUPPORTED_PDF_TYPES = {"application/pdf"}

# Fallback, falls die Ziffer nicht im Katalog steht (persoenliche Leistung).
DEFAULT_MULTIPLIER = 2.3


@dataclass
class ParsedZiffer:
    """Eine aus dem Rechnungstext erkannte, abgerechnete GOAE-Position."""

    ziffer: str
    multiplier: float = DEFAULT_MULTIPLIER
    justification: str | None = None
    service_time: str | None = None
    raw_line: str = ""


@dataclass
class ParsedInvoice:
    """Ergebnis des Parsings einer hochgeladenen Rechnung."""

    ziffern: list[ParsedZiffer] = field(default_factory=list)
    justification: str | None = None
    raw_text: str = ""
    # Fuer den Abgleich mit dem clientseitigen Geofencing-Tagebuch (ProofMed
    # "Geofencing-Beweis"): Behandlungsdatum (ISO 8601) und Praxisname, sofern
    # auf der Rechnung erkennbar.
    treatment_date: str | None = None
    praxis_name: str | None = None
    practice_email: str | None = None
    invoice_number: str | None = None


# --- Regex-Heuristiken --------------------------------------------------------
# Erkennt z.B. "GOÄ 1", "GOÄ 3", "Ziffer 410", "Ziff. 5", "GOA 250",
# "Nr. 250", "GOÄ 2006".
_ZIFFER_PATTERN = re.compile(
    r"(?:Ziffer|Ziff\.?|GO[ÄA]E?|Nr\.?)\s*[:.\-]?\s*(\d{1,4})\b",
    re.IGNORECASE,
)
# Erkennt z.B. "Zuschlag D", "Zuschlag A", "Zus. K1", "Zuschlag K 1".
_ZUSCHLAG_PATTERN = re.compile(
    r"(?:Zuschlag|Zus\.?)\s*[:.\-]?\s*(A|B|C|D|K\s*1)\b",
    re.IGNORECASE,
)
_TIME_PATTERN = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
# Rechnungs-/Belegnummern wie "GOÄ-2026-101" oder "2026-101" (Rechnungsdatum/
# Referenznummer) duerfen nicht als abgerechnete Ziffer interpretiert werden.
# Diese Muster werden vor der eigentlichen Ziffer-Extraktion aus dem Text
# entfernt, damit z.B. "GOÄ-2026-101" nicht als "Ziffer 2026" erkannt wird.
_INVOICE_REFERENCE_PATTERN = re.compile(
    r"\b(?:GO[ÄA]E?-)?20(?:2[0-9]|3[0-5])-\d{1,6}\b",
    re.IGNORECASE,
)
# Zusaetzliche Absicherung: Jahreszahlen (z.B. aus Rechnungsdatum/-nummer)
# sind niemals eine gueltige GOAE-Ziffer und werden auch dann verworfen, wenn
# sie (z.B. durch OCR-Rauschen) direkt hinter einem Ziffer-Schluesselwort
# stehen.
_ZIFFER_YEAR_MIN = 2020
_ZIFFER_YEAR_MAX = 2035
# Erkennt z.B. "2,3-fach", "3,5-fach", "2.3fach", "3,5x".
_MULTIPLIER_FACH_PATTERN = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*[-\s]?(?:fach|x\b|×)",
    re.IGNORECASE,
)
# Erkennt z.B. "Faktor 2,3", "Faktor: 3.5", "Faktor=2,3".
_MULTIPLIER_FAKTOR_PATTERN = re.compile(
    r"Faktor\s*[:=]?\s*(\d+(?:[.,]\d+)?)",
    re.IGNORECASE,
)
# Erkennt Text nach "Begründung:" / "Begruendung -" bis zum Zeilenende.
_JUSTIFICATION_PATTERN = re.compile(
    r"Begr[uü]ndung\s*[:\-]\s*(.+)",
    re.IGNORECASE,
)
# Erkennt ein explizit ausgezeichnetes Behandlungsdatum, z.B.
# "Behandlungsdatum: 15.03.2026" oder "Behandlungstag 15.3.26".
_TREATMENT_DATE_LABELED_PATTERN = re.compile(
    r"Behandlungs(?:datum|tag)\s*[:\-]?\s*(\d{1,2}\.\d{1,2}\.\d{2,4})",
    re.IGNORECASE,
)
# Fallback: irgendein deutsches Datum (TT.MM.JJJJ / TT.MM.JJ) im Text, falls
# kein explizit ausgezeichnetes Behandlungsdatum gefunden wurde.
_GENERIC_DATE_PATTERN = re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b")
# Erkennt den Praxisnamen, z.B. "Praxis Dr. Weber" oder "Praxis Mustermann".
_PRAXIS_NAME_PATTERN = re.compile(
    r"Praxis\s+((?:Dr\.?\s+)?[A-ZÄÖÜ][\wÄÖÜäöüß\-]*(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß\-]*){0,3})"
)
# Praxis-/Abrechnungs-E-Mail im Rechnungskopf, z.B. info@mvz-philippstor.de.
_EMAIL_PATTERN = re.compile(
    r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)
_PREFERRED_EMAIL_LOCALS = (
    "info",
    "rechnung",
    "praxis",
    "kontakt",
    "mail",
    "office",
    "abrechnung",
    "verwaltung",
)
# Ausgezeichnete Rechnungsnummer, z.B. "Rechnungsnr.: GOÄ-2026-101".
_INVOICE_NUMBER_LABELED_PATTERN = re.compile(
    r"Rechnungs(?:nr\.?|nummer)\s*[:.\-]?\s*([A-ZÄÖÜ0-9][A-ZÄÖÜ0-9.\-/]{2,})",
    re.IGNORECASE,
)


def _to_float(raw: str) -> float:
    """Wandelt eine erkannte Zahl (deutsches oder englisches Format) in float."""
    return float(raw.replace(",", "."))


def _looks_like_year(raw: str) -> bool:
    """True, wenn der erkannte Zahlenwert eher eine Jahreszahl als eine Ziffer ist."""
    return raw.isdigit() and _ZIFFER_YEAR_MIN <= int(raw) <= _ZIFFER_YEAR_MAX


def _parse_german_date(raw: str) -> str | None:
    """Wandelt ein TT.MM.JJJJ/TT.MM.JJ-Datum in ISO 8601 (YYYY-MM-DD) um."""
    parts = raw.split(".")
    if len(parts) != 3:
        return None
    try:
        day, month, year = (int(p) for p in parts)
    except ValueError:
        return None
    if year < 100:
        year += 2000
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _extract_treatment_date(text: str) -> str | None:
    """Erkennt das Behandlungsdatum einer Rechnung (ISO 8601), sofern vorhanden."""
    labeled = _TREATMENT_DATE_LABELED_PATTERN.search(text)
    if labeled:
        parsed = _parse_german_date(labeled.group(1))
        if parsed:
            return parsed
    generic = _GENERIC_DATE_PATTERN.search(text)
    if generic:
        return _parse_german_date(generic.group(0))
    return None


def _extract_practice_email(text: str) -> str | None:
    """Erkennt eine Praxis-/Abrechnungs-E-Mail, bevorzugt im Rechnungskopf."""
    found = [m.group(0) for m in _EMAIL_PATTERN.finditer(text)]
    if not found:
        return None
    header = "\n".join(text.splitlines()[:12])
    header_emails = [m.group(0) for m in _EMAIL_PATTERN.finditer(header)]
    pool = header_emails or found
    for email in pool:
        local = email.split("@", 1)[0].lower()
        if any(token in local for token in _PREFERRED_EMAIL_LOCALS):
            return email
    return pool[0]


def _extract_invoice_number(text: str) -> str | None:
    """Erkennt eine Rechnungsnummer, sofern vorhanden."""
    labeled = _INVOICE_NUMBER_LABELED_PATTERN.search(text)
    if labeled:
        return labeled.group(1).strip().rstrip(".")
    ref = _INVOICE_REFERENCE_PATTERN.search(text)
    if ref:
        return ref.group(0).strip()
    return None


def _extract_praxis_name(text: str) -> str | None:
    """Erkennt den Praxisnamen einer Rechnung, sofern vorhanden.

    Zeilenweise Suche (statt ueber den gesamten Text), da "\\s+" in der
    Namens-Wiederholungsgruppe sonst ueber Zeilenumbrueche hinweg auch die
    naechste Zeile (z.B. "Behandlungsdatum") als Namensbestandteil erfassen
    wuerde.
    """
    for line in text.splitlines():
        match = _PRAXIS_NAME_PATTERN.search(line)
        if match:
            return f"Praxis {match.group(1).strip()}"
    return None


def _guess_suffix(filename: str | None) -> str:
    name = (filename or "").lower()
    return name.rsplit(".", 1)[-1] if "." in name else ""


def extract_text(filename: str | None, content_type: str | None, data: bytes) -> str:
    """Extrahiert Rohtext aus einer hochgeladenen Rechnungsdatei (PDF oder Bild)."""
    ctype = (content_type or "").lower()
    suffix = _guess_suffix(filename)

    if ctype in SUPPORTED_PDF_TYPES or suffix == "pdf":
        return _extract_text_from_pdf(data)
    if ctype in SUPPORTED_IMAGE_TYPES or suffix in {"jpg", "jpeg", "png"}:
        return _extract_text_from_image(data)

    raise UnsupportedFileTypeError(
        f"Dateityp '{content_type or suffix or 'unbekannt'}' wird nicht "
        "unterstuetzt. Bitte JPEG, PNG oder PDF hochladen."
    )


def _extract_text_from_pdf(data: bytes) -> str:
    if PdfReader is None:
        raise OCREngineUnavailableError(
            "PDF-Verarbeitung ist auf diesem Server nicht verfuegbar "
            "(Python-Paket 'pypdf' fehlt)."
        )
    try:
        reader = PdfReader(io.BytesIO(data))
        pages_text = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:  # defensiv: beschaedigte/verschluesselte PDFs
        raise OCRError(f"PDF konnte nicht gelesen werden: {exc}") from exc

    text = "\n".join(pages_text).strip()
    if not text:
        raise OCRError(
            "Im PDF wurde keine auslesbare Textebene gefunden. Vermutlich "
            "handelt es sich um ein eingescanntes Bild-PDF ohne Textlayer."
        )
    return text


def _extract_text_from_image(data: bytes) -> str:
    if Image is None or pytesseract is None:
        raise OCREngineUnavailableError(
            "Bilderkennung (OCR) ist auf diesem Server nicht verfuegbar. Es "
            "fehlen die Python-Pakete 'Pillow'/'pytesseract' oder die "
            "Tesseract-OCR-Systembinary auf dem Host."
        )
    try:
        image = Image.open(io.BytesIO(data))
        image = image.convert("L")  # Graustufen verbessern die OCR-Trefferquote.
        text = pytesseract.image_to_string(image, lang="deu+eng")
    except pytesseract.TesseractNotFoundError as exc:
        raise OCREngineUnavailableError(
            "Die Tesseract-OCR-Systembinary ist auf diesem Host nicht "
            "installiert. Bilderkennung ist daher aktuell nicht moeglich; "
            "bitte alternativ ein PDF mit Textebene hochladen."
        ) from exc
    except OCRError:
        raise
    except Exception as exc:  # defensiv: unlesbare/kaputte Bilddateien
        raise OCRError(f"Bild konnte nicht verarbeitet werden: {exc}") from exc

    text = text.strip()
    if not text:
        raise OCRError(
            "Im Bild konnte kein Text erkannt werden. Bitte ein schaerferes, "
            "besser beleuchtetes Foto der Rechnung aufnehmen."
        )
    return text


def _window_around(text: str, start: int, end: int, before: int = 24, after: int = 96) -> str:
    return text[max(0, start - before) : min(len(text), end + after)]


def _extract_multiplier(window: str, ziffer: str) -> float:
    """Liest den Steigerungsfaktor aus einem Textfenster um die Ziffer."""
    fallback = default_multiplier(ziffer)
    match = _MULTIPLIER_FACH_PATTERN.search(window) or _MULTIPLIER_FAKTOR_PATTERN.search(
        window
    )
    if not match:
        return 1.0 if is_surcharge(ziffer) else fallback
    try:
        return _to_float(match.group(1))
    except ValueError:
        return 1.0 if is_surcharge(ziffer) else fallback


def _extract_service_time(window: str) -> str | None:
    match = _TIME_PATTERN.search(window)
    if not match:
        return None
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def _threshold_for(ziffer: str) -> float:
    entry = lookup(ziffer)
    if entry is None:
        return DEFAULT_MULTIPLIER
    return float(entry["threshold_multiplier"])


def parse_invoice_text(text: str) -> ParsedInvoice:
    """Extrahiert GOAE-Ziffern, Steigerungsfaktoren und Begruendung aus Text."""
    # Rechnungs-/Belegnummern (z.B. "GOÄ-2026-101", "2026-101") vorab entfernen,
    # damit sie unten nicht faelschlich als Ziffer erkannt werden.
    sanitized_text = _INVOICE_REFERENCE_PATTERN.sub(" ", text)

    justification_match = _JUSTIFICATION_PATTERN.search(sanitized_text)
    justification = (
        justification_match.group(1).strip() if justification_match else None
    )

    ziffern: list[ParsedZiffer] = []
    seen: set[str] = set()

    def _add_item(ziffer: str, start: int, end: int) -> None:
        ziffer = normalize_ziffer(ziffer)
        if not ziffer:
            return
        if _looks_like_year(ziffer):
            return
        allow_dupes = (ziffer == "420")
        if ziffer in seen and not allow_dupes:
            return
        window = _window_around(sanitized_text, start, end)
        factor_window = (
            sanitized_text[end : end + 96] if is_surcharge(ziffer) else window
        )
        multiplier = _extract_multiplier(factor_window, ziffer)
        threshold = _threshold_for(ziffer)
        if not allow_dupes:
            seen.add(ziffer)
        ziffern.append(
            ParsedZiffer(
                ziffer=ziffer,
                multiplier=multiplier,
                justification=(
                    justification if multiplier > threshold + 1e-6 else None
                ),
                service_time=_extract_service_time(window),
                raw_line=window.strip(),
            )
        )

    for match in _ZIFFER_PATTERN.finditer(sanitized_text):
        _add_item(match.group(1), match.start(), match.end())
    for match in _ZUSCHLAG_PATTERN.finditer(sanitized_text):
        token = re.sub(r"\s+", "", match.group(1))
        _add_item(token, match.start(), match.end())

    return ParsedInvoice(
        ziffern=ziffern,
        justification=justification,
        raw_text=text,
        treatment_date=_extract_treatment_date(sanitized_text),
        praxis_name=_extract_praxis_name(sanitized_text),
        practice_email=_extract_practice_email(text),
        invoice_number=_extract_invoice_number(text),
    )


def parse_uploaded_invoice(
    filename: str | None, content_type: str | None, data: bytes
) -> ParsedInvoice:
    """High-level Einstiegspunkt: Datei -> Rohtext -> geparste Rechnung."""
    text = extract_text(filename, content_type, data)
    parsed = parse_invoice_text(text)
    logger.info(
        "Rechnung geparst: %d Ziffer(n) erkannt, Begruendung vorhanden=%s",
        len(parsed.ziffern),
        bool(parsed.justification),
    )
    return parsed
