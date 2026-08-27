# ProofMed – System-Architektur & Bedienungshandbuch

**Version:** 1.0 · **Stand:** Auto-generiert aus dem aktuellen Codestand (`app/static/index.html`, `index.html`, `app/`, `android/`)
**Zielgruppe:** Entwickler:innen, Tester:innen, technische Redaktion, Support

---

## Inhaltsverzeichnis

1. [System-Überblick & Kernfunktionen](#1-system-überblick--kernfunktionen)
2. [Feature-Anleitung für Nutzer & Tester](#2-feature-anleitung-für-nutzer--tester-bedienungsanleitung)
3. [Datenfluss & Speicher-Architektur](#3-vollständiger-datenfluss--speicher-architektur)
4. [Test- & Verifikations-Leitfaden](#4-test--verifikations-leitfaden)
5. [Build, Deployment & APK-Wartung](#5-build-deployment--apk-wartung)
6. [Bekannte Einschränkungen & offene Punkte](#6-bekannte-einschränkungen--offene-punkte)

---

## 1. System-Überblick & Kernfunktionen

### 1.1 Was ist ProofMed?

ProofMed ist ein **Pre-Payment-Audit-Assistent** für privatärztliche Liquidationen nach der
deutschen **GOÄ** (Gebührenordnung für Ärzte). Patient:innen fotografieren oder scannen ihre
Rechnung, die App prüft automatisch die abgerechneten GOÄ-Ziffern gegen ein festes Regelwerk
(Kombinationsverbote, Höchstsätze, Zeitplausibilität) und erzeugt bei Auffälligkeiten einen
formellen Einwand samt Nachweis-Dossier – **bevor** die Rechnung bezahlt wird ("Zahlung
gestoppt / Frist eingefroren").

Das Produkt existiert technisch als **zwei getrennte Komponenten**, die im aktuellen Code
**nicht** direkt miteinander sprechen (siehe Abschnitt 1.4):

| Komponente | Ort im Repo | Rolle |
|---|---|---|
| **Frontend-App** (aktiv genutzt) | `app/static/index.html` (Quelle), gespiegelt nach `index.html`, `android/…/assets/public/`, `ios/…/public/` | Vollständig **client-seitige** Single-Page-App: OCR, Audit-Engine, PDF-Erzeugung, Fall-Verwaltung, Jahres-Dossier. Läuft als PWA im Browser oder als Capacitor-App (Android/iOS). |
| **Backend** (`app/`) | FastAPI-Service, deploybar auf Render als `verimed-backend` | Liefert die Frontend-App als statische Website aus, bietet eine **Zero-Knowledge-E2EE-Cloud-Backup-API** (`/api/v1/backup/*`) und enthält zusätzlich ein **separates, serverseitiges** GOÄ-Audit-/Claims-API (`/api/v1/claims/*`, `/api/v1/audit`), das von der aktuellen Frontend-Oberfläche **nicht aufgerufen wird**. |

### 1.2 Der Pre-Payment-Audit-Workflow (Ende-zu-Ende)

```
1. Praxisbesuch          →  Tagebuch: Live-Check-in per GPS oder manueller Eintrag
                             (Ankunft/Abfahrt, Dauer, SHA-256-Zeitstempel-Hash)

2. Rechnung erhalten      →  Tab "Audit & OCR": Foto/PDF hochladen
                             → Tesseract.js-OCR (Bild) bzw. PDF.js-Textextraktion (PDF)
                             → automatische GOÄ-Ziffern-, Faktor-, Datums-, Praxis- und
                               Rechnungsbetrags-Erkennung

3. Regelprüfung           →  Audit-Engine (rein clientseitig, in-memory):
                             - Kombinationsverbote (z.B. GOÄ 1 + GOÄ 3 am selben Tag)
                             - Höchstsatz-Prüfung (Steigerungsfaktor > 3,5x)
                             - Zeit-Plausibilität ggü. dem Geofence-Tagebucheintrag
                               (Mindestbehandlungszeit vs. tatsächliche Anwesenheit)

4. Bei Auffälligkeit      →  "Zahlung gestoppt (Frist eingefroren)" wird angezeigt,
                             ein Einwand-Text wird vorformuliert (mit Profil-Signatur)

5. Einwand versenden      →  "In Mail-App" (mailto:, CRLF-formatiert) oder
                             "Kombi-PDF teilen" (echtes binäres PDF mit Logo & Hash-Chip)
                             → Fall wird automatisch als "FROZEN" persistiert und mit dem
                               passenden Tagebucheintrag verknüpft

6. Korrektur erhalten     →  Im Dossier-Tab: "Als korrigiert markieren" → korrigierten
                             Betrag eingeben → Ersparnis wird berechnet, Fall wird "RESOLVED"

7. Jahresabschluss        →  Dossier-Tab: KPI-Zusammenfassung (Original- vs. regulierter
                             Betrag, Gesamtersparnis) + druckfertiges Steuer-/Beihilfe-PDF
                             mit ProofMed-Briefkopf und Patientendaten
```

### 1.3 Privacy-First / DSGVO-konforme lokale Vault-Architektur

Alle medizinisch-sensiblen Daten (Tagebuch, Fälle, Patientenprofil, GPS-Koordinaten,
OCR-Rohtext) bleiben **ausschließlich lokal** auf dem Gerät:

- **Web/PWA:** `localStorage` des Browsers.
- **Native App (Android/iOS via Capacitor):** native SQLite-Datenbank `proofmed.db`
  (Plugin `@capacitor-community/sqlite`), mit `localStorage` als Fallback bei
  Initialisierungsfehlern.

Es findet **keine automatische Übertragung** medizinischer Rohdaten an einen Server statt. Die
einzige optionale Netzwerkfunktion ist das **Zero-Knowledge-E2EE-Cloud-Backup** (Abschnitt 2.2 /
3.3): Das Tagebuch wird lokal mit einer vom Nutzer eingegebenen 6-stelligen PIN per
AES-256-GCM verschlüsselt, bevor der reine Chiffretext an das Backend übertragen wird. Das
Backend erhält weder die PIN noch den Schlüssel noch Klartext – es speichert ausschließlich
`ciphertext_base64`, `iv_base64`, `salt_base64` und einen SHA-256-Hash der PIN als Suchschlüssel
(`user_id_hash`).

Das UI weist prominent auf diese Architektur hin ("100% DSGVO-konform & Lokal"-Badge im Header,
Datenschutz-Modal mit Erklärtext).

### 1.4 Zwei GOÄ-Engines: Client (aktiv) vs. Server (vorhanden, nicht angebunden)

Ein für Entwickler:innen wichtiger struktureller Fakt: Im Repository existieren **zwei
unabhängige GOÄ-Regelwerke**:

1. **`GOA_CATALOG` in `app/static/index.html`** (JavaScript, ca. 26 Ziffern/Zuschläge) –
   dies ist die **einzige Engine, die die ausgelieferte App tatsächlich verwendet**. Sie läuft
   vollständig im Browser/WebView, ohne Serverkontakt.
2. **`app/goa_catalog.py` + `app/services/validator.py`** (Python/FastAPI, exponiert über
   `/api/v1/claims/validate` und `/api/v1/claims/catalog`) – ein separates, funktionsfähiges
   Backend-Regelwerk mit eigener Datenbanktabelle (`goa_ziffern`), das laut README für ein
   früheres/alternatives Frontend ("Lovable") konzipiert wurde. **Die aktuelle Capacitor-App
   ruft diese Endpunkte nicht auf.**

Bei künftigen Änderungen an GOÄ-Sätzen, Kombinationsverboten oder Höchstsätzen müssen **beide
Stellen** geprüft werden, falls beide Engines produktiv genutzt werden sollen. Aktuell ist nur
die JS-Version für den Nutzer wirksam.

---

## 2. Feature-Anleitung für Nutzer & Tester (Bedienungsanleitung)

Die App gliedert sich in drei Haupt-Tabs (Header-Navigation): **Audit & OCR**, **Tagebuch**,
**Dossier**. Ein Profil-Icon (Kopf-Symbol) oben rechts öffnet das Patientenprofil.

### 2.1 Onboarding & Profil

**Ort:** Kopf-Symbol oben rechts im Header → Modal "Patientenprofil & lokaler Tresor".

Beim ersten Start ist kein Profil hinterlegt. Solange `isConfigured` `false` ist, zeigt der
Audit-Tab oben einen **dezenten, nicht blockierenden Hinweisbanner**:

> "Profil noch nicht eingerichtet – Name & Anschrift für Einwand-Schreiben hinterlegen."
> mit Button **"Jetzt einrichten"**

Im Profil-Modal können folgende Felder gepflegt werden:

| Feld | Zweck |
|---|---|
| Vollständiger Name | Ersetzt den Platzhalter "Max Mustermann" in generierten Einwand-Briefen |
| Anschrift | Wird unter der Unterschrift im Einwand-Text und im Dossier-Briefkopf angezeigt |
| Krankenversicherung | Freitext (z.B. "Debeka PKV"), erscheint im Dossier-Briefkopf |
| Versichertennummer | Erscheint im Dossier-Briefkopf |
| Beihilfe-Nummer (optional) | Erscheint im Dossier-Briefkopf |
| Tresor-PIN (optional, 4–6 Ziffern) | Wird im Profil gespeichert, ist aber **nicht** identisch mit der PIN für das Cloud-Backup (siehe Hinweis unten) |

Klick auf **"Profil speichern"** persistiert den Datensatz sofort lokal; das Modal schließt,
der Hinweisbanner verschwindet automatisch (`isConfigured = true`, sobald Name **und**
Anschrift ausgefüllt sind).

> ⚠️ **Hinweis für Tester:** Die im Profil hinterlegte "Tresor-PIN" wird aktuell an **keiner**
> Stelle der App zur Zugriffskontrolle abgefragt (kein App-Lock-Screen implementiert). Die
> separate 6-stellige PIN, die beim Cloud-Backup (Tagebuch-Tab, "☁️ Backup auf Hetzner
> speichern") per Eingabedialog abgefragt wird, ist ein **eigener, unabhängiger** Wert, der
> niemals gespeichert, sondern bei jedem Vorgang neu eingegeben und nur zur
> Schlüsselableitung/Hash-Bildung verwendet wird.

### 2.2 Tagebuch & Geofencing

**Ort:** Tab "Tagebuch"

**Live-Check-in ("Ich bin jetzt in der Praxis")**
1. Button antippen → Eingabe-Dialog fragt den Praxisnamen ab.
2. Die App versucht, per `navigator.geolocation.getCurrentPosition()` GPS-Koordinaten zu
   erfassen (`lat`, `lng`, `accuracy`). Gelingt dies, wird der Eintrag als `logType: 'GPS_LIVE'`
   markiert (grünes "GPS Live"-Badge mit Live-Pulse-Animation); scheitert die
   Positionsermittlung (z.B. Berechtigung verweigert), fällt der Eintrag automatisch auf
   `logType: 'MANUAL_ENTRY'` zurück.
3. Ankunftszeit wird sofort erfasst; der Button "Praxis verlassen" wird aktiv, "Ich bin jetzt
   in der Praxis" wird deaktiviert (nur ein aktiver Live-Besuch gleichzeitig möglich).

**Live-Check-in beenden ("Praxis verlassen")**
- Erfasst die Abfahrtszeit, berechnet `durationMin` und speichert den vollständigen Eintrag im
  Tagebuch (`saveDiaryEntry`).

**Manueller Fallback-Eintrag**
- Formular "Praxisbesuch manuell nachtragen" (Praxisname, Datum, Ankunft, Abfahrt) → Button
  "In Tagebuch speichern". Nützlich für nachträglich erfasste oder GPS-lose Besuche.

**Jeder gespeicherte Tagebucheintrag erhält automatisch:**
- eine stabile, eindeutige `id` (UUID via `crypto.randomUUID()`),
- einen `proofHash` (SHA-256 über `date|arrival|departure|practice|durationMin`) als
  manipulationssicheren Zeitstempel-Nachweis, sichtbar als "SHA-256"-Zeile auf der Karte.

**Filter & Verwaltung:** Pillen "Aktive Besuche" / "Archiv" / "Alle" filtern die Liste. Pro
Eintrag stehen "Archivieren" und "Löschen" zur Verfügung.

**Verknüpfungs-Badge:** Sobald für einen Tagebucheintrag ein Fall (Case) existiert, erscheint
zusätzlich ein Badge:
- `🔴 Verknüpft: Zahlung gestoppt · <Praxisname>` (Status FROZEN)
- `🟠 Verknüpft: Wartet auf Korrektur · <Praxisname>` (Status WAITING_CORRECTION)
- `🟢 Verknüpft: Erledigt (Korr. 18,50 €) · <Praxisname>` (Status RESOLVED, inkl. korrigiertem
  Betrag)

Ein Klick auf dieses Badge springt direkt in den Dossier-Tab zum betreffenden Fall.

### 2.3 Audit-Engine & OCR-Scan

**Ort:** Tab "Audit & OCR"

**Rechnung hochladen:** Button "Foto / PDF wählen" öffnet den nativen Datei-/Kamera-Dialog
(`accept="image/*,application/pdf,.pdf"`, kein `capture`-Attribut, damit auf Android der volle
Auswahldialog Kamera/Galerie/Dateien erscheint statt direkt die Kamera zu starten).

**Verarbeitungspfad:**
- **PDF:** `pdf.js` extrahiert zunächst den eingebetteten Text-Layer. Enthält dieser mehr als
  30 Zeichen, wird er direkt verwendet. Andernfalls (gescanntes PDF ohne Text-Layer) wird
  Seite 1 auf einen Canvas gerendert und per Tesseract OCR erkannt.
- **Bild (JPG/PNG/…):** Das Bild durchläuft zunächst `preprocessImageToCanvas()`:
  Herunterskalierung nur oberhalb 2400px, Graustufen-Gewichtung, und ein **adaptives lokales
  Schwellenwertverfahren** (blockbasierte Hintergrund-Schätzung statt eines einzigen globalen
  Kontrast-Pivots), um ungleichmäßige Beleuchtung/Schatten auf Fotos robust auszugleichen.
  Anschließend läuft Tesseract.js (`deu+eng`) über das normalisierte Bild.

**Text-Normalisierung (`normalizeOCRText`):** Fängt typische OCR-Fehllesungen robust ab, u.a.:
- `GOA`, `G0A` (Ziffer 0 statt Buchstabe O), `GOAE`, `GOE` (Umlaut verschluckt/als E gelesen),
  bloßes `GO` vor einer gültigen Ziffer → werden alle zu `GOÄ` normalisiert,
- `Ziffer`, `Nr.`, `Pos`/`Pos.` → werden zu `GOÄ` normalisiert,
- typische Ziffern-Verwechslungen (`25O`→`250`, `65O`→`650`, `2OO`→`200`, `41O`→`410` usw.).

**Strikte zeilenweise Ziffern-Extraktion:** Ein GOÄ-Code wird nur akzeptiert, wenn in derselben
Zeile ein GOÄ-Bezeichner **unmittelbar** von einem gültigen Code gefolgt wird **und** dieselbe
Zeile zusätzlich einen Steigerungsfaktor (z.B. `3,5x`) oder einen Geldbetrag enthält. Dadurch
werden u.a. folgende historische Fehlerquellen ausgeschlossen:
- freistehende Zahlen in Fließtext (z.B. "60 Minuten" in einem Hinweistext) werden **nicht**
  als GOÄ 60 fehlinterpretiert,
- Preisfragmente (z.B. "34,97 €") werden **nicht** in "GOÄ 34" zerlegt,
- einzelne Buchstaben in normalem Fließtext werden **nicht** als Zuschlag A–D fehlgedeutet,
- Zeilen, die mit `Hinweis`, `Test-Hinweis`, `ProofMed`, `Mindestbehandlungszeit` u.ä. beginnen,
  werden komplett ignoriert (Fußzeilen/Testnotizen).
- Werden mehrere Rechnungspositionen von der OCR versehentlich in **eine** Textzeile
  zusammengeführt, wird jeder Code an das **nächstgelegene** Faktor-/Betrags-Fragment in seinem
  eigenen Zeilenabschnitt gebunden (kein Faktor-"Leck" zwischen benachbarten Positionen).

**Erkannt werden zusätzlich:** Behandlungsdatum, Praxisname (Heuristik über "Dr.", "Praxis",
"MVZ", "Gemeinschaftspraxis", "Klinik", "Institut" – wird an Trennzeichen wie "·" oder
Preisangaben abgeschnitten) sowie der **tatsächliche Rechnungsgesamtbetrag** (bevorzugt eine
Zeile mit "Gesamtbetrag"/"Rechnungsbetrag"/"Endbetrag"/"Gesamt", sonst der größte im Dokument
gefundene Geldbetrag).

**Manuelle Prüfung (Alternative zum Scan):** Im Bereich "GOÄ-Ziffern interaktiv testen" können
Ziffern über den Katalog (Filter "Alle" / "Persönlich" / "Technisch" / "Zuschläge", Suchfeld)
manuell ausgewählt und deren Steigerungsfaktor per Dropdown gesetzt werden. Button "Audit für
gewählte Ziffern ausführen" startet die Prüfung ohne OCR.

**Regelprüfungen der Audit-Engine (`runAuditEngine`):**
| Regel | Auslöser | Schweregrad |
|---|---|---|
| Steigerung über Schwellenwert | Persönliche Leistung mit Faktor > 2,3x (bis 3,5x) | WARN |
| Technische Leistung über Schwellenwert | Technische Leistung mit Faktor > 1,8x | WARN |
| Unzulässiger Höchstsatz | Faktor > 3,5x | ERROR |
| Kombinationsverbot | GOÄ 1 + GOÄ 3 am selben Tag | ERROR |
| Kombinationsverbot | GOÄ 5 + (GOÄ 7 oder GOÄ 8) am selben Tag | ERROR |
| Physische Unmöglichkeit (Zeitkonflikt) | Summe der GOÄ-Mindestbehandlungszeiten übersteigt die im Tagebuch erfasste tatsächliche Anwesenheitsdauer | ERROR |

Bei mindestens einem ERROR oder WARN wird die "Zahlung gestoppt"-Karte samt
Einwand-Formular eingeblendet (siehe 2.4).

### 2.4 Einwand-Generierung & Case Freeze

Sobald Prüfungsergebnisse vorliegen, erscheint die Karte **"Formeller Einwand gegen
Liquidation"** mit vier Aktionen:

| Button | Wirkung |
|---|---|
| **In Mail-App** | Öffnet den nativen `mailto:`-Client mit vorausgefülltem Betreff/Empfänger/Text. Der Body wird mit **striktem doppeltem CRLF** (`%0D%0A%0D%0A`) zwischen **jeder** Zeile (Absätze *und* Aufzählungspunkte) kodiert, da Webmailer wie WEB.DE/GMX/Gmail einzelne Zeilenumbrüche beim Konvertieren in HTML sonst zu einem Fließtext zusammenfallen lassen. |
| **Kombi-PDF teilen** | Erzeugt ein **echtes binäres PDF** (jsPDF) und übergibt es über die native Web-Share-API (`navigator.share`) als `application/pdf`-Datei. Ohne Share-Unterstützung erfolgt automatisch ein direkter Download derselben Datei. |
| **PDF drucken** | Baut dasselbe PDF, ruft `doc.autoPrint()` auf und öffnet es als Blob-URL in einem neuen Tab (löst den systemeigenen Druckdialog/"Als PDF speichern" aus). Bei blockiertem Popup erfolgt automatisch ein Direkt-Download. |
| **Text kopieren** | Kopiert den reinen Einwand-Text in die Zwischenablage. |

**Aufbau des generierten PDFs (`buildObjectionPdfDoc`):**
- Kopfzeile mit ProofMed-Logo und "ProofMed \| Pre-Payment Audit System",
- Titel "Formeller Einwand gegen Medizinische Liquidation" + Metadaten (Praxis, Datum,
  **nur echte GOÄ-Katalog-Ziffern** in der Ziffernliste – zufällige, von der OCR
  mitgerissene Zahlen wie eine Jahreszahl werden herausgefiltert),
- rotes Banner "ZAHLUNG GESTOPPT …" bei ERROR/WARN,
- farbcodierte Fehlerboxen (roter Balken = ERROR, gelber Balken = WARN),
- grüne Box "Verifizierter Geofence-Nachweis" mit **monospaced SHA-256-Hash-Chip**, falls ein
  passender Tagebucheintrag existiert,
- der vollständige Einwand-Brieftext (Unterschrift nutzt das Patientenprofil, siehe 2.1),
- ein eigener **Dokumenten-Integritätsstempel (SHA-256)** über den gesamten Fallinhalt,
- optional weitere Seiten: die hochgeladene Originalrechnung (Bild oder alle PDF-Seiten),
  seitenumbruch-getrennt, größenangepasst unter Beibehaltung des Seitenverhältnisses.

**Automatische Fall-Persistenz ("Case Freeze"):** Ein Klick auf **"In Mail-App"** oder
**"Kombi-PDF teilen"** ruft intern `upsertCaseFromObjection()` auf. Dabei wird:
1. ein Fall-Datensatz (`cases`) mit Status `FROZEN` angelegt oder aktualisiert (Schlüssel:
   Rechnungsdatum + Praxisname – ein erneutes Senden setzt einen bereits gelösten Fall wieder
   auf `FROZEN` zurück und löscht die vorherige Korrektur),
2. mit dem passenden Tagebucheintrag verknüpft (`diaryEntryId`),
3. der SHA-256-Hash sowie – falls vorhanden – die hochgeladene Original-Rechnung
   (`receiptDataUrl`) übernommen,
4. der von der Audit-Engine selbst berechnete "korrekte" Betrag als
   `auditedCorrectionAmount` gespeichert (Vorschlagswert für Schritt 2.5).

Die Persistenz ist **fehlertolerant**: Ein Speicherfehler blockiert niemals den eigentlichen
Mail-/Share-Vorgang.

### 2.5 Case-Management & Korrektur

**Ort:** Tab "Dossier", Karte "Fälle mit Zahlungsstopp"

Jeder gesendete Einwand erscheint hier als Fall-Karte mit Praxisname, Rechnungs-/Einwanddatum,
Status-Badge, Betrag und SHA-256-Hash. Zwei Aktionen:

**"Als korrigiert markieren"**
1. Ein Eingabedialog fragt den **tatsächlich korrigierten Rechnungsbetrag** ab. Als Vorschlag
   erscheint der von der Audit-Engine berechnete Betrag (`auditedCorrectionAmount`), ersatzweise
   der ursprüngliche Betrag.
2. Bei gültiger Eingabe (Zahl ≥ 0) wird:
   - `correctedAmount` gesetzt,
   - `savedAmount = originalAmount − correctedAmount` berechnet,
   - `status` auf `RESOLVED` gesetzt, `resolvedDate` auf das aktuelle Datum,
3. Dossier-KPI-Leiste, Fall-Karte **und** das verknüpfte Tagebuch-Badge aktualisieren sich
   sofort synchron (`🟢 Erledigt (Korr. X €)`).
4. Abbruch (Dialog abbrechen) oder ungültige Eingabe ändern den Fall **nicht**.

**"Einwand erneut öffnen"**
- Erstellt eine Erinnerungs-E-Mail (`mailto:`, ebenfalls im doppelten-CRLF-Format) an die
  ursprünglich abgeleitete Praxis-E-Mail-Adresse, mit Verweis auf Einwanddatum, Rechnungsdatum,
  Betrag und den gespeicherten SHA-256-Hash. Der ursprüngliche Einwand-Volltext wird dabei
  **nicht** erneut mitgeschickt (er ist nicht Teil des persistenten Fall-Schemas), sondern es
  wird ein kompaktes Erinnerungsschreiben generiert.

### 2.6 Jahres-Dossier & Steuer-Export (§ 33 EStG / PKV / Beihilfe)

**Ort:** Tab "Dossier"

**KPI-Zusammenfassung** (oberhalb der Fallliste, erscheint sobald mindestens ein Fall
existiert):
- **Ursprüngliche Liquidationen** – Summe aller `originalAmount` im gewählten Zeitraum,
- **Regulierter Endbetrag** – Summe aus `correctedAmount` (gelöste Fälle) bzw. weiterhin
  `originalAmount` (noch offene Fälle),
- **Gesamtersparnis** – Summe von `savedAmount`, **ausschließlich** über tatsächlich gelöste
  (RESOLVED) Fälle; offene Fälle tragen bewusst keine spekulative Ersparnis bei.

**Jahresfilter:** Dropdown "Jahr 2026" / "Jahr 2025" / "Alle Jahre" filtert nach dem
Rechnungsdatum-Jahr der Fälle (`YYYY`-Präfix-Vergleich) und aktualisiert KPI-Leiste, Fallliste
und – bei erneutem Export – auch den Dateinamen von CSV/PDF.

**Export-Karte "Jahres-Dossier & Beihilfe Export":**
- **"CSV-Dossier herunterladen"** – exportiert die Tagebuch-Rohdaten (Datum, Praxis, Ankunft,
  Abfahrt, Dauer, Erfassungsart, SHA-256-Hash) als `.csv`.
- **"PDF-Dossier drucken"** – erzeugt ein **echtes binäres PDF** (`buildDossierPdfDoc`) mit:
  - Briefkopf mit ProofMed-Logo und "ProofMed \| Patientendossier & Nachweisübersicht",
  - **Patientendaten-Box** (Name, Anschrift, Versicherten-/Beihilfenummer, Export-Datum,
    gewähltes Steuerjahr) – gespeist aus dem Patientenprofil (2.1),
  - den drei KPI-Karten (s.o.),
  - einer **seitenumbruchfähigen Tabelle** aller Fälle im gewählten Zeitraum mit Datum,
    Praxis, Zeitfenster, Dauer (aus dem verknüpften Tagebucheintrag), Status (farbiger Punkt
    + Text – bewusst **kein** Unicode-Emoji, da die PDF-Standardschrift Helvetica keine
    Emoji-Glyphen enthält), Betrag (bei gelösten Fällen als "Original → Korrigiert") und
    gekürztem SHA-256-Hash.
  - Auslösung identisch zu 2.4: `doc.autoPrint()` + Blob-URL-Tab, mit Direkt-Download-Fallback
    bei blockiertem Popup.

---

## 3. Vollständiger Datenfluss & Speicher-Architektur

### 3.1 `ProofMedStorage` – der zentrale Storage-Adapter

Definiert in `app/static/index.html`. Bietet eine einheitliche `async`-Schnittstelle
(`getItem(key)` / `setItem(key, value)` / `removeItem(key)`), die transparent zwischen zwei
Backends umschaltet:

```
ProofMedStorage.init()
  ├─ Läuft die App nativ in Capacitor (window.Capacitor.isNativePlatform())?
  │    └─ Ja  → CapacitorSQLite-Plugin, Datenbank "proofmed.db"
  │             Tabelle: proofmed_storage(key TEXT PRIMARY KEY, value TEXT, updated_at)
  │    └─ Nein (Web/PWA) oder SQLite-Init fehlgeschlagen
  │             → Fallback auf window.localStorage (versucht zusätzlich
  │               navigator.storage.persist() für dauerhafte Web-Speicherung)
```

Auf dieser generischen Key-Value-Schicht bauen typisierte Convenience-Methoden auf, die jeweils
**einen JSON-Array-/Objekt-Blob unter einem festen Schlüssel** lesen/schreiben:

| Methode | Storage-Key | Inhalt |
|---|---|---|
| `getDiaryLogs()` / `setDiaryLogs()` | `proofmed_diary` | Array aller Tagebucheinträge |
| `getCases()` / `setCases()` | `proofmed_cases` | Array aller Fälle |
| `getProfile()` / `setProfile()` | `proofmed_profile` | ein Profil-Objekt |

Alle drei Methoden enthalten eine **abwärtskompatible Migrationslogik**, die beim Lesen fehlende
Felder älterer Datensätze automatisch mit sinnvollen Defaults ergänzt und die Änderung im
Hintergrund zurückschreibt – bestehende Nutzerdaten gehen bei App-Updates nicht verloren:

- Tagebucheinträge ohne `id` erhalten eine neue, stabile UUID (`diary_<uuid>`).
- Fälle ohne `originalAmount` erhalten diesen Wert aus dem alten Feldnamen `totalAmount`
  (welches zur Sicherheit zusätzlich erhalten bleibt); fehlende `correctedAmount`,
  `savedAmount`, `resolvedDate`, `invoiceNumber`, `auditedCorrectionAmount` werden auf `null`
  gesetzt.

### 3.2 Schemas & Beispieldaten

**`profile` (ein einzelnes Objekt, kein Array):**
```json
{
  "fullName": "Erika Musterfrau",
  "address": "Teststraße 5, 50667 Köln",
  "insuranceName": "Debeka PKV",
  "insuranceNumber": "V-778899",
  "beihilfeNumber": "B-4711",
  "vaultPin": "",
  "isConfigured": true
}
```

**`diary_entries` (Array unter dem Schlüssel `proofmed_diary`):**
```json
{
  "id": "diary_a577a48f-c918-48f9-a086-fdda72968c7f",
  "date": "2026-08-26",
  "practice": "MVZ Philippstor Düren",
  "arrival": "09:15",
  "departure": "09:52",
  "durationMin": 37,
  "logType": "GPS_LIVE",
  "lat": "50.9375",
  "lng": "6.9603",
  "accuracy": 12,
  "proofHash": "09bc52639cd4c40b46f8d2ce8f6b9f6677ac29f9406706caaf925848bb5357ce",
  "archived": false
}
```
*(`lat`/`lng`/`accuracy` nur bei `logType: "GPS_LIVE"`; bei manuellen Einträgen entfallen sie.)*

**`cases` (Array unter dem Schlüssel `proofmed_cases`):**
```json
{
  "id": "case_9bb6bed3-dc8c-4b3d-b24d-879707e40880",
  "invoiceNumber": null,
  "invoiceDate": "2026-08-26",
  "doctorName": "MVZ Philippstor Düren",
  "originalAmount": 30.82,
  "correctedAmount": 18.50,
  "savedAmount": 12.32,
  "status": "RESOLVED",
  "objectionDate": "2026-08-26",
  "resolvedDate": "2026-08-26",
  "sha256Hash": "09bc52639cd4c40b46f8d2ce8f6b9f6677ac29f9406706caaf925848bb5357ce",
  "diaryEntryId": "diary_a577a48f-c918-48f9-a086-fdda72968c7f",
  "receiptDataUrl": "data:image/jpeg;base64,…",
  "auditedCorrectionAmount": 30.82
}
```
`status` ist eine von drei Konstanten: `FROZEN` (Zahlung gestoppt, Einwand versendet),
`WAITING_CORRECTION` (im Datenmodell vorgesehen, aktuell aber von keiner UI-Aktion automatisch
ausgelöst), `RESOLVED` (korrigierter Betrag bestätigt).

> **`audit_history`:** Der Auftrag nennt zusätzlich ein Schema `audit_history`. Im aktuellen
> Code existiert **kein** separat persistierter Prüfverlauf – jedes Audit-Ergebnis lebt nur
> als flüchtiger In-Memory-Zustand (`lastAuditData`) für die Dauer der aktuellen Sitzung und
> wird erst beim Versenden eines Einwands dauerhaft (als `cases`-Eintrag, s.o.) gespeichert.
> Eine chronologische Historie **aller** durchgeführten Prüfungen (auch ohne Einwand) ist
> derzeit nicht implementiert.

### 3.3 Backend-Datenmodell (nur für Cloud-Backup aktiv genutzt)

Das FastAPI-Backend (`app/models/`) definiert per SQLAlchemy u.a.:

- **`EncryptedBackup`** (`app/models/backup.py`) – die einzige vom Frontend tatsächlich
  genutzte Tabelle: `user_id_hash` (Primärschlüssel/Suchindex), `ciphertext_base64`,
  `iv_base64`, `salt_base64`, `updated_at`. Enthält ausschließlich AES-256-GCM-Chiffretext,
  niemals Klartext oder Schlüsselmaterial (Zero-Knowledge).
- **`GOAZiffer`** (`app/models/goa.py`) und **`Claim`** (`app/models/claim.py`) – Tabellen des
  separaten, aktuell nicht angebundenen Server-Audit-Regelwerks (siehe Abschnitt 1.4).

### 3.4 Kryptografischer Integritäts-Nachweis (SHA-256)

Zwei unterschiedliche, aber verwandte Hash-Arten kommen zum Einsatz (beide via
`window.crypto.subtle.digest("SHA-256", …)`):

1. **Tagebuch-Zeitstempel-Hash (`proofHash`):** SHA-256 über den zusammengesetzten String
   `"{date}|{arrival}|{departure}|{practice}|{durationMin}"`. Dient als manipulationssicherer
   Nachweis, dass ein Praxisbesuch mit exakt diesen Eckdaten erfasst wurde, bevor eine Rechnung
   dazu vorlag.
2. **Fall-/Dokumenten-Integritätsstempel (`sha256Hash` im Fall bzw. der Stempel im PDF-Footer):**
   Bevorzugt wird der bereits vorhandene `proofHash` des verknüpften Tagebucheintrags
   übernommen (stärkster Nachweis: koppelt den Fall an den unabhängigen Zeitstempel). Existiert
   kein verknüpfter Tagebucheintrag, wird stattdessen ein SHA-256-Hash über den
   JSON-serialisierten Fallinhalt (Praxis, Datum, Betrag, Ziffern, Fehlermeldungen,
   Einwandtext) gebildet. Dieser Hash erscheint sowohl im UI (Fall-Karte, Geofence-Box) als
   auch als eigener, monospace formatierter "Dokumenten-Integritätsstempel" am Ende jedes
   generierten PDFs.

Für das optionale Cloud-Backup wird zusätzlich per PBKDF2 (100.000 Iterationen, SHA-256) aus
der Backup-PIN ein AES-256-GCM-Schlüssel abgeleitet (16 Byte Zufalls-Salt, 12 Byte
Zufalls-IV je Verschlüsselungsvorgang) sowie ein separater `user_id_hash =
SHA-256(pin + statisches_Salt)` als serverseitiger Suchschlüssel gebildet.

---

## 4. Test- & Verifikations-Leitfaden

> **Hinweis zur Ist-Situation:** Im Repository ist **kein** `npm test`-Skript hinterlegt
> (`package.json` enthält ausschließlich `cap:sync`, `cap:build`, `cap:open:android`,
> `cap:open:ios`). Für das Python-Backend existiert ein einzelnes manuelles Testskript
> (`test_audit_api.py`, per `python test_audit_api.py` bzw. gegen einen laufenden Uvicorn-
> Server auszuführen), aber ebenfalls keine committete `pytest`-Suite. Der folgende Abschnitt
> beschreibt daher die **tatsächlich praktizierte** Verifikationsmethodik sowie eine konkrete
> Anleitung, wie neue Regressionstests reproduzierbar aufgesetzt werden können.

### 4.1 Testmatrix

| Ebene | Werkzeug | Was wird geprüft |
|---|---|---|
| **Lokaler Desktop-Browser** | Statischer HTTP-Server über `app/static/` (siehe unten) | Voller Funktionsumfang: OCR, Audit-Engine, PDF-Erzeugung, Case-Lifecycle, Dossier-KPIs |
| **Mobiler Browser** | Gleicher Server, Chrome/Safari auf echtem Gerät oder DevTools-Device-Emulation | Touch-Bedienung, Datei-/Kamera-Dialog, Responsive-Layout |
| **Android-APK** | Android Studio Emulator oder physisches Gerät | Native SQLite-Persistenz, native Datei-Auswahl (Kamera/Galerie/Dateien), GPS-Berechtigung, Capacitor-Bridge |
| **Backend (optional)** | `uvicorn app.main:app --reload`, danach `/health`, `/api/docs` | Nur relevant für Cloud-Backup-Feature und das separate (ungenutzte) Claims-API |

**Lokalen Static-Server starten** (für Desktop-/Mobile-Browser-Tests, keine Backend-Abhängigkeit
nötig, da die App vollständig clientseitig läuft):
```bash
python -m http.server 8123 --directory app/static
# danach: http://localhost:8123 im Browser öffnen
```
*(Ein passender Eintrag liegt bereits unter `.claude/launch.json` für das integrierte
Preview-Tool vor.)*

**Manueller End-to-End-Testlauf (empfohlener Mindestumfang pro Release):**
1. Profil anlegen (2.1) → Banner verschwindet.
2. Live-Check-in starten/beenden (2.2) → Eintrag mit `proofHash` erscheint im Tagebuch.
3. Testrechnung scannen oder manuell Ziffern wählen, die ein Kombinationsverbot auslösen
   (z.B. GOÄ 1 + GOÄ 3) (2.3) → "Zahlung gestoppt"-Karte erscheint.
4. "Kombi-PDF teilen" auslösen (2.4) → PDF öffnen/speichern, Logo/Hash-Chip/Anlage prüfen;
   im Dossier-Tab erscheint ein neuer Fall mit Status `FROZEN`.
5. Fall "Als korrigiert markieren" (2.5), abweichenden Betrag eingeben → KPI-Leiste,
   Fall-Karte und Tagebuch-Badge müssen synchron auf `RESOLVED` wechseln.
6. Dossier-PDF drucken (2.6) → Briefkopf, Patientendaten, KPI-Karten und Tabellenzeile prüfen.

### 4.2 Automatisierte Regressionstests (Node-basiert)

Für die JavaScript-Logik (Storage, Audit-Engine, PDF-Generatoren, Mailto-Encoder) hat sich in
der bisherigen Entwicklung folgendes Muster bewährt, das sich als committete Test-Suite
nachrüsten lässt:

1. Die relevanten Funktionen werden per Regex/Klammer-Balancing direkt aus
   `app/static/index.html` extrahiert (kein Duplikat-/Abschreibe-Code) und via Node's
   `vm`-Modul in einer Sandbox mit gemockten Browser-Globals (`localStorage`, `document`,
   `window.location`, `fetch`, `crypto`) ausgeführt.
2. Für PDF-Tests wird die echte `jspdf`-Bibliothek (`npm install jspdf@2.5.1` in einem
   Testverzeichnis) gegen den extrahierten Code laufen gelassen – so werden reale
   jsPDF-API-Fehler (falsche Methodennamen, falsche Bild-Formate) erkannt, nicht nur
   Syntaxfehler.
3. Jeder Testlauf endet mit einer Zusammenfassung `"<n> passed, <m> failed"` und
   `process.exit(1)` bei Fehlern (CI-tauglich).

**Empfehlung:** Dieses Muster in ein `tests/`-Verzeichnis überführen und ein echtes
`"test": "node tests/run-all.js"`-Skript in `package.json` ergänzen, damit `npm test`
reproduzierbar für alle Mitwirkenden funktioniert.

### 4.3 Backend-Test (optional, nur Cloud-Backup/Claims-API)

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
```
- Health-Check: `GET http://127.0.0.1:8000/health` → `{"status":"ok","project":"ProofMed"}`
- Interaktive API-Doku: `http://127.0.0.1:8000/api/docs`
- Manuelles Test-Skript: `python test_audit_api.py` (prüft die separate, aktuell ungenutzte
  Claims-Validierungs-Route – siehe Abschnitt 1.4).

---

## 5. Build, Deployment & APK-Wartung

### 5.1 Render Web-Deployment (Backend)

Der GitHub-Repository-Name ist **`verimed-api`** (`VeriMedApp/verimed-api`), der auf Render
konfigurierte Service-Name gemäß `render.yaml` lautet **`verimed-backend`**.

**Deployment per Blueprint (empfohlen):**
1. Repository nach GitHub pushen (bereits eingerichtet: `origin` zeigt auf
   `https://github.com/VeriMedApp/verimed-api.git`).
2. Auf [dashboard.render.com](https://dashboard.render.com): **New +** → **Blueprint** →
   Repo `verimed-api` auswählen. Render erkennt `render.yaml` automatisch.
3. `render.yaml` konfiguriert einen **Docker-Web-Service** (`env: docker`,
   `dockerfilePath: ./Dockerfile`), Plan `free`, Health-Check-Pfad `/health`.
4. Folgende Umgebungsvariablen werden automatisch gesetzt (siehe `render.yaml`):
   `PORT=10000`, `DATABASE_URL=sqlite+aiosqlite:///./verimed.db`, `DEBUG=false`,
   `LOG_LEVEL=INFO`, `TIME_TOLERANCE_MINUTES=10`, `ENCRYPTION_KEY` (automatisch generiert),
   `ALLOWED_ORIGINS=*`.
5. Deploy abwarten (ca. 3–5 Minuten, das Docker-Image installiert zusätzlich
   `tesseract-ocr` + `tesseract-ocr-deu` für die serverseitige OCR-Route).

> ⚠️ **Wichtiger Hinweis aus `render.yaml`:** Die Standardkonfiguration nutzt SQLite **in
> einer lokalen Datei innerhalb des Containers**. Render-Webdienste haben **kein
> persistentes Dateisystem** ohne explizit gemounteten "Disk" – alle Daten (inkl. der
> verschlüsselten E2EE-Backups!) gehen bei jedem Deploy, Neustart oder Scaling-Event
> **verloren**. Für produktiven Einsatz entweder einen Disk-Mount ergänzen oder auf eine
> verwaltete PostgreSQL-Datenbank umstellen (`DATABASE_URL` auf `postgresql+asyncpg://…`
   setzen; die App konvertiert eine von Render gelieferte `postgresql://`-URL automatisch).

**Nach dem Deploy testen:**
```
GET  https://<service>.onrender.com/health
GET  https://<service>.onrender.com/           (liefert die Frontend-App aus)
POST https://<service>.onrender.com/api/v1/backup/save
```

**Freie-Plan-Hinweise:** Der Web-Service schläft nach ca. 15 Minuten Inaktivität; der erste
Request danach dauert 30–60 Sekunden (Cold Start).

*(Für weitere Detail-Optionen – manuelles Setup ohne Blueprint, SMTP-Konfiguration für
`/api/v1/send-objection`, Fehlerbehebung – siehe die bestehende `DEPLOY.md`. Dort referenzierte
PostgreSQL-Blueprint- und "Lovable"-Frontend-Hinweise stammen aus einer früheren
Projektphase und sind nicht mehr mit dem aktuellen `render.yaml`/Frontend-Stand deckungsgleich.)*

### 5.2 Android Studio APK-Build

**Voraussetzungen:** Android Studio, JDK, installierte Android SDK/Build-Tools; Node.js für
`npm run cap:sync`. App-ID: `de.proofmed.app`, `versionCode 1`, `versionName "1.0"`.

**Verifizierte Android-Umgebung / Build-Toolchain:**

| Komponente | Wert |
|---|---|
| Betriebssystem | Windows 11 (amd64) |
| JDK | JetBrains Runtime (JBR) / OpenJDK 17.0.14 |
| JDK-Pfad | `C:\Users\MoneyMachine\.jdks\jbr-17.0.14` |
| Gradle | 8.2.1 |
| Verifikation | `.\gradlew assembleDebug` erfolgreich abgeschlossen |

Setup (PowerShell), falls `JAVA_HOME` nicht bereits auf ein kompatibles JDK zeigt:

```powershell
$env:JAVA_HOME="C:\Users\MoneyMachine\.jdks\jbr-17.0.14"
$env:Path="$env:JAVA_HOME\bin;$env:Path"

cd android
.\gradlew assembleDebug
```

**Schritt-für-Schritt-Ablauf nach Frontend-Änderungen:**

1. **Web-Assets synchronisieren** (kopiert `app/static/` in die nativen Projekte):
   ```bash
   npm run cap:sync
   ```
   Dies führt intern `npx cap copy && npx cap sync` aus. Auf Windows schlägt der
   `pod install`-Schritt für iOS regelmäßig fehl (`ENOENT … Podfile`), da CocoaPods dort nicht
   verfügbar ist – **das ist erwartet** und betrifft nur die iOS-Abhängigkeitsauflösung, nicht
   den Android-Build; der reine Asset-Kopiervorgang (`android/app/src/main/assets/public/`)
   ist davon nicht betroffen und sollte danach mit `app/static/index.html` byte-identisch sein.
2. **Android Studio öffnen:**
   ```bash
   npm run cap:open:android
   ```
   (öffnet `android/` als Gradle-Projekt).
3. **Clean Project:** Menü *Build → Clean Project* (entfernt alte Build-Artefakte, u.a. den in
   `android/app/build/intermediates/assets/…` zwischengespeicherten Asset-Stand, der sonst
   veraltete Web-Inhalte in die APK einbacken kann).
4. **Gradle-Sync** abwarten (automatisch nach dem Öffnen bzw. über den "Sync Now"-Banner).
5. **Debug-APK bauen:**
   - Über die IDE: *Build → Build Bundle(s) / APK(s) → Build APK(s)*, oder
   - über die Kommandozeile:
     ```bash
     cd android
     ./gradlew assembleDebug
     ```
   Ergebnis: `android/app/build/outputs/apk/debug/app-debug.apk`.
6. **Auf Gerät/Emulator installieren & testen** (siehe Testmatrix, Abschnitt 4.1) – insbesondere
   den nativen Datei-Auswahldialog (Foto/PDF wählen) und GPS-Check-in prüfen.
7. **Release-Build** (signiert, für Play-Store-Upload): *Build → Generate Signed Bundle / APK*,
   Keystore auswählen/anlegen, `assembleRelease` bzw. `bundleRelease` ausführen.

> ✅ **Berechtigungsstatus:** `android/app/src/main/AndroidManifest.xml` deklariert neben
> `android.permission.INTERNET` inzwischen auch die für Geofencing und Rechnungs-Scan
> benötigten Laufzeit-Berechtigungen: `ACCESS_FINE_LOCATION`, `ACCESS_COARSE_LOCATION`
> (Live-GPS-Check-in im Tagebuch), `CAMERA`, `READ_EXTERNAL_STORAGE` (mit
> `android:maxSdkVersion="32"`) und `READ_MEDIA_IMAGES` (native Datei-/Kamera-Auswahl beim
> Rechnungs-Scan). Der Gradle-Build (`.\gradlew assembleDebug`, s.o.) wurde nach Ergänzung
> dieser Berechtigungen erfolgreich verifiziert.

**iOS-Analogon:** `npm run cap:open:ios` öffnet `ios/App/App.xcworkspace` in Xcode (setzt eine
funktionierende CocoaPods-Installation auf macOS voraus – auf Windows nicht durchführbar).

---

## 6. Bekannte Einschränkungen & offene Punkte

Diese Liste dokumentiert – im Sinne der Transparenz – Sachverhalte, die beim Erstellen dieses
Handbuchs im Code auffielen und für künftige Weiterentwicklung relevant sein können:

1. **Zwei getrennte GOÄ-Engines** (Client-JS vs. Server-Python) – siehe 1.4. Änderungen an
   Sätzen/Regeln müssen aktuell in beiden Implementierungen unabhängig gepflegt werden, falls
   beide je in Produktion genutzt werden.
2. **Kein automatisiertes, committetes Testskript** (`npm test` existiert nicht) – siehe
   Abschnitt 4.
3. **Kein persistenter Audit-Verlauf (`audit_history`)** über den Case-Datensatz hinaus – jede
   Prüfung ohne anschließenden Einwand-Versand bleibt flüchtig.
4. **Zwei unabhängige PIN-Konzepte:** die Profil-"Tresor-PIN" (aktuell ohne
   Zugriffskontroll-Funktion) und die Cloud-Backup-PIN (nie gespeichert, nur zur
   Schlüsselableitung) sind bewusst getrennt, aber für Endnutzer:innen ggf.
   erklärungsbedürftig.
5. **Render-Standardkonfiguration nutzt ephemeres SQLite** – vor produktivem Einsatz des
   Cloud-Backups zwingend auf persistenten Speicher (Disk-Mount oder PostgreSQL) umstellen.
6. ~~Android-Manifest ohne explizite Standort-/Kamera-Berechtigungen~~ – **behoben.** Das
   Manifest deklariert inzwischen `ACCESS_FINE_LOCATION`, `ACCESS_COARSE_LOCATION`, `CAMERA`,
   `READ_EXTERNAL_STORAGE` und `READ_MEDIA_IMAGES`; der Gradle-Build wurde damit erfolgreich
   verifiziert (siehe 5.2).
7. **`WAITING_CORRECTION`-Status** ist im Datenmodell vorgesehen, wird aber von keiner
   aktuellen UI-Aktion automatisch gesetzt (nur `FROZEN` und `RESOLVED` sind aktuell erreichbar).

---

*Dieses Dokument wurde durch Analyse des tatsächlichen, aktuellen Codestands erstellt
(`app/static/index.html`, `index.html`, `app/`, `android/`, Konfigurationsdateien im
Projekt-Root). Bei künftigen Funktionsänderungen sollte es entsprechend aktualisiert werden.*
