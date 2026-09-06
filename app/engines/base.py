"""Basisklassen und Hilfsfunktionen fuer alle Konvertierungs-Engines."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from app import formats

log = logging.getLogger("converter.engine")


class ConversionError(RuntimeError):
    """Fachlicher Fehler waehrend einer Konvertierung."""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


@dataclass
class StepContext:
    """Umgebung fuer einen einzelnen Konvertierungsschritt."""

    scratch: Path
    timeout: int
    options: dict[str, object] = field(default_factory=dict)
    log_lines: list[str] = field(default_factory=list)

    def note(self, message: str) -> None:
        self.log_lines.append(message)

    def opt(self, key: str, default: object = None) -> object:
        return self.options.get(key, default)

    def opt_str(self, key: str, default: str = "") -> str:
        value = self.options.get(key, default)
        return str(value) if value is not None else default

    def opt_int(self, key: str, default: int) -> int:
        value = self.options.get(key, default)
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default

    def opt_bool(self, key: str, default: bool = False) -> bool:
        value = self.options.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "ja"}
        return bool(value)


def run_command(
    argv: Sequence[str],
    *,
    timeout: int,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    label: str = "",
    ok_returncodes: Sequence[int] = (0,),
) -> str:
    """Fuehrt ein externes Programm aus.

    Es wird bewusst niemals eine Shell benutzt: Argumente kommen als Liste,
    damit Dateinamen keine Befehle einschleusen koennen.
    """

    binary = argv[0]
    if shutil.which(binary) is None:
        raise ConversionError(
            f"Das Programm '{binary}' ist auf diesem Server nicht installiert.",
            "Bitte das Container-Image pruefen.",
        )

    safe_env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        # Kein Netzwerkzugriff durch Bibliotheken, die Proxies auswerten.
        "no_proxy": "*",
        "NO_PROXY": "*",
    }
    if env:
        safe_env.update(env)

    log.debug("Starte %s", " ".join(argv))
    try:
        proc = subprocess.run(  # noqa: S603 - feste Argumentliste, keine Shell
            list(argv),
            cwd=str(cwd) if cwd else None,
            env=safe_env,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ConversionError(
            f"Zeitlimit von {timeout} Sekunden ueberschritten"
            f"{f' ({label})' if label else ''}.",
            "Die Datei ist zu gross oder zu komplex fuer die eingestellte Grenze.",
        ) from exc
    except OSError as exc:
        raise ConversionError(f"Programm '{binary}' konnte nicht gestartet werden.", str(exc)) from exc

    stdout = proc.stdout.decode("utf-8", "replace")
    stderr = proc.stderr.decode("utf-8", "replace")
    if proc.returncode not in ok_returncodes:
        detail = (stderr or stdout).strip()
        raise ConversionError(
            f"{label or binary} ist mit Fehlercode {proc.returncode} beendet worden.",
            detail[-4000:],
        )
    return stdout


def unique_path(directory: Path, stem: str, ext: str) -> Path:
    """Liefert einen freien Dateinamen im Zielverzeichnis."""
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"{stem}.{ext}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"{stem}-{counter}.{ext}"
        counter += 1
    return candidate


class Engine:
    """Ein Konverter zwischen zwei Formatmengen.

    ``cost`` bewertet den Weg: niedrig = verlustarm und schnell. Die
    Wegesuche bevorzugt guenstige Kanten, damit z. B. DOCX -> PDF direkt
    ueber LibreOffice laeuft und nicht ueber einen Umweg.
    """

    name: str = "engine"
    label: str = "Konverter"
    cost: int = 10
    #: Binary, dessen Vorhandensein die Engine benoetigt (optional).
    requires: str | None = None

    #: Endungen, die gelesen werden koennen.
    source_exts: tuple[str, ...] = ()
    #: Endungen, die geschrieben werden koennen.
    target_exts: tuple[str, ...] = ()

    def __init__(self) -> None:
        self._sources = formats.expand(*self.source_exts)
        self._targets = formats.expand(*self.target_exts)

    # -- Faehigkeiten ------------------------------------------------
    def sources(self) -> set[str]:
        return set(self._sources)

    def targets(self) -> set[str]:
        return set(self._targets)

    def supports(self, src: str, dst: str) -> bool:
        return src != dst and src in self._sources and dst in self._targets

    def edge_cost(self, src: str, dst: str) -> int:
        return self.cost

    def available(self) -> bool:
        return self.requires is None or shutil.which(self.requires) is not None

    # -- Ausfuehrung -------------------------------------------------
    def convert(self, src: Path, dst: Path, src_ext: str, dst_ext: str, ctx: StepContext) -> Path:
        """Konvertiert ``src`` nach ``dst`` und gibt den erzeugten Pfad zurueck."""
        raise NotImplementedError

    def describe(self, src: str, dst: str) -> str:
        return f"{src.upper()} nach {dst.upper()} ueber {self.label}"

    def __repr__(self) -> str:  # pragma: no cover - Debugging
        return f"<Engine {self.name}>"
