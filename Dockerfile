# =====================================================================
# Dokumentenkonverter - Betrieb auf eigener Infrastruktur
#
# Das Abbild enthaelt saemtliche Konvertierungsprogramme. Zur Laufzeit
# wird keine Verbindung ins Internet benoetigt.
# =====================================================================

FROM python:3.12-slim-trixie AS basis

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------------------
# Systemprogramme
#
# Die Installation ist in benannte Gruppen unterteilt. Schlaegt etwas fehl,
# nennt die letzte "### Installiere Gruppe"-Zeile im Protokoll die betroffene
# Gruppe. Das ist bei rund 35 Paketen deutlich hilfreicher als eine einzelne
# Sammelmeldung ueber die gesamte Liste.
#
# Die apt-Voreinstellungen fangen die haeufigsten Abbruchursachen ab:
# kurze Netzaussetzer (Retries) und eine unvollstaendige IPv6-Strecke,
# wie sie hinter Behoerden-Firewalls oft vorliegt (ForceIPv4).
#
# Schriften: Liberation sowie Carlito und Caladea sind metrisch kompatibel
# zu Arial, Times, Calibri und Cambria. Ohne sie verschieben sich
# Seitenumbrueche in Word-Dokumenten.
# ---------------------------------------------------------------------
RUN set -eux; \
    printf 'Acquire::Retries "5";\nAcquire::http::Timeout "60";\nAcquire::ForceIPv4 "true";\n' \
        > /etc/apt/apt.conf.d/99konverter; \
    apt-get update; \
    gruppe() { name="$1"; shift; echo "### Installiere Gruppe: ${name}"; \
               apt-get install --no-install-recommends -y "$@"; }; \
    gruppe "Grundwerkzeuge und Schriften" \
        fontconfig \
        libmagic1 \
        fonts-liberation2 \
        fonts-crosextra-carlito \
        fonts-crosextra-caladea \
        fonts-dejavu-core \
        fonts-noto-core; \
    gruppe "LibreOffice (Office-Dokumente)" \
        libreoffice-core \
        libreoffice-writer \
        libreoffice-calc \
        libreoffice-impress \
        libreoffice-draw \
        libreoffice-nlpsolver \
        default-jre-headless; \
    gruppe "Pandoc (Markup und E-Books)" \
        pandoc; \
    gruppe "Bildverarbeitung" \
        imagemagick \
        libheif1 \
        libraw-bin; \
    gruppe "Video und Audio" \
        ffmpeg; \
    gruppe "PDF-Werkzeuge" \
        ghostscript \
        poppler-utils \
        qpdf \
        pngquant \
        unpaper; \
    gruppe "Texterkennung" \
        tesseract-ocr \
        tesseract-ocr-deu \
        tesseract-ocr-eng \
        tesseract-ocr-fra \
        tesseract-ocr-ita \
        tesseract-ocr-spa \
        tesseract-ocr-tur \
        tesseract-ocr-rus \
        tesseract-ocr-osd; \
    gruppe "Archive" \
        p7zip-full \
        unar; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/* /usr/share/doc /usr/share/man

# ---------------------------------------------------------------------
# ImageMagick absichern: Bildkonvertierung darf weder Netzwerkadressen
# aufloesen noch eingebettete Skripte ausfuehren.
# ---------------------------------------------------------------------
COPY deploy/imagemagick-policy.xml /tmp/policy.xml
RUN for ziel in /etc/ImageMagick-6/policy.xml /etc/ImageMagick-7/policy.xml; do \
        if [ -d "$(dirname "$ziel")" ]; then cp /tmp/policy.xml "$ziel"; fi; \
    done; \
    rm -f /tmp/policy.xml

# ---------------------------------------------------------------------
# Python-Abhaengigkeiten
# ---------------------------------------------------------------------
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# ---------------------------------------------------------------------
# Anwendungsbenutzer ohne besondere Rechte
# ---------------------------------------------------------------------
RUN groupadd --gid 10001 konverter \
    && useradd --uid 10001 --gid 10001 --home-dir /home/konverter \
       --create-home --shell /usr/sbin/nologin konverter \
    && mkdir -p /data/work /home/konverter/.cache \
    && chown -R konverter:konverter /data /home/konverter

WORKDIR /app
COPY --chown=konverter:konverter app/ /app/app/

# Schriftverzeichnis vorbereiten, damit die erste Umwandlung nicht
# unnoetig lange dauert.
RUN fc-cache --force --system-only >/dev/null 2>&1 || true

USER konverter

ENV HOME=/home/konverter \
    WORK_DIR=/data/work \
    XDG_CACHE_HOME=/home/konverter/.cache \
    OMP_THREAD_LIMIT=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=5).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--workers", "1", \
     "--timeout-keep-alive", "65", \
     "--no-server-header", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
