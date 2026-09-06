"""Ausfuehrung der Konvertierungen.

Ein Auftrag besteht aus mehreren Dateien. Jede Datei wird einzeln ueber den
in der Registry gefundenen Weg gefuehrt; danach folgt optional eine
Nachbearbeitung (Texterkennung, Komprimierung). Fehler einzelner Dateien
brechen den Auftrag nicht ab.
"""

from __future__ import annotations

import logging
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from app import formats
from app.config import settings
from app.engines.base import ConversionError, StepContext, run_command
from app.registry import Route, registry
from app.security import sanitize_filename, split_extension

log = logging.getLogger("converter.pipeline")


@dataclass
class SourceFile:
    """Eine hochgeladene Datei."""

    file_id: str
    original_name: str
    path: Path
    ext: str
    size: int


@dataclass
class FileOutcome:
    """Ergebnis fuer genau eine Eingabedatei."""

    file_id: str
    original_name: str
    status: str = "wartet"          # wartet | laeuft | fertig | fehler
    result_name: str = ""
    result_path: Path | None = None
    size: int = 0
    error: str = ""
    detail: str = ""
    route: str = ""
    engines: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    duration: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.file_id,
            "name": self.original_name,
            "status": self.status,
            "resultName": self.result_name,
            "size": self.size,
            "error": self.error,
            "detail": self.detail,
            "route": self.route,
            "engines": self.engines,
            "notes": self.notes,
            "duration": round(self.duration, 2),
        }


def convert_file(
    source: SourceFile,
    target_ext: str,
    options: dict[str, object],
    scratch_root: Path,
    result_dir: Path,
    timeout: int,
) -> FileOutcome:
    """Fuehrt eine Datei ueber den gefundenen Weg zum Zielformat."""

    outcome = FileOutcome(file_id=source.file_id, original_name=source.original_name)
    started = time.monotonic()
    scratch = scratch_root / f"f-{source.file_id}"
    scratch.mkdir(parents=True, exist_ok=True)

    try:
        target = formats.canonical(target_ext)
        if target is None:
            raise ConversionError(f"Das Zielformat '{target_ext}' ist unbekannt.")

        if source.ext == target:
            raise ConversionError(
                f"Die Datei liegt bereits als {target.upper()} vor.",
                "Bitte ein anderes Zielformat waehlen.",
            )

        route = registry.route(source.ext, target)
        if route is None:
            raise ConversionError(
                f"Fuer {source.ext.upper()} nach {target.upper()} gibt es keinen Weg.",
                "Bitte ein anderes Zielformat waehlen.",
            )

        outcome.route = route.describe()
        outcome.engines = route.engine_names()
        ctx = StepContext(scratch=scratch, timeout=timeout, options=dict(options))

        prepared = _preprocess(source.path, source.ext, scratch, ctx)
        produced = _run_route(prepared, route, scratch, ctx)
        produced = _postprocess(produced, source.ext, target, ctx)

        stem, _ = split_extension(sanitize_filename(source.original_name))
        suffix = formats.file_suffix(target)
        final = _unique_result(result_dir, stem or "ergebnis", suffix)
        shutil.move(str(produced), str(final))

        outcome.result_path = final
        outcome.result_name = final.name
        outcome.size = final.stat().st_size
        outcome.notes = list(ctx.log_lines)
        outcome.status = "fertig"

    except ConversionError as exc:
        outcome.status = "fehler"
        outcome.error = exc.message
        outcome.detail = exc.detail
        log.info("Konvertierung fehlgeschlagen (%s): %s", source.original_name, exc.message)
    except Exception as exc:  # pragma: no cover - unerwarteter Fehler
        outcome.status = "fehler"
        outcome.error = "Unerwarteter Fehler bei der Konvertierung."
        outcome.detail = f"{type(exc).__name__}: {exc}"
        log.exception("Unerwarteter Fehler bei %s", source.original_name)
    finally:
        outcome.duration = time.monotonic() - started
        shutil.rmtree(scratch, ignore_errors=True)

    return outcome


def _run_route(src: Path, route: Route, scratch: Path, ctx: StepContext) -> Path:
    current = src
    for index, step in enumerate(route.steps, start=1):
        suffix = formats.file_suffix(step.dst_ext)
        target = scratch / f"schritt{index}.{suffix}"
        ctx.scratch = scratch / f"s{index}"
        ctx.scratch.mkdir(parents=True, exist_ok=True)
        step.engine.convert(current, target, step.src_ext, step.dst_ext, ctx)
        if not target.exists() or target.stat().st_size == 0:
            raise ConversionError(
                f"Schritt {index} ({step.describe()}) hat keine Datei erzeugt."
            )
        current = target
    ctx.scratch = scratch
    return current


def _preprocess(path: Path, src_ext: str, scratch: Path, ctx: StepContext) -> Path:
    """Texterkennung vor der eigentlichen Umwandlung.

    Ein eingescanntes PDF traegt keinen Text. Damit Wege wie PDF nach Word
    oder PDF nach Text ueberhaupt etwas liefern, muss die Textebene vorher
    erzeugt werden - nicht erst am Ende.
    """
    if src_ext != "pdf" or not ctx.opt_bool("ocr", False):
        return path

    # Die Quelldatei selbst wird nicht veraendert.
    arbeitskopie = scratch / "quelle-ocr.pdf"
    shutil.copy2(path, arbeitskopie)
    return _run_ocr(arbeitskopie, ctx)


