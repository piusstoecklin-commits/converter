"""Pandoc-Engine fuer Text-, Markup- und E-Book-Formate."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from app.engines.base import ConversionError, Engine, StepContext, run_command

# Endung -> Pandoc-Lesefilter.
READERS: dict[str, str] = {
    "md": "markdown",
    "html": "html",
    "rst": "rst",
    "tex": "latex",
    "org": "org",
    "textile": "textile",
    "mediawiki": "mediawiki",
    "docbook": "docbook",
    "opml": "opml",
    "ipynb": "ipynb",
    "man": "man",
    "epub": "epub",
    "fb2": "fb2",
    "docx": "docx",
    "odt": "odt",
    "csv": "csv",
    "json": "json",
}

# Endung -> Pandoc-Schreibfilter.
WRITERS: dict[str, str] = {
    "md": "markdown",
    "html": "html5",
    "rst": "rst",
    "tex": "latex",
    "typ": "typst",
    "org": "org",
    "textile": "textile",
    "mediawiki": "mediawiki",
    "dokuwiki": "dokuwiki",
    "docbook": "docbook5",
    "opml": "opml",
    "ipynb": "ipynb",
    "man": "man",
    "adoc": "asciidoc",
    "epub": "epub3",
    "fb2": "fb2",
    "docx": "docx",
    "odt": "odt",
    "rtf": "rtf",
    "txt": "plain",
}

# Diese Zielformate sind Container, fuer die Pandoc eigene Vorlagendateien
# aus seinem Datenverzeichnis liest. Der Sandbox-Modus verbietet genau das,
# weshalb solche Ziele bei aktiver Sandbox ueber HTML und LibreOffice laufen.
_CONTAINERFORMATE = frozenset({"docx", "odt", "epub", "fb2"})


def _sandbox_aktiv() -> bool:
    return os.environ.get("PANDOC_SANDBOX", "1").strip().lower() not in {
        "0", "false", "no", "nein", "aus"
    }


# Schreibfilter, die ein vollstaendiges Dokument mit Kopf brauchen.
_STANDALONE = {
    "html5", "latex", "epub3", "fb2", "docx", "odt", "rtf", "man", "docbook5",
    "opml", "ipynb", "typst",
}


@lru_cache(maxsize=1)
def _pandoc_major() -> int:
    """Hauptversion von Pandoc, fuer die Wahl der Optionsnamen."""
    try:
        output = run_command(["pandoc", "--version"], timeout=20, label="Pandoc")
    except Exception:
        return 3
    match = re.search(r"pandoc\s+(\d+)\.", output)
    return int(match.group(1)) if match else 3


class PandocEngine(Engine):
    name = "pandoc"
    label = "Pandoc"
    requires = "pandoc"
    cost = 12
    source_exts = tuple(READERS)
    target_exts = tuple(WRITERS)

    def edge_cost(self, src: str, dst: str) -> int:
        # Fuer Office-Dokumente ist LibreOffice originaltreuer; Pandoc soll
        # dort nur einspringen, wenn kein anderer Weg existiert.
        if src in {"docx", "odt"} and dst in {"docx", "odt", "rtf"}:
            return self.cost + 30
        if src == "csv":
            return self.cost + 10
        return self.cost

    def supports(self, src: str, dst: str) -> bool:
        if not super().supports(src, dst):
            return False
        # JSON ist bei Pandoc der abstrakte Syntaxbaum, kein Datenformat.
        # Als Ziel waere das fuer Anwenderinnen und Anwender irrefuehrend.
        if src == "json" and dst not in {"md", "html", "txt", "docx", "odt"}:
            return False
        # Containerformate liessen sich nur ohne Sandbox erzeugen. Der Weg
        # ueber HTML und LibreOffice fuehrt zum selben Ziel, ohne dass Pandoc
        # auf das Dateisystem zugreifen darf.
        if dst in _CONTAINERFORMATE and _sandbox_aktiv():
            return False
        return True

    def convert(self, src: Path, dst: Path, src_ext: str, dst_ext: str, ctx: StepContext) -> Path:
        reader = READERS.get(src_ext)
        writer = WRITERS.get(dst_ext)
        if reader is None or writer is None:
            raise ConversionError(f"Pandoc kennt den Weg {src_ext.upper()} nach {dst_ext.upper()} nicht.")

        argv = ["pandoc", "--from", reader, "--to", writer, "--output", str(dst)]

        if writer in _STANDALONE:
            argv.append("--standalone")
        if writer == "html5":
            # Alles einbetten, damit die erzeugte Seite offline funktioniert
            # und keine Verbindung nach aussen aufbaut. Pandoc 2 kennt die
            # Option noch unter ihrem alten Namen.
            argv.append("--embed-resources" if _pandoc_major() >= 3 else "--self-contained")
            argv.append("--wrap=preserve")
        if writer in {"epub3", "fb2"}:
            argv.append("--toc")
        if dst_ext == "md":
            argv.append("--wrap=none")

        title = ctx.opt_str("title") or src.stem
        if writer in _STANDALONE:
            argv += ["--metadata", f"title={title}"]

        # Die Sandbox verbietet Pandoc jeden Datei- und Netzwerkzugriff
        # ausser der Eingabedatei. Das verhindert, dass ein praepariertes
        # Dokument ueber einen Bild- oder Include-Verweis den Inhalt einer
        # Serverdatei in das Ergebnis einbettet.
        if dst_ext not in _CONTAINERFORMATE:
            argv.append("--sandbox")

        argv.append(str(src))
        run_command(argv, timeout=ctx.timeout, cwd=src.parent, label="Pandoc")
        if not dst.exists() or dst.stat().st_size == 0:
            raise ConversionError("Pandoc hat keine verwertbare Ausgabedatei erzeugt.")
        return dst


def engines() -> list[Engine]:
    return [PandocEngine()]
