"""Engine zum Umpacken von Archiven.

Beim Entpacken wird jeder Eintrag geprueft: Pfade, die aus dem Zielordner
herausfuehren ("Zip Slip"), symbolische Verweise und uebergrosse Inhalte
("Zip-Bombe") werden abgewiesen.
"""

from __future__ import annotations

import bz2
import gzip
import lzma
import os
import shutil
import tarfile
import zipfile
from pathlib import Path

from app.engines.base import ConversionError, Engine, StepContext, run_command

ARCHIVE_IN = ("zip", "tar", "tgz", "tbz2", "txz", "7z", "rar", "gz", "bz2", "xz", "iso")
ARCHIVE_OUT = ("zip", "tar", "tgz", "tbz2", "txz", "7z")

# Grenzen gegen Archive, die beim Entpacken explodieren.
MAX_TOTAL_BYTES = 8 * 1024 * 1024 * 1024
MAX_ENTRIES = 20_000
MAX_RATIO = 200


class ArchiveEngine(Engine):
    name = "archive"
    label = "Archivumpackung"
    cost = 9
    source_exts = ARCHIVE_IN
    target_exts = ARCHIVE_OUT

    def convert(self, src: Path, dst: Path, src_ext: str, dst_ext: str, ctx: StepContext) -> Path:
        workdir = ctx.scratch / "archiv"
        if workdir.exists():
            shutil.rmtree(workdir, ignore_errors=True)
        workdir.mkdir(parents=True, exist_ok=True)

        self._extract(src, src_ext, workdir, ctx)
        entries = sorted(p for p in workdir.rglob("*") if p.is_file())
        if not entries:
            raise ConversionError("Das Archiv enthaelt keine Dateien.")
        ctx.note(f"{len(entries)} Datei(en) umgepackt.")
        self._pack(workdir, dst, dst_ext, ctx)
        shutil.rmtree(workdir, ignore_errors=True)
        return dst

    # -- Entpacken ---------------------------------------------------
    def _extract(self, src: Path, src_ext: str, target: Path, ctx: StepContext) -> None:
        if src_ext == "zip":
            self._extract_zip(src, target)
        elif src_ext in {"tar", "tgz", "tbz2", "txz"}:
            self._extract_tar(src, target)
        elif src_ext in {"gz", "bz2", "xz"}:
            self._extract_single(src, src_ext, target)
        elif src_ext == "7z":
            self._extract_7z(src, target, ctx)
        elif src_ext == "rar":
            self._extract_rar(src, target, ctx)
        elif src_ext == "iso":
            self._extract_iso(src, target, ctx)
        else:
            raise ConversionError(f"{src_ext.upper()} kann nicht entpackt werden.")

    @staticmethod
    def _safe_join(target: Path, name: str) -> Path:
        candidate = (target / name).resolve()
        base = target.resolve()
        if candidate != base and base not in candidate.parents:
            raise ConversionError(
                "Das Archiv enthaelt einen Eintrag ausserhalb des Zielordners und wurde abgewiesen.",
                f"Auffaelliger Eintrag: {name}",
            )
        return candidate

    def _extract_zip(self, src: Path, target: Path) -> None:
        with zipfile.ZipFile(src) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ENTRIES:
                raise ConversionError(f"Das Archiv enthaelt mehr als {MAX_ENTRIES} Eintraege.")
            total = 0
            for info in infos:
                if info.is_dir():
                    continue
                total += info.file_size
                if total > MAX_TOTAL_BYTES:
                    raise ConversionError("Der entpackte Inhalt ueberschreitet die zulaessige Groesse.")
                if info.compress_size > 0 and info.file_size / info.compress_size > MAX_RATIO:
                    raise ConversionError(
                        "Das Archiv wirkt wie eine Dekompressionsbombe und wurde abgewiesen.",
                        f"Auffaelliger Eintrag: {info.filename}",
                    )
                destination = self._safe_join(target, info.filename)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, destination.open("wb") as sink:
                    shutil.copyfileobj(source, sink, length=1024 * 1024)

    def _extract_tar(self, src: Path, target: Path) -> None:
        with tarfile.open(src, "r:*") as archive:
            total = 0
            count = 0
            for member in archive:
                count += 1
                if count > MAX_ENTRIES:
                    raise ConversionError(f"Das Archiv enthaelt mehr als {MAX_ENTRIES} Eintraege.")
                if member.issym() or member.islnk():
                    # Verweise koennen auf Serverpfade zeigen und werden verworfen.
                    continue
                if not member.isfile() and not member.isdir():
                    continue
                total += member.size
                if total > MAX_TOTAL_BYTES:
                    raise ConversionError("Der entpackte Inhalt ueberschreitet die zulaessige Groesse.")
                destination = self._safe_join(target, member.name)
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                with extracted, destination.open("wb") as sink:
                    shutil.copyfileobj(extracted, sink, length=1024 * 1024)

    def _extract_single(self, src: Path, src_ext: str, target: Path) -> None:
        openers = {"gz": gzip.open, "bz2": bz2.open, "xz": lzma.open}
        stem = src.stem or "inhalt"
        destination = target / stem
        written = 0
        with openers[src_ext](src, "rb") as source, destination.open("wb") as sink:
            while chunk := source.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_TOTAL_BYTES:
                    raise ConversionError("Der entpackte Inhalt ueberschreitet die zulaessige Groesse.")
                sink.write(chunk)

    def _extract_7z(self, src: Path, target: Path, ctx: StepContext) -> None:
        try:
            import py7zr
        except ImportError as exc:  # pragma: no cover
            raise ConversionError("Das Modul py7zr ist nicht installiert.", str(exc)) from exc
        try:
            with py7zr.SevenZipFile(src, mode="r") as archive:
                names = archive.getnames()
                if len(names) > MAX_ENTRIES:
                    raise ConversionError(f"Das Archiv enthaelt mehr als {MAX_ENTRIES} Eintraege.")
                for name in names:
                    self._safe_join(target, name)
                archive.extractall(path=str(target))
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError("Das 7z-Archiv konnte nicht entpackt werden.", str(exc)) from exc

    def _extract_rar(self, src: Path, target: Path, ctx: StepContext) -> None:
        try:
            import rarfile
        except ImportError as exc:  # pragma: no cover
            raise ConversionError("Das Modul rarfile ist nicht installiert.", str(exc)) from exc
        try:
            with rarfile.RarFile(src) as archive:
                infos = archive.infolist()
                if len(infos) > MAX_ENTRIES:
                    raise ConversionError(f"Das Archiv enthaelt mehr als {MAX_ENTRIES} Eintraege.")
                for info in infos:
                    self._safe_join(target, info.filename)
                archive.extractall(path=str(target))
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(
                "Das RAR-Archiv konnte nicht entpackt werden.",
                f"{exc} - moeglicherweise fehlt das Programm 'unrar' oder das Archiv ist verschluesselt.",
            ) from exc

    def _extract_iso(self, src: Path, target: Path, ctx: StepContext) -> None:
        run_command(["7z", "x", "-y", f"-o{target}", str(src)], timeout=ctx.timeout, label="7z")

    # -- Packen ------------------------------------------------------
    def _pack(self, source_dir: Path, dst: Path, dst_ext: str, ctx: StepContext) -> None:
        if dst_ext == "zip":
            level = max(0, min(9, ctx.opt_int("compression_level", 6)))
            with zipfile.ZipFile(dst, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=level) as archive:
                for path in sorted(source_dir.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(source_dir).as_posix())
            return

        if dst_ext in {"tar", "tgz", "tbz2", "txz"}:
            modes = {"tar": "w", "tgz": "w:gz", "tbz2": "w:bz2", "txz": "w:xz"}
            with tarfile.open(dst, modes[dst_ext]) as archive:
                for path in sorted(source_dir.rglob("*")):
                    if path.is_file():
                        archive.add(path, arcname=path.relative_to(source_dir).as_posix())
            return

        if dst_ext == "7z":
            import py7zr

            with py7zr.SevenZipFile(dst, mode="w") as archive:
                for path in sorted(source_dir.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(source_dir).as_posix())
            return

        raise ConversionError(f"{dst_ext.upper()} kann nicht geschrieben werden.")


def engines() -> list[Engine]:
    return [ArchiveEngine()]
