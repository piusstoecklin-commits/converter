"""Engine fuer Schriftdateien (TrueType, OpenType, WOFF, WOFF2)."""

from __future__ import annotations

from pathlib import Path

from app.engines.base import ConversionError, Engine, StepContext

FONT_EXTS = ("ttf", "otf", "woff", "woff2")


class FontEngine(Engine):
    name = "fonttools"
    label = "fontTools"
    cost = 8
    source_exts = FONT_EXTS
    target_exts = FONT_EXTS

    def convert(self, src: Path, dst: Path, src_ext: str, dst_ext: str, ctx: StepContext) -> Path:
        try:
            from fontTools.ttLib import TTFont
        except ImportError as exc:  # pragma: no cover
            raise ConversionError("Das Modul fontTools ist nicht installiert.", str(exc)) from exc

        try:
            font = TTFont(str(src))
        except Exception as exc:
            raise ConversionError("Die Schriftdatei konnte nicht gelesen werden.", str(exc)) from exc

        try:
            # Web-Schriften tragen ihre Kompression im Container; beim Wechsel
            # muss sie zurueckgesetzt bzw. neu gesetzt werden.
            font.flavor = {"woff": "woff", "woff2": "woff2"}.get(dst_ext)
            if dst_ext == "woff2":
                try:
                    import brotli  # noqa: F401
                except ImportError as exc:
                    raise ConversionError(
                        "Fuer WOFF2 wird das Modul brotli benoetigt.", str(exc)
                    ) from exc
            font.save(str(dst))
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(
                f"Die Schrift konnte nicht als {dst_ext.upper()} gespeichert werden.", str(exc)
            ) from exc
        finally:
            font.close()

        if not dst.exists() or dst.stat().st_size == 0:
            raise ConversionError("Es wurde keine Schriftdatei erzeugt.")
        return dst


def engines() -> list[Engine]:
    return [FontEngine()]
