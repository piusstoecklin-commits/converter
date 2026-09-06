"""Bild-Engines.

Fuer die haeufigen Rasterformate wird Pillow benutzt: schnell, ohne externe
Delegates und damit mit deutlich kleinerer Angriffsflaeche. ImageMagick
uebernimmt die Sonderfaelle (Vektor, HDR, Kamerarohdaten, exotische Formate).
"""

from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path

from app.engines.base import ConversionError, Engine, StepContext, run_command

try:  # pragma: no cover - haengt vom Image ab
    import pillow_heif

    pillow_heif.register_heif_opener()
    _HEIF_READY = True
except Exception:  # pragma: no cover
    _HEIF_READY = False


# Formate, die Pillow zuverlaessig ohne Zusatzbibliotheken beherrscht.
_PILLOW_READ = (
    "jpg", "png", "gif", "bmp", "tiff", "webp", "ico", "ppm", "pgm", "pbm",
    "tga", "pcx", "jp2", "psd", "dds", "xpm",
)
_PILLOW_WRITE = ("jpg", "png", "gif", "bmp", "tiff", "webp", "ico", "ppm", "tga", "jp2", "pdf")

_PILLOW_SAVE_FORMAT = {
    "jpg": "JPEG",
    "png": "PNG",
    "gif": "GIF",
    "bmp": "BMP",
    "tiff": "TIFF",
    "webp": "WEBP",
    "ico": "ICO",
    "ppm": "PPM",
    "tga": "TGA",
    "jp2": "JPEG2000",
    "pdf": "PDF",
}

# Zielformate ohne Alphakanal: Transparenz muss auf einen Hintergrund gelegt
# werden, sonst wird sie schwarz.
_NO_ALPHA = {"jpg", "pdf", "ppm", "bmp"}


class PillowEngine(Engine):
    name = "pillow"
    label = "Bildverarbeitung (Pillow)"
    cost = 6
    source_exts = _PILLOW_READ + (("heic",) if _HEIF_READY else ())
    target_exts = _PILLOW_WRITE

    def edge_cost(self, src: str, dst: str) -> int:
        if dst == "ico":
            return self.cost + 8
        return self.cost

    def convert(self, src: Path, dst: Path, src_ext: str, dst_ext: str, ctx: StepContext) -> Path:
        from PIL import Image, ImageOps, ImageSequence

        Image.MAX_IMAGE_PIXELS = 512_000_000  # Schutz vor Dekompressionsbomben

        try:
            with Image.open(src) as image:
                image.load()
                frames = [f.copy() for f in ImageSequence.Iterator(image)] if dst_ext == "gif" else None
                prepared = self._prepare(image, dst_ext, ctx, ImageOps)
                self._save(prepared, dst, dst_ext, ctx, frames)
        except ConversionError:
            raise
        except Exception as exc:  # Pillow wirft sehr unterschiedliche Fehler
            raise ConversionError(
                f"Das Bild konnte nicht als {dst_ext.upper()} gespeichert werden.", str(exc)
            ) from exc
        return dst

    def _prepare(self, image, dst_ext: str, ctx: StepContext, ImageOps):
        from PIL import Image

        # Aufnahmeorientierung aus den EXIF-Daten anwenden, damit Hochformat-
        # Fotos nicht gedreht landen.
        try:
            image = ImageOps.exif_transpose(image) or image
        except Exception:
            pass

        max_edge = ctx.opt_int("max_edge", 0)
        if max_edge > 0 and max(image.size) > max_edge:
            image.thumbnail((max_edge, max_edge), Image.LANCZOS)

        if dst_ext in _NO_ALPHA and image.mode in {"RGBA", "LA", "P", "PA"}:
            converted = image.convert("RGBA")
            background = Image.new("RGB", converted.size, ctx.opt_str("background", "#FFFFFF") or "#FFFFFF")
            background.paste(converted, mask=converted.split()[-1])
            image = background
        elif dst_ext in _NO_ALPHA and image.mode not in {"RGB", "L", "CMYK"}:
            image = image.convert("RGB")
        elif dst_ext == "png" and image.mode == "CMYK":
            image = image.convert("RGB")
        elif dst_ext == "webp" and image.mode not in {"RGB", "RGBA", "L"}:
            image = image.convert("RGBA")
        elif dst_ext == "ico" and image.mode != "RGBA":
            image = image.convert("RGBA")
        return image

    def _save(self, image, dst: Path, dst_ext: str, ctx: StepContext, frames) -> None:
        save_format = _PILLOW_SAVE_FORMAT[dst_ext]
        params: dict[str, object] = {}
        quality = ctx.opt_int("quality", 88)

        if dst_ext in {"jpg", "webp"}:
            params["quality"] = max(1, min(100, quality))
        if dst_ext == "jpg":
            params["optimize"] = True
            params["progressive"] = True
            params["subsampling"] = 0 if quality >= 90 else 2
        if dst_ext == "png":
            params["optimize"] = True
            params["compress_level"] = 9 if ctx.opt_bool("optimize", True) else 6
        if dst_ext == "tiff":
            params["compression"] = ctx.opt_str("tiff_compression", "tiff_deflate") or "tiff_deflate"
        if dst_ext == "webp":
            params["method"] = 4
            if ctx.opt_bool("lossless", False):
                params["lossless"] = True
        if dst_ext == "ico":
            params["sizes"] = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        if dst_ext == "pdf":
            params["resolution"] = float(ctx.opt_int("dpi", 150))
        if dst_ext == "gif" and frames and len(frames) > 1:
            first, *rest = [f.convert("P", palette=1) for f in frames]
            first.save(dst, format="GIF", save_all=True, append_images=rest, loop=0)
            return

        image.save(dst, format=save_format, **params)


