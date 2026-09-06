"""Katalog aller unterstuetzten Dateiformate.

Der Katalog ist die einzige Stelle, an der Endungen, Anzeigenamen und
MIME-Typen gepflegt werden. Die Konvertierungs-Engines verweisen nur noch
auf die hier definierten Kennungen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

# Anzeigenamen und Sortierung der Kategorien in der Oberflaeche.
CATEGORIES: dict[str, str] = {
    "document": "Dokumente",
    "spreadsheet": "Tabellen",
    "presentation": "Praesentationen",
    "drawing": "Zeichnungen",
    "markup": "Text und Markup",
    "ebook": "E-Books",
    "email": "E-Mail",
    "image": "Bilder",
    "video": "Video",
    "audio": "Audio",
    "subtitle": "Untertitel",
    "data": "Daten",
    "archive": "Archive",
    "font": "Schriften",
}

CATEGORY_ORDER: list[str] = list(CATEGORIES)


@dataclass(frozen=True)
class Format:
    ext: str
    label: str
    category: str
    mime: str = "application/octet-stream"
    aliases: tuple[str, ...] = ()
    # Formate, die nur gelesen werden koennen (kein Konvertierungsziel).
    read_only: bool = False
    # Formate, die nur erzeugt werden koennen (kein Eingabeformat).
    write_only: bool = False
    note: str = ""


def _f(
    ext: str,
    label: str,
    category: str,
    mime: str = "application/octet-stream",
    *,
    aliases: Iterable[str] = (),
    read_only: bool = False,
    write_only: bool = False,
    note: str = "",
) -> Format:
    return Format(
        ext=ext,
        label=label,
        category=category,
        mime=mime,
        aliases=tuple(aliases),
        read_only=read_only,
        write_only=write_only,
        note=note,
    )


_ALL: list[Format] = [
    # ------------------------------------------------------------------
    # Dokumente
    # ------------------------------------------------------------------
    _f("pdf", "PDF-Dokument", "document", "application/pdf"),
    _f("pdfa", "PDF/A (Langzeitarchiv)", "document", "application/pdf", write_only=True,
       note="Archivtaugliches PDF nach PDF/A-2b, geeignet fuer die Aktenfuehrung."),
    _f("docx", "Word-Dokument (DOCX)", "document",
       "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    _f("doc", "Word 97-2003 (DOC)", "document", "application/msword"),
    _f("docm", "Word mit Makros (DOCM)", "document", "application/vnd.ms-word.document.macroEnabled.12"),
    _f("dot", "Word-Vorlage (DOT)", "document", "application/msword"),
    _f("dotx", "Word-Vorlage (DOTX)", "document",
       "application/vnd.openxmlformats-officedocument.wordprocessingml.template"),
    _f("odt", "OpenDocument Text (ODT)", "document", "application/vnd.oasis.opendocument.text"),
    _f("ott", "OpenDocument Textvorlage (OTT)", "document",
       "application/vnd.oasis.opendocument.text-template"),
    _f("fodt", "Flat-XML ODF Text (FODT)", "document", "application/vnd.oasis.opendocument.text-flat-xml"),
    _f("sxw", "StarOffice Writer (SXW)", "document", "application/vnd.sun.xml.writer"),
    _f("rtf", "Rich Text Format (RTF)", "document", "application/rtf"),
    _f("wpd", "WordPerfect (WPD)", "document", "application/wordperfect", read_only=True),
    _f("wps", "Microsoft Works (WPS)", "document", "application/vnd.ms-works", read_only=True),
    _f("lwp", "Lotus Word Pro (LWP)", "document", "application/vnd.lotus-wordpro", read_only=True),
    _f("uot", "Unified Office Text (UOT)", "document", "application/x-uo"),
    _f("hwp", "Hangul (HWP)", "document", "application/x-hwp", read_only=True),
    _f("pages", "Apple Pages", "document", "application/x-iwork-pages-sffpages", read_only=True,
       note="Nur moderne Pages-Dateien mit eingebettetem PDF-Vorschauinhalt."),

    # ------------------------------------------------------------------
    # Tabellen
    # ------------------------------------------------------------------
    _f("xlsx", "Excel-Arbeitsmappe (XLSX)", "spreadsheet",
       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    _f("xls", "Excel 97-2003 (XLS)", "spreadsheet", "application/vnd.ms-excel"),
    _f("xlsm", "Excel mit Makros (XLSM)", "spreadsheet",
       "application/vnd.ms-excel.sheet.macroEnabled.12"),
    _f("xltx", "Excel-Vorlage (XLTX)", "spreadsheet",
       "application/vnd.openxmlformats-officedocument.spreadsheetml.template"),
    _f("xlt", "Excel-Vorlage (XLT)", "spreadsheet", "application/vnd.ms-excel"),
    _f("ods", "OpenDocument Tabelle (ODS)", "spreadsheet",
       "application/vnd.oasis.opendocument.spreadsheet"),
    _f("ots", "OpenDocument Tabellenvorlage (OTS)", "spreadsheet",
       "application/vnd.oasis.opendocument.spreadsheet-template"),
    _f("fods", "Flat-XML ODF Tabelle (FODS)", "spreadsheet",
       "application/vnd.oasis.opendocument.spreadsheet-flat-xml"),
    _f("sxc", "StarOffice Calc (SXC)", "spreadsheet", "application/vnd.sun.xml.calc"),
    _f("csv", "CSV (Trennzeichen-getrennt)", "spreadsheet", "text/csv"),
    _f("tsv", "TSV (Tabulator-getrennt)", "spreadsheet", "text/tab-separated-values"),
    _f("dif", "Data Interchange Format (DIF)", "spreadsheet", "text/x-dif"),
    _f("slk", "SYLK (SLK)", "spreadsheet", "text/x-sylk"),
    _f("dbf", "dBASE-Datenbank (DBF)", "spreadsheet", "application/x-dbf"),
    _f("numbers", "Apple Numbers", "spreadsheet", "application/x-iwork-numbers-sffnumbers",
       read_only=True),

    # ------------------------------------------------------------------
    # Praesentationen
    # ------------------------------------------------------------------
    _f("pptx", "PowerPoint-Praesentation (PPTX)", "presentation",
       "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    _f("ppt", "PowerPoint 97-2003 (PPT)", "presentation", "application/vnd.ms-powerpoint"),
    _f("pptm", "PowerPoint mit Makros (PPTM)", "presentation",
       "application/vnd.ms-powerpoint.presentation.macroEnabled.12"),
    _f("pps", "PowerPoint-Bildschirmpraesentation (PPS)", "presentation",
       "application/vnd.ms-powerpoint"),
    _f("ppsx", "PowerPoint-Bildschirmpraesentation (PPSX)", "presentation",
       "application/vnd.openxmlformats-officedocument.presentationml.slideshow"),
    _f("potx", "PowerPoint-Vorlage (POTX)", "presentation",
       "application/vnd.openxmlformats-officedocument.presentationml.template"),
    _f("pot", "PowerPoint-Vorlage (POT)", "presentation", "application/vnd.ms-powerpoint"),
    _f("odp", "OpenDocument Praesentation (ODP)", "presentation",
       "application/vnd.oasis.opendocument.presentation"),
    _f("otp", "OpenDocument Praesentationsvorlage (OTP)", "presentation",
       "application/vnd.oasis.opendocument.presentation-template"),
    _f("fodp", "Flat-XML ODF Praesentation (FODP)", "presentation",
       "application/vnd.oasis.opendocument.presentation-flat-xml"),
    _f("sxi", "StarOffice Impress (SXI)", "presentation", "application/vnd.sun.xml.impress"),
    _f("key", "Apple Keynote", "presentation", "application/x-iwork-keynote-sffkey", read_only=True),

    # ------------------------------------------------------------------
    # Zeichnungen und Vektorgrafik
    # ------------------------------------------------------------------
    _f("odg", "OpenDocument Zeichnung (ODG)", "drawing",
       "application/vnd.oasis.opendocument.graphics"),
    _f("otg", "OpenDocument Zeichnungsvorlage (OTG)", "drawing",
       "application/vnd.oasis.opendocument.graphics-template"),
    _f("fodg", "Flat-XML ODF Zeichnung (FODG)", "drawing",
       "application/vnd.oasis.opendocument.graphics-flat-xml"),
    _f("sxd", "StarOffice Draw (SXD)", "drawing", "application/vnd.sun.xml.draw"),
    _f("svg", "SVG-Vektorgrafik", "drawing", "image/svg+xml"),
    _f("vsd", "Visio-Zeichnung (VSD)", "drawing", "application/vnd.visio", read_only=True),
    _f("vsdx", "Visio-Zeichnung (VSDX)", "drawing",
       "application/vnd.ms-visio.drawing", read_only=True),
    _f("cdr", "CorelDRAW (CDR)", "drawing", "application/vnd.corel-draw", read_only=True),
    _f("pub", "Microsoft Publisher (PUB)", "drawing", "application/x-mspublisher", read_only=True),
    _f("wmf", "Windows Metafile (WMF)", "drawing", "image/wmf"),
    _f("emf", "Enhanced Metafile (EMF)", "drawing", "image/emf"),
    _f("eps", "Encapsulated PostScript (EPS)", "drawing", "application/postscript"),
    _f("ps", "PostScript (PS)", "drawing", "application/postscript"),
    _f("dxf", "AutoCAD-Austauschformat (DXF)", "drawing", "image/vnd.dxf", read_only=True),

    # ------------------------------------------------------------------
    # Text und Markup
    # ------------------------------------------------------------------
    _f("txt", "Reiner Text (TXT)", "markup", "text/plain"),
    _f("md", "Markdown (MD)", "markup", "text/markdown", aliases=("markdown", "mdown", "mkd")),
    _f("html", "HTML-Seite", "markup", "text/html", aliases=("htm", "xhtml")),
    _f("rst", "reStructuredText (RST)", "markup", "text/x-rst"),
    _f("adoc", "AsciiDoc", "markup", "text/asciidoc", aliases=("asciidoc", "asc")),
    _f("org", "Org-Mode", "markup", "text/x-org"),
    _f("tex", "LaTeX", "markup", "application/x-tex", aliases=("latex",)),
    _f("typ", "Typst", "markup", "text/x-typst", write_only=True),
    _f("textile", "Textile", "markup", "text/x-textile"),
    _f("mediawiki", "MediaWiki-Markup", "markup", "text/plain", aliases=("wiki",)),
    _f("dokuwiki", "DokuWiki-Markup", "markup", "text/plain"),
    _f("docbook", "DocBook XML", "markup", "application/docbook+xml"),
    _f("opml", "OPML-Gliederung", "markup", "text/x-opml"),
    _f("ipynb", "Jupyter-Notebook", "markup", "application/x-ipynb+json"),
    _f("man", "Unix-Manpage (roff)", "markup", "text/troff"),

    # ------------------------------------------------------------------
    # E-Books
    # ------------------------------------------------------------------
    _f("epub", "EPUB (E-Book)", "ebook", "application/epub+zip"),
    _f("fb2", "FictionBook (FB2)", "ebook", "application/x-fictionbook+xml"),

    # ------------------------------------------------------------------
    # E-Mail
    # ------------------------------------------------------------------
    _f("eml", "E-Mail (EML / MIME)", "email", "message/rfc822"),
    _f("msg", "Outlook-Nachricht (MSG)", "email", "application/vnd.ms-outlook", read_only=True),
    _f("mbox", "Mailbox-Archiv (MBOX)", "email", "application/mbox", read_only=True),

    # ------------------------------------------------------------------
    # Bilder
    # ------------------------------------------------------------------
    _f("jpg", "JPEG-Bild", "image", "image/jpeg", aliases=("jpeg", "jpe")),
    _f("png", "PNG-Bild", "image", "image/png"),
    _f("gif", "GIF-Bild", "image", "image/gif"),
    _f("bmp", "Windows-Bitmap (BMP)", "image", "image/bmp"),
    _f("tiff", "TIFF-Bild", "image", "image/tiff", aliases=("tif",)),
    _f("webp", "WebP-Bild", "image", "image/webp"),
    _f("avif", "AVIF-Bild", "image", "image/avif"),
    _f("jxl", "JPEG XL", "image", "image/jxl"),
    _f("heic", "HEIC (Apple-Foto)", "image", "image/heic", aliases=("heif",)),
    _f("ico", "Windows-Symbol (ICO)", "image", "image/vnd.microsoft.icon"),
    _f("jp2", "JPEG 2000", "image", "image/jp2", aliases=("j2k", "jpf", "jpx")),
    _f("psd", "Photoshop-Dokument (PSD)", "image", "image/vnd.adobe.photoshop"),
    _f("xcf", "GIMP-Bild (XCF)", "image", "image/x-xcf", read_only=True),
    _f("tga", "Targa (TGA)", "image", "image/x-tga"),
    _f("pcx", "PCX-Bild", "image", "image/x-pcx"),
    _f("ppm", "Portable Pixmap (PPM)", "image", "image/x-portable-pixmap"),
    _f("pgm", "Portable Graymap (PGM)", "image", "image/x-portable-graymap"),
    _f("pbm", "Portable Bitmap (PBM)", "image", "image/x-portable-bitmap"),
    _f("dds", "DirectDraw Surface (DDS)", "image", "image/vnd-ms.dds"),
    _f("exr", "OpenEXR (HDR)", "image", "image/x-exr"),
    _f("hdr", "Radiance HDR", "image", "image/vnd.radiance"),
    _f("xpm", "X-PixMap (XPM)", "image", "image/x-xpixmap"),
    _f("cr2", "Canon-Rohbild (CR2)", "image", "image/x-canon-cr2", read_only=True),
    _f("nef", "Nikon-Rohbild (NEF)", "image", "image/x-nikon-nef", read_only=True),
    _f("arw", "Sony-Rohbild (ARW)", "image", "image/x-sony-arw", read_only=True),
    _f("dng", "Digital Negative (DNG)", "image", "image/x-adobe-dng", read_only=True),
    _f("orf", "Olympus-Rohbild (ORF)", "image", "image/x-olympus-orf", read_only=True),
    _f("raf", "Fujifilm-Rohbild (RAF)", "image", "image/x-fuji-raf", read_only=True),

    # ------------------------------------------------------------------
    # Video
    # ------------------------------------------------------------------
    _f("mp4", "MP4-Video", "video", "video/mp4"),
    _f("mkv", "Matroska-Video (MKV)", "video", "video/x-matroska"),
    _f("webm", "WebM-Video", "video", "video/webm"),
    _f("mov", "QuickTime-Video (MOV)", "video", "video/quicktime"),
    _f("avi", "AVI-Video", "video", "video/x-msvideo"),
    _f("wmv", "Windows Media Video (WMV)", "video", "video/x-ms-wmv"),
    _f("flv", "Flash-Video (FLV)", "video", "video/x-flv"),
    _f("mpg", "MPEG-Video", "video", "video/mpeg", aliases=("mpeg", "mpe")),
    _f("m4v", "MPEG-4-Video (M4V)", "video", "video/x-m4v"),
    _f("3gp", "3GPP-Video", "video", "video/3gpp"),
    _f("ogv", "Ogg-Video (OGV)", "video", "video/ogg"),
    _f("ts", "MPEG-Transportstrom (TS)", "video", "video/mp2t"),
    _f("mts", "AVCHD (MTS/M2TS)", "video", "video/mp2t", aliases=("m2ts",)),
    _f("vob", "DVD-Video (VOB)", "video", "video/mpeg", read_only=True),
    _f("asf", "Advanced Systems Format (ASF)", "video", "video/x-ms-asf"),

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------
    _f("mp3", "MP3-Audio", "audio", "audio/mpeg"),
    _f("wav", "WAV-Audio", "audio", "audio/wav"),
    _f("flac", "FLAC (verlustfrei)", "audio", "audio/flac"),
    _f("ogg", "Ogg-Vorbis", "audio", "audio/ogg", aliases=("oga",)),
    _f("opus", "Opus-Audio", "audio", "audio/opus"),
    _f("m4a", "MPEG-4-Audio (M4A)", "audio", "audio/mp4"),
    _f("aac", "AAC-Audio", "audio", "audio/aac"),
    _f("wma", "Windows Media Audio (WMA)", "audio", "audio/x-ms-wma"),
    _f("aiff", "AIFF-Audio", "audio", "audio/aiff", aliases=("aif",)),
    _f("amr", "AMR-Sprachaufnahme", "audio", "audio/amr"),
    _f("ac3", "Dolby Digital (AC3)", "audio", "audio/ac3"),
    _f("mka", "Matroska-Audio (MKA)", "audio", "audio/x-matroska"),
    _f("au", "Sun-Audio (AU)", "audio", "audio/basic"),
    _f("caf", "Core Audio Format (CAF)", "audio", "audio/x-caf"),
    _f("ape", "Monkey's Audio (APE)", "audio", "audio/x-ape", read_only=True),
    _f("wv", "WavPack (WV)", "audio", "audio/x-wavpack"),

    # ------------------------------------------------------------------
    # Untertitel
    # ------------------------------------------------------------------
    _f("srt", "SubRip-Untertitel (SRT)", "subtitle", "application/x-subrip"),
    _f("vtt", "WebVTT-Untertitel", "subtitle", "text/vtt"),
    _f("ass", "Advanced SubStation (ASS)", "subtitle", "text/x-ssa", aliases=("ssa",)),

    # ------------------------------------------------------------------
    # Daten
    # ------------------------------------------------------------------
    _f("json", "JSON-Daten", "data", "application/json"),
    _f("xml", "XML-Daten", "data", "application/xml"),
    _f("yaml", "YAML-Daten", "data", "application/yaml", aliases=("yml",)),
    _f("toml", "TOML-Konfiguration", "data", "application/toml"),
    _f("ini", "INI-Konfiguration", "data", "text/plain", aliases=("cfg", "conf")),
    _f("jsonl", "JSON Lines (JSONL)", "data", "application/jsonl", aliases=("ndjson",)),
    _f("sql", "SQL-INSERT-Anweisungen", "data", "application/sql", write_only=True),

    # ------------------------------------------------------------------
    # Archive
    # ------------------------------------------------------------------
    _f("zip", "ZIP-Archiv", "archive", "application/zip"),
    _f("tar", "TAR-Archiv", "archive", "application/x-tar"),
    _f("tgz", "TAR-GZIP-Archiv", "archive", "application/gzip", aliases=("tar.gz",)),
    _f("tbz2", "TAR-BZIP2-Archiv", "archive", "application/x-bzip2", aliases=("tar.bz2",)),
    _f("txz", "TAR-XZ-Archiv", "archive", "application/x-xz", aliases=("tar.xz",)),
    _f("7z", "7-Zip-Archiv", "archive", "application/x-7z-compressed"),
    _f("rar", "RAR-Archiv", "archive", "application/vnd.rar", read_only=True),
    _f("gz", "GZIP-Datei", "archive", "application/gzip"),
    _f("bz2", "BZIP2-Datei", "archive", "application/x-bzip2"),
    _f("xz", "XZ-Datei", "archive", "application/x-xz"),
    _f("iso", "ISO-Abbild", "archive", "application/x-iso9660-image", read_only=True),

    # ------------------------------------------------------------------
    # Schriften
    # ------------------------------------------------------------------
    _f("ttf", "TrueType-Schrift (TTF)", "font", "font/ttf"),
    _f("otf", "OpenType-Schrift (OTF)", "font", "font/otf"),
    _f("woff", "Web-Schrift (WOFF)", "font", "font/woff"),
    _f("woff2", "Web-Schrift (WOFF2)", "font", "font/woff2"),
]


FORMATS: dict[str, Format] = {fmt.ext: fmt for fmt in _ALL}

# Manche Kennungen des Katalogs sind keine Dateiendungen: PDF/A ist ein
# Profil und wird als ".pdf" gespeichert, TAR-Varianten haben zusammen-
# gesetzte Endungen.
FILE_SUFFIX: dict[str, str] = {
    "pdfa": "pdf",
    "tgz": "tar.gz",
    "tbz2": "tar.bz2",
    "txz": "tar.xz",
    "docbook": "xml",
    "mediawiki": "wiki",
    "dokuwiki": "txt",
    "typ": "typ",
}


def file_suffix(ext: str) -> str:
    """Endung, unter der ein Ergebnis gespeichert bzw. ausgeliefert wird."""
    key = canonical(ext) or ext.lower().lstrip(".")
    return FILE_SUFFIX.get(key, key)

# Aliase auf die kanonische Endung abbilden ("jpeg" -> "jpg").
_ALIAS_MAP: dict[str, str] = {}
for _fmt in _ALL:
    _ALIAS_MAP[_fmt.ext] = _fmt.ext
    for _alias in _fmt.aliases:
        _ALIAS_MAP[_alias] = _fmt.ext


def canonical(ext: str) -> str | None:
    """Normalisiert eine Endung auf die kanonische Kennung des Katalogs."""
    if not ext:
        return None
    key = ext.strip().lower().lstrip(".")
    return _ALIAS_MAP.get(key)


def get(ext: str) -> Format | None:
    key = canonical(ext)
    return FORMATS.get(key) if key else None


def label(ext: str) -> str:
    fmt = get(ext)
    return fmt.label if fmt else ext.upper()


def mime(ext: str) -> str:
    fmt = get(ext)
    return fmt.mime if fmt else "application/octet-stream"


def expand(*exts: str) -> set[str]:
    """Hilfsfunktion fuer Engines: normalisiert eine Liste von Endungen."""
    result: set[str] = set()
    for ext in exts:
        key = canonical(ext)
        if key:
            result.add(key)
    return result


def by_category(exts: Iterable[str]) -> dict[str, list[Format]]:
    """Gruppiert Formate nach Kategorie, in der Reihenfolge des Katalogs."""
    buckets: dict[str, list[Format]] = {}
    for ext in exts:
        fmt = FORMATS.get(ext)
        if fmt is None:
            continue
        buckets.setdefault(fmt.category, []).append(fmt)
    ordered: dict[str, list[Format]] = {}
    for category in CATEGORY_ORDER:
        entries = buckets.get(category)
        if entries:
            ordered[category] = sorted(entries, key=lambda f: f.label.lower())
    return ordered