def _postprocess(path: Path, src_ext: str, target: str, ctx: StepContext) -> Path:
    """Optionale Nachbearbeitung fuer PDF-Ergebnisse."""
    if target not in {"pdf", "pdfa"}:
        return path

    # Bei PDF-Quellen ist die Texterkennung bereits vorab gelaufen.
    if ctx.opt_bool("ocr", False) and src_ext != "pdf":
        path = _run_ocr(path, ctx)
    if ctx.opt_bool("compress", False):
        path = _compress_pdf(path, ctx)
    return path


def _run_ocr(path: Path, ctx: StepContext) -> Path:
    """Durchsuchbare Textebene per Tesseract erzeugen."""
    if shutil.which("ocrmypdf") is None:
        ctx.note("Texterkennung uebersprungen: ocrmypdf ist nicht installiert.")
        return path

    target = path.with_name(f"{path.stem}-ocr.pdf")
    languages = ctx.opt_str("ocr_language", "deu+eng") or "deu+eng"
    # Nur erlaubte Sprachkuerzel weiterreichen.
    languages = "+".join(part for part in languages.split("+") if part.isalpha() and len(part) <= 8)[:40]
    argv = [
        "ocrmypdf",
        "--quiet",
        "--language", languages or "deu",
        # Seiten mit vorhandener Textebene unveraendert lassen.
        "--skip-text",
        "--optimize", "1",
        "--jobs", "2",
    ]
    if ctx.opt_bool("deskew", True):
        argv.append("--deskew")
    argv += [str(path), str(target)]

    try:
        run_command(argv, timeout=ctx.timeout, label="Texterkennung")
    except ConversionError as exc:
        ctx.note(f"Texterkennung nicht moeglich: {exc.message}")
        return path
    if not target.exists() or target.stat().st_size == 0:
        ctx.note("Texterkennung hat kein Ergebnis geliefert; das Original wird ausgeliefert.")
        return path
    ctx.note(f"Texterkennung durchgefuehrt (Sprachen: {languages}).")
    return target


def _compress_pdf(path: Path, ctx: StepContext) -> Path:
    """PDF ueber Ghostscript verkleinern."""
    from app.engines.pdftools import GS_PRESETS, _gs_base

    preset = GS_PRESETS.get(ctx.opt_str("compress_preset", "ebook"), "/ebook")
    target = path.with_name(f"{path.stem}-klein.pdf")
    argv = _gs_base() + [
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.7",
        f"-dPDFSETTINGS={preset}",
        "-dDetectDuplicateImages=true",
        "-dCompressFonts=true",
        f"-sOutputFile={target}",
        str(path),
    ]
    try:
        run_command(argv, timeout=ctx.timeout, label="PDF-Komprimierung")
    except ConversionError as exc:
        ctx.note(f"Komprimierung nicht moeglich: {exc.message}")
        return path

    if not target.exists() or target.stat().st_size == 0:
        return path
    before, after = path.stat().st_size, target.stat().st_size
    if after >= before:
        ctx.note("Komprimierung brachte keine Verkleinerung; das Original wird ausgeliefert.")
        target.unlink(missing_ok=True)
        return path
    ctx.note(f"Groesse durch Komprimierung von {_human(before)} auf {_human(after)} verringert.")
    return target


def merge_pdfs(paths: list[Path], destination: Path, ctx: StepContext) -> Path:
    """Mehrere PDF-Dateien in der uebergebenen Reihenfolge zusammenfuehren."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    try:
        for path in paths:
            writer.append(str(path))
        with destination.open("wb") as handle:
            writer.write(handle)
    except Exception as exc:
        raise ConversionError("Die PDF-Dateien konnten nicht zusammengefuehrt werden.", str(exc)) from exc
    finally:
        writer.close()
    ctx.note(f"{len(paths)} Dokumente zusammengefuehrt.")
    return destination


def build_zip(outcomes: list[FileOutcome], destination: Path) -> Path:
    """Alle erfolgreichen Ergebnisse in ein ZIP-Archiv legen."""
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        used: set[str] = set()
        for outcome in outcomes:
            if outcome.status != "fertig" or outcome.result_path is None:
                continue
            name = outcome.result_name
            counter = 1
            while name in used:
                stem, _, suffix = outcome.result_name.rpartition(".")
                name = f"{stem}-{counter}.{suffix}" if suffix else f"{outcome.result_name}-{counter}"
                counter += 1
            used.add(name)
            archive.write(outcome.result_path, name)
    return destination


def _unique_result(directory: Path, stem: str, suffix: str) -> Path:
    """Freier Dateiname im Ergebnisordner des Auftrags."""
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{stem}.{suffix}"
    counter = 2
    # Zwei Uploads koennen denselben Namen tragen ("scan.pdf" aus zwei Ordnern).
    while candidate.exists():
        candidate = directory / f"{stem}-{counter}.{suffix}"
        counter += 1
    return candidate


def _human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"
