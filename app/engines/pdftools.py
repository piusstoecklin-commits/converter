"""PDF-Engines: Ghostscript, Poppler und pdf2docx."""

from __future__ import annotations

import shutil
from pathlib import Path

from app.engines.base import ConversionError, Engine, StepContext, run_command

# Ghostscript-Voreinstellungen fuer die Komprimierung.
GS_PRESETS: dict[str, str] = {
    "screen": "/screen",      # kleinste Datei, 72 dpi
    "ebook": "/ebook",        # ausgewogen, 150 dpi
    "printer": "/printer",    # Druckqualitaet, 300 dpi
    "prepress": "/prepress",  # Druckvorstufe, farbtreu
}


def _gs_base() -> list[str]:
    return [
        "gs",
        "-dSAFER",            # kein Dateisystemzugriff aus dem PostScript heraus
        "-dBATCH",
        "-dNOPAUSE",
        "-dQUIET",
        "-dNOOUTERSAVE",
        "-dPARANOIDSAFER",
    ]


class GhostscriptPdfaEngine(Engine):
    """Erzeugt archivtaugliches PDF/A-2b aus einem beliebigen PDF."""

    name = "ghostscript-pdfa"
    label = "Ghostscript (PDF/A)"
    requires = "gs"
    cost = 12
    source_exts = ("pdf",)
    target_exts = ("pdfa",)

    def convert(self, src: Path, dst: Path, src_ext: str, dst_ext: str, ctx: StepContext) -> Path:
        definition = ctx.scratch / "pdfa_def.ps"
        definition.write_text(_PDFA_DEF, encoding="utf-8")
        argv = _gs_base() + [
            "-dPDFA=2",
            "-dPDFACompatibilityPolicy=1",
            "-sColorConversionStrategy=UseDeviceIndependentColor",
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.7",
            f"-sOutputFile={dst}",
            str(definition),
            str(src),
        ]
        run_command(argv, timeout=ctx.timeout, label="Ghostscript")
        if not dst.exists() or dst.stat().st_size == 0:
            raise ConversionError("Das PDF/A konnte nicht erzeugt werden.")
        return dst


class PostScriptEngine(Engine):
    """PostScript und EPS zuverlaessig nach PDF wandeln."""

    name = "ghostscript-ps"
    label = "Ghostscript (PostScript)"
    requires = "gs"
    cost = 10
    source_exts = ("ps", "eps")
    target_exts = ("pdf",)

    def convert(self, src: Path, dst: Path, src_ext: str, dst_ext: str, ctx: StepContext) -> Path:
        argv = _gs_base() + [
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.7",
            "-dEPSCrop" if src_ext == "eps" else "-dAutoRotatePages=/PageByPage",
            f"-sOutputFile={dst}",
            str(src),
        ]
        run_command(argv, timeout=ctx.timeout, label="Ghostscript")
        if not dst.exists() or dst.stat().st_size == 0:
            raise ConversionError("Aus der PostScript-Datei konnte kein PDF erzeugt werden.")
        return dst


class PopplerTextEngine(Engine):
    """Textebene eines PDF extrahieren."""

    name = "poppler-text"
    label = "Poppler (Textextraktion)"
    requires = "pdftotext"
    # Die Textextraktion verwirft jede Formatierung. Sie ist deshalb teuer,
    # damit sie nie als Zwischenschritt auf dem Weg zu einem Dokument dient.
    cost = 24
    source_exts = ("pdf",)
    target_exts = ("txt",)

    def convert(self, src: Path, dst: Path, src_ext: str, dst_ext: str, ctx: StepContext) -> Path:
        argv = ["pdftotext", "-enc", "UTF-8", "-nopgbrk"]
        if ctx.opt_bool("keep_layout", True):
            argv.append("-layout")
        argv += [str(src), str(dst)]
        run_command(argv, timeout=ctx.timeout, label="pdftotext")
        if not dst.exists():
            raise ConversionError("Aus dem PDF konnte kein Text gelesen werden.")
        if dst.stat().st_size == 0:
            raise ConversionError(
                "Dieses PDF enthaelt keine Textebene.",
                "Es handelt sich vermutlich um einen Scan. Bitte die Einstellung "
                "'Texterkennung (OCR) durchfuehren' aktivieren und erneut starten.",
            )
        return dst


class PopplerHtmlEngine(Engine):
    """PDF als HTML mit eingebetteten Bildern."""

    name = "poppler-html"
    label = "Poppler (HTML)"
    requires = "pdftohtml"
    cost = 22
    source_exts = ("pdf",)
    target_exts = ("html",)

    def convert(self, src: Path, dst: Path, src_ext: str, dst_ext: str, ctx: StepContext) -> Path:
        outdir = ctx.scratch / "pdfhtml"
        outdir.mkdir(parents=True, exist_ok=True)
        target = outdir / "seite.html"
        argv = ["pdftohtml", "-s", "-i", "-noframes", "-enc", "UTF-8", "-fmt", "png", str(src), str(target)]
        run_command(argv, timeout=ctx.timeout, cwd=outdir, label="pdftohtml")
        if not target.exists():
            raise ConversionError("Das PDF konnte nicht als HTML dargestellt werden.")
        shutil.move(str(target), str(dst))
        return dst


class Pdf2DocxEngine(Engine):
    """PDF in ein bearbeitbares Word-Dokument ueberfuehren."""

    name = "pdf2docx"
    label = "pdf2docx"
    # Guenstiger als der Umweg ueber reinen Text, weil das Layout erhalten bleibt.
    cost = 18
    source_exts = ("pdf",)
    target_exts = ("docx",)

    def convert(self, src: Path, dst: Path, src_ext: str, dst_ext: str, ctx: StepContext) -> Path:
        try:
            from pdf2docx import Converter
        except ImportError as exc:  # pragma: no cover
            raise ConversionError("Das Modul pdf2docx ist nicht installiert.", str(exc)) from exc

        converter = None
        try:
            converter = Converter(str(src))
            converter.convert(str(dst), start=0, end=None)
        except Exception as exc:
            raise ConversionError(
                "Das PDF konnte nicht in ein Word-Dokument umgesetzt werden.",
                f"{type(exc).__name__}: {exc}",
            ) from exc
        finally:
            if converter is not None:
                try:
                    converter.close()
                except Exception:
                    pass

        if not dst.exists() or dst.stat().st_size == 0:
            raise ConversionError("pdf2docx hat kein Dokument erzeugt.")
        ctx.note(
            "PDF nach Word ist eine Nachbildung des Layouts. Bitte das Ergebnis vor "
            "der Weiterverwendung pruefen."
        )
        return dst


# Minimale PDF/A-Definition fuer Ghostscript (ohne externes ICC-Profil).
_PDFA_DEF = """%!
[ /Title (Konvertiertes Dokument)
  /DOCINFO pdfmark
[ /GTS_PDFA1 true
  /Copyright ()
  /DOCINFO pdfmark
"""


def engines() -> list[Engine]:
    return [
        GhostscriptPdfaEngine(),
        PostScriptEngine(),
        PopplerTextEngine(),
        PopplerHtmlEngine(),
        Pdf2DocxEngine(),
    ]
