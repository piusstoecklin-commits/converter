# Dokumentenkonverter

Ein selbst betriebener Dateikonverter für Behörden. Alle Dateien werden
ausschließlich auf dem eigenen Server verarbeitet — es besteht kein Bedarf,
Unterlagen an einen Online-Dienst zu übermitteln.

**155 Eingabeformate, 123 Zielformate, 24 Konvertierungsmodule.**
Ohne Anmeldung, ohne Benutzerkonten, ohne Datenbank, ohne Verbindung nach außen.

---

## Inhalt

- [Schnellstart](#schnellstart)
- [Unterstützte Formate](#unterstützte-formate)
- [Funktionen](#funktionen)
- [Datenschutz und Sicherheit](#datenschutz-und-sicherheit)
- [Konfiguration](#konfiguration)
- [Betrieb](#betrieb)
- [Aufbau der Anwendung](#aufbau-der-anwendung)
- [Schnittstelle](#schnittstelle)
- [Tests](#tests)
- [Häufige Fragen](#häufige-fragen)

---

## Schnellstart

```bash
git clone <repository-adresse> konverter
cd konverter
docker compose up -d --build
```

Der Dienst lauscht anschließend auf `127.0.0.1:8080`. Für einen ersten Test
ohne Reverse Proxy in `docker-compose.yml` die Portzuweisung auf
`"8080:8080"` ändern.

Für den regulären Betrieb wird ein Reverse Proxy mit TLS und einer
Netzbeschränkung vorgeschaltet — ein vollständiges Beispiel liegt in
[`deploy/nginx.conf`](deploy/nginx.conf).

Prüfung, ob der Dienst arbeitet:

```bash
curl -s http://127.0.0.1:8080/api/health
# {"status":"ok","version":"1.0.0","auftraege":0,"laufend":0,"wartend":0,"arbeiter":4}
```

---

## Unterstützte Formate

| Bereich | Formate |
|---|---|
| **Dokumente** (16) | PDF, PDF/A, DOCX, DOC, DOCM, DOT, DOTX, ODT, OTT, FODT, SXW, RTF, WPD, WPS, LWP, UOT, HWP, Pages |
| **Tabellen** (14) | XLSX, XLS, XLSM, XLT, XLTX, ODS, OTS, FODS, SXC, CSV, TSV, DIF, SLK, DBF, Numbers |
| **Präsentationen** (11) | PPTX, PPT, PPTM, PPS, PPSX, POT, POTX, ODP, OTP, FODP, SXI, Keynote |
| **Zeichnungen** (14) | SVG, ODG, OTG, FODG, SXD, VSD, VSDX, CDR, PUB, WMF, EMF, EPS, PS, DXF |
| **Text und Markup** (12) | TXT, Markdown, HTML, reStructuredText, AsciiDoc, Org, LaTeX, Typst, Textile, MediaWiki, DokuWiki, DocBook, OPML, Jupyter, Manpage |
| **E-Books** (2) | EPUB, FB2 |
| **E-Mail** (3) | EML, MSG (Outlook), MBOX |
| **Bilder** (28) | JPEG, PNG, GIF, BMP, TIFF, WebP, AVIF, JPEG XL, HEIC, ICO, JPEG 2000, PSD, XCF, TGA, PCX, PPM, PGM, PBM, DDS, EXR, HDR, XPM sowie Kamerarohdaten (CR2, NEF, ARW, DNG, ORF, RAF) |
| **Video** (15) | MP4, MKV, WebM, MOV, AVI, WMV, FLV, MPEG, M4V, 3GP, OGV, TS, MTS, VOB, ASF |
| **Audio** (16) | MP3, WAV, FLAC, OGG, Opus, M4A, AAC, WMA, AIFF, AMR, AC3, MKA, AU, CAF, APE, WavPack |
| **Untertitel** (3) | SRT, WebVTT, ASS/SSA |
| **Daten** (6) | JSON, XML, YAML, TOML, INI, JSON Lines, SQL |
| **Archive** (11) | ZIP, TAR, TAR.GZ, TAR.BZ2, TAR.XZ, 7Z, RAR, GZ, BZ2, XZ, ISO |
| **Schriften** (4) | TTF, OTF, WOFF, WOFF2 |

Die vollständige, jeweils aktuelle Liste zeigt die Oberfläche unter
„Unterstützte Formate“ beziehungsweise `GET /api/info`.

### Wie die vielen Formatkombinationen entstehen

Die Konvertierer bilden einen **gerichteten Graphen**: Formate sind Knoten,
Umwandlungen sind Kanten. Beim Auswählen einer Datei sucht der Dienst mit dem
Dijkstra-Verfahren den günstigsten Weg zum gewünschten Ziel — bei Bedarf über
Zwischenschritte.

```
Outlook-Nachricht nach Archiv-PDF:   MSG → HTML → PDF → PDF/A
Eingescanntes PDF nach Word:         PDF → DOCX      (pdf2docx, Layout bleibt)
Markdown nach Word:                  MD → HTML → DOCX
```

Jede Kante trägt Kosten, die den Qualitätsverlust abbilden. Deshalb läuft
`DOCX → PDF` direkt über LibreOffice und nicht über einen Umweg. Mehrstufige
Wege werden in der Oberfläche gekennzeichnet.

Fachlich unsinnige Ketten sind ausgeschlossen: über ein Standbild ließe sich
formal ein Weg von `MP4` nach `DOCX` konstruieren — eine Domänenregel
verhindert das (siehe `app/registry.py`).

---

## Funktionen

**Stapelverarbeitung.** Bis zu 50 Dateien je Auftrag. Bei gemischten Dateitypen
zeigt die Oberfläche nur Zielformate an, die für **alle** ausgewählten Dateien
funktionieren. Mehrere Ergebnisse werden als ZIP-Archiv gebündelt.

**Texterkennung (OCR).** Eingescannte Dokumente werden durchsuchbar. Verfügbare
Sprachen: Deutsch, Englisch, Französisch, Italienisch, Spanisch, Türkisch,
Russisch. Die Erkennung läuft bei PDF-Quellen **vor** der Umwandlung, damit auch
`PDF → Word` und `PDF → Text` bei Scans ein Ergebnis liefern.

**PDF/A für die Langzeitarchivierung.** Erzeugt archivtaugliche Dokumente nach
PDF/A-2b, wie sie für die Aktenführung benötigt werden.

**Zusammenführen.** Mehrere Dateien lassen sich zu einem einzigen PDF
verbinden — etwa Scan, Foto und Gebührentabelle zu einer geschlossenen Akte.

**PDF verkleinern.** Vier Stufen von Bildschirmqualität (72 dpi) bis
Druckvorstufe. Bringt die Komprimierung keine Verkleinerung, wird das Original
ausgeliefert und ein Hinweis angezeigt.

**Metadaten entfernen.** Auf Wunsch werden EXIF-Daten wie Aufnahmeort und
Kameramodell aus Bildern gelöscht.

**Verständliche Fehlermeldungen.** Statt eines Fehlercodes erscheint der Grund
samt Handlungsempfehlung, zum Beispiel: *„Dieses PDF enthält keine Textebene.
Es handelt sich vermutlich um einen Scan. Bitte die Einstellung ‚Texterkennung
(OCR) durchführen‘ aktivieren und erneut starten.“*

Der Ausfall einer Datei bricht den Stapel nicht ab — die übrigen werden
umgewandelt und der Fehler wird je Datei ausgewiesen.

---

## Datenschutz und Sicherheit

### Verarbeitung der Dateien

| Zeitpunkt | Was geschieht |
|---|---|
| Beim Hochladen | Ablage in einem Auftragsordner mit zufälliger, nicht erratbarer Kennung (192 Bit) |
| Nach der Umwandlung | Die **Originaldateien werden unmittelbar gelöscht** |
| Nach Ablauf der Frist | Der gesamte Auftragsordner wird gelöscht (Standard: 30 Minuten) |
| Auf Knopfdruck | Die Schaltfläche „Dateien jetzt vom Server löschen“ entfernt alles sofort |
| Beim Neustart | Reste eines früheren Laufs werden beim Start beseitigt |

Es gibt **keine Datenbank und keine Protokollierung von Dateiinhalten**. Aufträge
existieren nur im Arbeitsspeicher und auf der Platte des Servers. Mit
`SHRED_FILES=true` werden Dateiinhalte vor dem Löschen überschrieben.

Für besonders schutzbedürftige Unterlagen kann das Arbeitsverzeichnis als
`tmpfs` eingebunden werden — dann berührt kein Inhalt jemals die Festplatte
(Vorlage in `docker-compose.yml`).

### Zugangsschutz ohne Anmeldung

Der Dienst kennt bewusst keine Benutzerkonten. Der Zugangsschutz liegt damit
im Netz: Der Reverse Proxy beschränkt den Zugriff auf das Behördennetz
(`allow`/`deny` in `deploy/nginx.conf`). **Der Dienst darf nicht ungeschützt
aus dem Internet erreichbar sein.**

Ergänzend greift eine IP-bezogene Lastbegrenzung (Standard: 60 Aufträge je
10 Minuten) und eine Obergrenze gleichzeitig aktiver Aufträge.

### Härtung der Verarbeitung

Konvertierungsprogramme sind ein beliebtes Angriffsziel, weil sie fremde
Dateien auswerten. Folgende Maßnahmen sind umgesetzt:

- **Keine Shell.** Externe Programme werden ausschließlich mit fester
  Argumentliste aufgerufen. Ein Dateiname kann keinen Befehl einschleusen.
- **Namensbereinigung.** Hochgeladene Namen werden auf einen sicheren
  Dateinamen ohne Pfadanteile abgebildet — Windows- und Unix-Pfade,
  Steuerzeichen und reservierte Gerätenamen eingeschlossen.
- **Zeit- und Größengrenzen** je Schritt, je Auftrag und je Datei.
- **LibreOffice** startet mit einem frischen, leeren Benutzerprofil, in dem die
  Makroausführung abgeschaltet ist.
- **Pandoc** läuft im Sandbox-Modus (`--sandbox`) und hat damit keinen Zugriff
  auf das Dateisystem. Ein präpariertes Dokument kann so keine Serverdatei über
  einen Bild- oder Include-Verweis in das Ergebnis einbetten. Zielformate, die
  Pandocs eigene Vorlagendateien benötigen (DOCX, ODT, EPUB), werden deshalb
  über HTML und LibreOffice erzeugt statt die Sandbox aufzugeben.
- **ImageMagick** erhält eine eigene `policy.xml`: keine Netzwerkzugriffe,
  keine skriptfähigen Formate (MSL, MVG), feste Ressourcengrenzen.
  Für die häufigen Rasterformate wird ohnehin Pillow benutzt — schneller und
  mit deutlich kleinerer Angriffsfläche.
- **Ghostscript** läuft mit `-dSAFER` und `-dPARANOIDSAFER`.
- **FFmpeg** darf nur lokale Dateien öffnen (`-protocol_whitelist file,crypto,data`).
  Eine präparierte Playlist kann keine Adressen im internen Netz abrufen.
- **XML** wird mit `defusedxml` gelesen (Schutz vor Entity-Expansion und
  externen Referenzen).
- **Archive** werden Eintrag für Eintrag geprüft: Pfade, die aus dem
  Zielordner herausführen („Zip Slip“), symbolische Verweise und
  Dekompressionsbomben werden abgewiesen.
- **CSV nach Excel** entschärft Zellinhalte, die mit `=`, `+`, `-` oder `@`
  beginnen, damit sie in Excel nicht als Formel ausgeführt werden.
- **Optionen** aus dem Formular werden gegen eine Positivliste geprüft und auf
  Wertebereiche begrenzt.

### Härtung des Containers

Der Container läuft **ohne Root-Rechte** (UID 10001), mit
schreibgeschütztem Dateisystem, ohne zusätzliche Capabilities und mit
`no-new-privileges`. Beschreibbar sind nur das Arbeitsverzeichnis und zwei
`tmpfs`-Bereiche.

### Oberfläche

Die Weboberfläche lädt **nichts aus dem Internet nach** — kein CDN, keine
Schriften von fremden Servern, keine Fremdbibliotheken. Eine strenge
Content-Security-Policy hält das durch. Ergänzend sind gesetzt:
`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
`Referrer-Policy: no-referrer`, `Cache-Control: no-store`. Die interaktive
API-Dokumentation ist abgeschaltet.

---

## Konfiguration

Alle Einstellungen erfolgen über Umgebungsvariablen in `docker-compose.yml`.

### Beschriftung

| Variable | Standard | Bedeutung |
|---|---|---|
| `APP_NAME` | `Dokumentenkonverter` | Titel in der Oberfläche |
| `ORGANISATION` | `Landratsamt` | Behördenname im Kopfbereich |
| `FOOTER_NOTE` | — | Freitext im Fußbereich, z. B. Ansprechpartner der IT |

### Grenzwerte

| Variable | Standard | Bedeutung |
|---|---|---|
| `MAX_UPLOAD_MB` | `512` | Maximale Größe je Datei |
| `MAX_FILES_PER_JOB` | `50` | Maximale Anzahl Dateien je Auftrag |
| `STEP_TIMEOUT` | `900` | Zeitlimit je Konvertierungsschritt (Sekunden) |
| `JOB_TIMEOUT` | `3600` | Zeitlimit je Auftrag (Sekunden) |
| `WORKERS` | Anzahl CPU-Kerne | Parallele Konvertierungen |

### Aufbewahrung

| Variable | Standard | Bedeutung |
|---|---|---|
| `RETENTION_MINUTES` | `30` | Frist, nach der Ergebnisse gelöscht werden |
| `CLEANUP_INTERVAL` | `60` | Intervall des Aufräumdienstes (Sekunden) |
| `SHRED_FILES` | `false` | Inhalte vor dem Löschen überschreiben |

### Missbrauchsschutz

| Variable | Standard | Bedeutung |
|---|---|---|
| `RATE_LIMIT_JOBS` | `60` | Aufträge je Zeitfenster und Aufrufer (`0` = aus) |
| `RATE_LIMIT_WINDOW` | `600` | Zeitfenster in Sekunden |
| `MAX_ACTIVE_JOBS` | `200` | Gleichzeitig aktive Aufträge |
| `TRUST_PROXY` | `false` | `X-Forwarded-For` auswerten — nur mit Reverse Proxy aktivieren |

### Konvertierung

| Variable | Standard | Bedeutung |
|---|---|---|
| `MAX_PATH_LENGTH` | `3` | Maximale Zahl an Zwischenschritten |
| `PANDOC_SANDBOX` | `1` | Pandoc-Sandbox. Abschalten erweitert die Formatvielfalt geringfügig, gibt aber eine Schutzmaßnahme auf |
| `WORK_DIR` | `/data/work` | Arbeitsverzeichnis |

---

## Betrieb

### Dimensionierung

| Nutzung | CPU | RAM | Platte |
|---|---|---|---|
| Kleine Behörde, gelegentlich | 2 Kerne | 4 GB | 20 GB |
| Regelbetrieb (Standard) | 4 Kerne | 8 GB | 50 GB |
| Viele Videos oder OCR | 8 Kerne | 16 GB | 100 GB |

Der Plattenbedarf richtet sich nach `MAX_UPLOAD_MB × MAX_FILES_PER_JOB ×
gleichzeitige Aufträge`. Videokonvertierung und Texterkennung sind
rechenintensiv; das Abbild ist rund 3 GB groß.

### Häufige Handgriffe

```bash
docker compose logs -f konverter        # Protokoll mitlesen
docker compose restart konverter        # Neustart
docker compose up -d --build            # Aktualisieren
docker compose down                     # Anhalten

# Belegung des Arbeitsverzeichnisses
docker compose exec konverter du -sh /data/work

# Betriebszustand
curl -s http://127.0.0.1:8080/api/health
```

### Überwachung

`GET /api/health` liefert Zustand, Version und Auftragszahlen und eignet sich
als Prüfpunkt für die Systemüberwachung. Das Abbild bringt zusätzlich einen
`HEALTHCHECK` mit, den Docker selbst auswertet.

### Betrieb ohne Internetzugang

Zur Laufzeit wird keine Verbindung nach außen benötigt. Für ein
netzgetrenntes Rechenzentrum lässt sich das Abbild auf einem Rechner mit
Internetzugang bauen und übertragen:

```bash
docker build -t dokumentenkonverter:1.0.0 .
docker save dokumentenkonverter:1.0.0 | gzip > konverter.tar.gz
# Datei übertragen, dann auf dem Zielsystem:
gunzip -c konverter.tar.gz | docker load
```

---

## Aufbau der Anwendung

```
app/
├── config.py          Einstellungen aus Umgebungsvariablen
├── formats.py         Katalog aller 163 Formate (Endung, Name, MIME, Kategorie)
├── registry.py        Konvertierungsgraph und Wegesuche (Dijkstra)
├── pipeline.py        Ausführung eines Weges, Vor- und Nachbearbeitung
├── jobs.py            Auftragsverwaltung, Worker-Pool, Aufräumdienst
├── security.py        Namensbereinigung, Lastbegrenzung, Kopfzeilen
├── main.py            HTTP-Schnittstelle (FastAPI)
├── engines/
│   ├── base.py        Basisklasse, Prozessaufruf ohne Shell
│   ├── office.py      LibreOffice: Writer, Calc, Impress, Draw
│   ├── markup.py      Pandoc
│   ├── images.py      Pillow, ImageMagick, LibRaw
│   ├── av.py          FFmpeg: Video, Audio, Untertitel, Standbild, GIF
│   ├── pdftools.py    Ghostscript, Poppler, pdf2docx
│   ├── data.py        Tabellen und Strukturdaten
│   ├── mail.py        EML, MSG, MBOX
│   ├── archives.py    Archive umpacken
│   └── fonts.py       Schriften
└── static/            Oberfläche (HTML, CSS, JavaScript ohne Fremdbibliotheken)
```

### Eine neue Engine hinzufügen

Es genügt, `sources`, `targets` und `convert()` zu beschreiben — die Wegesuche
nimmt die neuen Kanten selbständig auf, auch für mehrstufige Wege:

```python
class MeineEngine(Engine):
    name = "meine-engine"
    label = "Mein Konverter"
    requires = "mein-programm"     # Engine entfällt, wenn das Programm fehlt
    cost = 10                      # niedriger = verlustärmer
    source_exts = ("abc",)
    target_exts = ("pdf",)

    def convert(self, src, dst, src_ext, dst_ext, ctx):
        run_command(["mein-programm", "-o", str(dst), str(src)],
                    timeout=ctx.timeout, label="Mein Konverter")
        return dst
```

Anschließend in `app/registry.py` das Modul in `_MODULES` aufnehmen. Fehlt das
benötigte Programm, entfallen lediglich die Wege dieser Engine — der Dienst
läuft weiter.

---

## Schnittstelle

Die Oberfläche benutzt dieselbe Schnittstelle; sie lässt sich für
Fachverfahren direkt ansprechen.

| Methode | Pfad | Zweck |
|---|---|---|
| `GET` | `/api/info` | Formate, Kategorien, Grenzwerte |
| `GET` | `/api/targets?ext=docx` | Zielformate; mehrere Endungen mit Komma ergeben die Schnittmenge |
| `POST` | `/api/jobs` | Auftrag anlegen (multipart: `files`, `target`, `options`, `merge`) |
| `GET` | `/api/jobs/{id}` | Status und Ergebnisse |
| `GET` | `/api/jobs/{id}/dateien/{dateiId}` | Einzelnes Ergebnis herunterladen |
| `GET` | `/api/jobs/{id}/paket` | ZIP-Archiv oder zusammengeführtes PDF |
| `DELETE` | `/api/jobs/{id}` | Auftrag samt Dateien sofort löschen |
| `GET` | `/api/health` | Betriebszustand |

Beispiel — eingescanntes PDF mit Texterkennung nach Word:

```bash
AUFTRAG=$(curl -s -F "files=@scan.pdf" -F "target=docx" \
  -F 'options={"ocr":true,"ocr_language":"deu"}' \
  http://127.0.0.1:8080/api/jobs | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")

curl -s "http://127.0.0.1:8080/api/jobs/$AUFTRAG"          # bis "status":"fertig"
curl -sO -J "http://127.0.0.1:8080/api/jobs/$AUFTRAG/dateien/000"
```

---

## Tests

```bash
pip install -r requirements.txt pytest
python -m pytest tests/ -v
```

Die Testreihe deckt ab: Formatkatalog, Wegesuche einschließlich der
Domänenregel, Namensbereinigung, Lastbegrenzung, die Daten-Engines, die
Archivschutzmaßnahmen (Pfadausbruch, Dekompressionsbombe, symbolische
Verweise) sowie die HTTP-Schnittstelle vom Hochladen bis zum Löschen.

Die Tests laufen auch ohne die externen Programme: Fehlt LibreOffice oder
FFmpeg, entfallen lediglich deren Wege. Für einen Durchlauf mit allen Engines:

```bash
docker compose exec konverter python -m pytest /app/tests -v
```

---

## Häufige Fragen

**Warum gibt es keine Anmeldung?**
Weil sie in einem abgeschotteten Behördennetz keinen zusätzlichen Schutz
bringt, aber Betrieb und Nutzung erschwert. Der Zugangsschutz liegt im Netz
(Reverse Proxy, siehe oben). Wird der Dienst darüber hinaus benötigt, lässt
sich am Reverse Proxy eine Authentifizierung ergänzen, ohne die Anwendung zu
ändern.

**Verlassen Dateien jemals den Server?**
Nein. Alle Konvertierungsprogramme sind im Abbild enthalten und arbeiten
lokal. Netzwerkzugriffe der Werkzeuge sind zusätzlich unterbunden (Pandoc
Sandbox, ImageMagick-Policy, FFmpeg-Protokollliste).

**Wie genau ist „PDF nach Word“?**
Es ist eine Nachbildung des Layouts, keine Rückgewinnung des Originals. Für
einfache Textdokumente ist das Ergebnis gut, bei komplexen Layouts sollte es
geprüft werden — die Oberfläche weist darauf hin.

**Wieso schlägt die Umwandlung eines Scans nach Text fehl?**
Ein Scan enthält Bildpunkte, keinen Text. Mit der Einstellung „Texterkennung
(OCR) durchführen“ wird die Textebene erzeugt und die Umwandlung gelingt.

**Warum ist mein Video nicht in einem PDF darstellbar?**
Solche Wege sind absichtlich ausgeschlossen. Erhalten bleibt, was fachlich
Sinn ergibt: ein Standbild oder ein animiertes GIF aus dem Video.

**Können passwortgeschützte Dateien umgewandelt werden?**
Nein. Verschlüsselte PDF- oder Office-Dateien müssen vorher entsperrt werden.

**Was passiert bei einem Neustart?**
Laufende Aufträge gehen verloren und Reste im Arbeitsverzeichnis werden
gelöscht. Da Aufträge nur Minuten leben, ist das unkritisch.