_MAGICK_READ = (
    "jpg", "png", "gif", "bmp", "tiff", "webp", "avif", "jxl", "heic", "ico",
    "jp2", "psd", "xcf", "tga", "pcx", "ppm", "pgm", "pbm", "dds", "exr",
    "hdr", "xpm", "svg", "wmf", "emf", "eps", "ps", "pdf",
)
_MAGICK_WRITE = (
    "jpg", "png", "gif", "bmp", "tiff", "webp", "avif", "jxl", "heic", "ico",
    "jp2", "psd", "tga", "pcx", "ppm", "pgm", "pbm", "dds", "exr", "hdr",
    "xpm", "pdf", "eps", "ps",
)


@lru_cache(maxsize=1)
def _magick_binary() -> str | None:
    """ImageMagick 7 bringt 'magick' mit, Version 6 nur 'convert'."""
    for candidate in ("magick", "convert"):
        if shutil.which(candidate):
            return candidate
    return None


class ImageMagickEngine(Engine):
    name = "imagemagick"
    label = "ImageMagick"
    cost = 14
    source_exts = _MAGICK_READ
    target_exts = _MAGICK_WRITE

    def available(self) -> bool:
        return _magick_binary() is not None

    def edge_cost(self, src: str, dst: str) -> int:
        # Mehrseitige Quellen auf ein Einzelbild abzubilden ist verlustbehaftet.
        if src == "pdf" and dst != "pdf":
            return self.cost + 10
        return self.cost

    def convert(self, src: Path, dst: Path, src_ext: str, dst_ext: str, ctx: StepContext) -> Path:
        binary = _magick_binary()
        if binary is None:
            raise ConversionError("ImageMagick ist auf diesem Server nicht installiert.")

        density = ctx.opt_int("dpi", 200)
        argv: list[str] = [binary]

        # Bei Vektor- und Seitenformaten bestimmt die Aufloesung die Qualitaet;
        # sie muss vor der Eingabedatei stehen.
        if src_ext in {"svg", "pdf", "eps", "ps", "wmf", "emf"}:
            argv += ["-density", str(max(36, min(1200, density)))]

        source_spec = str(src)
        page = ctx.opt_int("page", 0)
        if src_ext in {"pdf", "tiff", "gif", "psd"} and dst_ext not in {"pdf", "tiff", "gif"}:
            # Ohne Seitenangabe erzeugt ImageMagick eine Datei je Seite.
            source_spec = f"{src}[{max(0, page)}]"

        argv += [source_spec, "-auto-orient"]

        if src_ext in {"svg", "pdf", "eps", "ps"} and dst_ext not in {"pdf", "eps", "ps"}:
            argv += ["-background", ctx.opt_str("background", "white") or "white", "-flatten"]
        if dst_ext in {"jpg", "ppm", "bmp"}:
            argv += ["-background", ctx.opt_str("background", "white") or "white", "-alpha", "remove", "-alpha", "off"]

        max_edge = ctx.opt_int("max_edge", 0)
        if max_edge > 0:
            argv += ["-resize", f"{max_edge}x{max_edge}>"]

        quality = ctx.opt_int("quality", 88)
        if dst_ext in {"jpg", "webp", "avif", "heic", "jxl", "jp2"}:
            argv += ["-quality", str(max(1, min(100, quality)))]

        if ctx.opt_bool("strip_metadata", True):
            argv.append("-strip")

        # Grenzen gegen Dekompressionsbomben.
        argv += ["-limit", "memory", "1GiB", "-limit", "map", "2GiB", "-limit", "disk", "4GiB"]
        argv.append(str(dst))

        run_command(argv, timeout=ctx.timeout, cwd=src.parent, label="ImageMagick")
        if not dst.exists():
            # ImageMagick haengt bei mehrseitigen Ausgaben "-0" an den Namen.
            alternative = dst.with_name(f"{dst.stem}-0{dst.suffix}")
            if alternative.exists():
                shutil.move(str(alternative), str(dst))
            else:
                raise ConversionError(f"ImageMagick hat keine {dst_ext.upper()}-Datei erzeugt.")
        return dst


_RAW_EXTS = ("cr2", "nef", "arw", "dng", "orf", "raf")


class RawPhotoEngine(Engine):
    """Kamerarohdaten ueber LibRaw in ein TIFF entwickeln."""

    name = "libraw"
    label = "LibRaw (Kamerarohdaten)"
    requires = "dcraw_emu"
    cost = 20
    source_exts = _RAW_EXTS
    target_exts = ("tiff",)

    def convert(self, src: Path, dst: Path, src_ext: str, dst_ext: str, ctx: StepContext) -> Path:
        workdir = ctx.scratch / "raw"
        workdir.mkdir(parents=True, exist_ok=True)
        staged = workdir / src.name
        shutil.copy2(src, staged)
        # -T = TIFF, -w = Weissabgleich der Kamera, -q 3 = beste Interpolation.
        run_command(
            ["dcraw_emu", "-T", "-w", "-q", "3", str(staged)],
            timeout=ctx.timeout,
            cwd=workdir,
            label="LibRaw",
        )
        produced = next((p for p in workdir.glob(f"{staged.name}*.tiff")), None)
        if produced is None:
            produced = next((p for p in workdir.glob("*.tiff")), None)
        if produced is None:
            raise ConversionError("Das Rohbild konnte nicht entwickelt werden.")
        shutil.move(str(produced), str(dst))
        return dst


def engines() -> list[Engine]:
    return [PillowEngine(), ImageMagickEngine(), RawPhotoEngine()]
