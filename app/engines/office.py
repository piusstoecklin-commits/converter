"""LibreOffice-Engines fuer Office-Dokumente.

LibreOffice wird headless als Unterprozess gestartet. Jeder Auftrag erhaelt
ein eigenes, leeres Benutzerprofil. Das erlaubt parallele Konvertierungen
und stellt sicher, dass keine Einstellung eines vorherigen Dokuments
uebernommen wird.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from app import formats
from app.engines.base import ConversionError, Engine, StepContext, run_command

# Profilvorgabe: Makroausfuehrung auf "sehr hoch" (nur signierte, vertrauens-
# wuerdige Makros) und keine automatischen Netzwerkzugriffe. Wird als frisches
# Profil vor jedem Start hinterlegt.
_PROFILE_XCU = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry"
           xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <item oor:path="/org.openoffice.Office.Common/Security/Scripting">
    <prop oor:name="MacroSecurityLevel" oor:op="fuse">
      <value>3</value>
    </prop>
    <prop oor:name="DisableMacrosExecution" oor:op="fuse">
      <value>true</value>
    </prop>
  </item>
  <item oor:path="/org.openoffice.Office.Common/Save/Document">
    <prop oor:name="LoadPrinter" oor:op="fuse">
      <value>false</value>
    </prop>
  </item>
  <item oor:path="/org.openoffice.Office.Common/Internal">
    <prop oor:name="CurrentTempURL" oor:op="fuse">
      <value></value>
    </prop>
  </item>
</oor:items>
"""

# Zielformat -> LibreOffice-Exportfilter, getrennt nach Anwendung.
WRITER_TARGETS: dict[str, str] = {
    "pdf": "pdf:writer_pdf_Export",
    "docx": "docx:MS Word 2007 XML",
    "doc": "doc:MS Word 97",
    "dotx": "dotx:MS Word 2007 XML Template",
    "dot": "dot:MS Word 97 Vorlage",
    "odt": "odt:writer8",
    "ott": "ott:writer8_template",
    "fodt": "fodt:OpenDocument Text Flat XML",
    "rtf": "rtf:Rich Text Format",
    "txt": "txt:Text (encoded):UTF8",
    "html": "html:HTML (StarWriter)",
    "epub": "epub:EPUB",
    "uot": "uot:UOF text",
    "png": "png:writer_png_Export",
    "jpg": "jpg:writer_jpg_Export",
}

CALC_TARGETS: dict[str, str] = {
    "pdf": "pdf:calc_pdf_Export",
    "xlsx": "xlsx:Calc MS Excel 2007 XML",
    "xls": "xls:MS Excel 97",
    "xltx": "xltx:Calc MS Excel 2007 XML Template",
    "ods": "ods:calc8",
    "ots": "ots:calc8_template",
    "fods": "fods:OpenDocument Spreadsheet Flat XML",
    "html": "html:HTML (StarCalc)",
    # 44 = Komma als Trennzeichen, 34 = Anfuehrungszeichen, 76 = UTF-8.
    "csv": "csv:Text - txt - csv (StarCalc):44,34,76,1,,0,false,true,true",
    "dif": "dif:DIF",
    "slk": "slk:SYLK",
    "dbf": "dbf:dBase",
}

IMPRESS_TARGETS: dict[str, str] = {
    "pdf": "pdf:impress_pdf_Export",
    "pptx": "pptx:Impress MS PowerPoint 2007 XML",
    "ppt": "ppt:MS PowerPoint 97",
    "ppsx": "ppsx:Impress MS PowerPoint 2007 XML AutoPlay",
    "potx": "potx:Impress MS PowerPoint 2007 XML Template",
    "odp": "odp:impress8",
    "otp": "otp:impress8_template",
    "fodp": "fodp:OpenDocument Presentation Flat XML",
    "html": "html:impress_html_Export",
    "svg": "svg:impress_svg_Export",
    "png": "png:impress_png_Export",
    "jpg": "jpg:impress_jpg_Export",
}

DRAW_TARGETS: dict[str, str] = {
    "pdf": "pdf:draw_pdf_Export",
    "odg": "odg:draw8",
    "otg": "otg:draw8_template",
    "fodg": "fodg:OpenDocument Drawing Flat XML",
    "svg": "svg:draw_svg_Export",
    "png": "png:draw_png_Export",
    "jpg": "jpg:draw_jpg_Export",
    "gif": "gif:draw_gif_Export",
    "tiff": "tif:draw_tif_Export",
    "bmp": "bmp:draw_bmp_Export",
    "emf": "emf:draw_emf_Export",
    "wmf": "wmf:draw_wmf_Export",
    "eps": "eps:draw_eps_Export",
    "html": "html:draw_html_Export",
}

# Importfilter fuer Formate, bei denen LibreOffice sonst raten muesste.
IMPORT_FILTERS: dict[str, str] = {
    "txt": "Text (encoded):UTF8",
    "csv": "Text - txt - csv (StarCalc):44,34,76,1,,0,true,true,true",
    "tsv": "Text - txt - csv (StarCalc):9,34,76,1,,0,true,true,true",
}


class LibreOfficeEngine(Engine):
    """Gemeinsame Basis fuer Writer, Calc, Impress und Draw."""

    requires = "soffice"
    cost = 10

    def __init__(self, family: str, label: str, sources: tuple[str, ...], target_map: dict[str, str]):
        self.name = f"libreoffice-{family}"
        self.label = label
        self.family = family
        self.target_map = target_map
        self.source_exts = sources
        self.target_exts = tuple(target_map)
        super().__init__()

    def edge_cost(self, src: str, dst: str) -> int:
        # Rastergrafik aus einem Textdokument ist ein Notnagel und soll nur
        # gewaehlt werden, wenn es keinen besseren Weg gibt.
        if dst in {"png", "jpg", "bmp", "gif", "tiff"}:
            return self.cost + 25
        # Verlustfreie Wege innerhalb der ODF-Familie sind besonders guenstig.
        if dst in {"pdf", "odt", "ods", "odp", "odg", "docx", "xlsx", "pptx"}:
            return self.cost
        return self.cost + 4

    def convert(self, src: Path, dst: Path, src_ext: str, dst_ext: str, ctx: StepContext) -> Path:
        filter_spec = self.target_map.get(dst_ext)
        if filter_spec is None:
            raise ConversionError(f"LibreOffice kann kein {dst_ext.upper()} aus {src_ext.upper()} erzeugen.")

        outdir = ctx.scratch / f"lo-{uuid.uuid4().hex[:8]}"
        outdir.mkdir(parents=True, exist_ok=True)
        profile = self._make_profile(ctx.scratch)

        argv = [
            "soffice",
            f"-env:UserInstallation=file://{profile}",
            "--headless",
            "--invisible",
            "--nologo",
            "--nofirststartwizard",
            "--norestore",
            "--nodefault",
            "--nolockcheck",
        ]
        infilter = IMPORT_FILTERS.get(src_ext)
        if infilter:
            argv.append(f"--infilter={infilter}")
        argv += ["--convert-to", filter_spec, "--outdir", str(outdir), str(src)]

        output = run_command(argv, timeout=ctx.timeout, cwd=outdir, label="LibreOffice")

        produced = self._collect(outdir, dst_ext)
        if produced is None:
            raise ConversionError(
                f"LibreOffice hat keine {dst_ext.upper()}-Datei erzeugt.",
                output.strip()[-2000:] or "Das Quelldokument ist moeglicherweise beschaedigt oder passwortgeschuetzt.",
            )
        shutil.move(str(produced), str(dst))
        shutil.rmtree(outdir, ignore_errors=True)
        shutil.rmtree(profile, ignore_errors=True)
        return dst

    def _make_profile(self, scratch: Path) -> Path:
        profile = scratch / f"loprofile-{uuid.uuid4().hex[:8]}"
        (profile / "user").mkdir(parents=True, exist_ok=True)
        try:
            (profile / "user" / "registrymodifications.xcu").write_text(_PROFILE_XCU, encoding="utf-8")
        except OSError:
            # Ohne Vorgabe startet LibreOffice mit Standardeinstellungen; das
            # ist kein Grund, die Konvertierung abzubrechen.
            pass
        return profile

    @staticmethod
    def _collect(outdir: Path, dst_ext: str) -> Path | None:
        candidates = [p for p in outdir.iterdir() if p.is_file()]
        if not candidates:
            return None
        # Bevorzugt die Datei mit passender Endung (LibreOffice benutzt z. B.
        # ".tif" statt ".tiff" und ".jpg" statt ".jpeg").
        wanted = {dst_ext}
        fmt = formats.get(dst_ext)
        if fmt:
            wanted |= set(fmt.aliases)
        wanted |= {"tif"} if dst_ext == "tiff" else set()
        for path in candidates:
            if path.suffix.lower().lstrip(".") in wanted:
                return path
        return max(candidates, key=lambda p: p.stat().st_size)


# LibreOffice liest kein Markdown und kein EPUB - diese Wege laufen ueber
# Pandoc und danach ueber Writer.
WRITER_SOURCES = (
    "odt", "ott", "fodt", "sxw", "docx", "doc", "docm", "dot", "dotx", "rtf",
    "txt", "html", "wpd", "wps", "lwp", "uot", "hwp",
)
CALC_SOURCES = (
    "ods", "ots", "fods", "sxc", "xlsx", "xls", "xlsm", "xlt", "xltx",
    "csv", "tsv", "dif", "slk", "dbf",
)
IMPRESS_SOURCES = (
    "odp", "otp", "fodp", "sxi", "pptx", "ppt", "pptm", "pps", "ppsx", "pot", "potx",
)
DRAW_SOURCES = (
    "odg", "otg", "fodg", "sxd", "svg", "vsd", "vsdx", "cdr", "pub", "wmf", "emf", "dxf",
)


def engines() -> list[Engine]:
    return [
        LibreOfficeEngine("writer", "LibreOffice Writer", WRITER_SOURCES, WRITER_TARGETS),
        LibreOfficeEngine("calc", "LibreOffice Calc", CALC_SOURCES, CALC_TARGETS),
        LibreOfficeEngine("impress", "LibreOffice Impress", IMPRESS_SOURCES, IMPRESS_TARGETS),
        LibreOfficeEngine("draw", "LibreOffice Draw", DRAW_SOURCES, DRAW_TARGETS),
    ]
