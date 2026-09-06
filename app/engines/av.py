"""FFmpeg-Engines fuer Video, Audio und Untertitel."""

from __future__ import annotations

from pathlib import Path

from app.engines.base import ConversionError, Engine, StepContext, run_command

VIDEO_IN = (
    "mp4", "mkv", "webm", "mov", "avi", "wmv", "flv", "mpg", "m4v", "3gp",
    "ogv", "ts", "mts", "vob", "asf", "gif",
)
VIDEO_OUT = ("mp4", "mkv", "webm", "mov", "avi", "wmv", "flv", "mpg", "m4v", "3gp", "ogv", "ts", "asf")

AUDIO_IN = (
    "mp3", "wav", "flac", "ogg", "opus", "m4a", "aac", "wma", "aiff", "amr",
    "ac3", "mka", "au", "caf", "ape", "wv",
)
AUDIO_OUT = ("mp3", "wav", "flac", "ogg", "opus", "m4a", "aac", "wma", "aiff", "ac3", "mka", "au", "caf", "wv")

SUBTITLE_IN = ("srt", "vtt", "ass")
SUBTITLE_OUT = ("srt", "vtt", "ass")

# Zielcontainer -> (Video-Codec, Audio-Codec, zusaetzliche Argumente)
VIDEO_PROFILES: dict[str, tuple[str, str, list[str]]] = {
    "mp4": ("libx264", "aac", ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]),
    "m4v": ("libx264", "aac", ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]),
    "mov": ("libx264", "aac", ["-pix_fmt", "yuv420p"]),
    "mkv": ("libx264", "aac", ["-pix_fmt", "yuv420p"]),
    "webm": ("libvpx-vp9", "libopus", ["-pix_fmt", "yuv420p", "-row-mt", "1", "-b:v", "0"]),
    "ogv": ("libtheora", "libvorbis", ["-q:v", "7"]),
    "avi": ("mpeg4", "libmp3lame", ["-vtag", "XVID", "-q:v", "4"]),
    "wmv": ("msmpeg4v3", "wmav2", ["-q:v", "4"]),
    "asf": ("msmpeg4v3", "wmav2", ["-q:v", "4"]),
    "flv": ("flv", "libmp3lame", ["-ar", "44100"]),
    "mpg": ("mpeg2video", "mp2", ["-q:v", "4"]),
    "3gp": ("mpeg4", "aac", ["-ar", "16000", "-ac", "1", "-q:v", "6"]),
    "ts": ("libx264", "aac", ["-pix_fmt", "yuv420p", "-bsf:v", "h264_mp4toannexb"]),
}

# Zielformat -> (Codec, zusaetzliche Argumente)
AUDIO_PROFILES: dict[str, tuple[str, list[str]]] = {
    "mp3": ("libmp3lame", ["-q:a", "2"]),
    "wav": ("pcm_s16le", []),
    "flac": ("flac", ["-compression_level", "8"]),
    "ogg": ("libvorbis", ["-q:a", "5"]),
    "opus": ("libopus", ["-b:a", "128k"]),
    "m4a": ("aac", ["-b:a", "192k"]),
    "aac": ("aac", ["-b:a", "192k"]),
    "wma": ("wmav2", ["-b:a", "192k"]),
    "aiff": ("pcm_s16be", []),
    "ac3": ("ac3", ["-b:a", "192k"]),
    "mka": ("flac", []),
    "au": ("pcm_s16be", []),
    "caf": ("pcm_s16le", []),
    "wv": ("wavpack", []),
}

# Nur lokale Dateien zulassen. Verhindert, dass eine praeparierte Playlist
# den Server dazu bringt, Adressen im internen Netz abzurufen.
_SAFE_PROTOCOLS = ["-protocol_whitelist", "file,crypto,data"]


def _base_argv() -> list[str]:
    return ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *_SAFE_PROTOCOLS]


class VideoEngine(Engine):
    name = "ffmpeg-video"
    label = "FFmpeg (Video)"
    requires = "ffmpeg"
    cost = 18
    source_exts = VIDEO_IN
    target_exts = VIDEO_OUT

    def convert(self, src: Path, dst: Path, src_ext: str, dst_ext: str, ctx: StepContext) -> Path:
        video_codec, audio_codec, extra = VIDEO_PROFILES[dst_ext]
        argv = _base_argv() + ["-i", str(src)]

        crf = ctx.opt_int("crf", 23)
        preset = ctx.opt_str("preset", "medium") or "medium"

        argv += ["-c:v", video_codec]
        if video_codec in {"libx264", "libvpx-vp9"}:
            argv += ["-crf", str(max(0, min(51, crf)))]
        if video_codec == "libx264":
            argv += ["-preset", preset]

        if src_ext == "gif":
            argv += ["-an"]
        else:
            argv += ["-c:a", audio_codec]

        argv += extra

        scale = ctx.opt_int("max_height", 0)
        if scale > 0:
            argv += ["-vf", f"scale=-2:'min({scale},ih)'"]

        argv += ["-map_metadata", "-1" if ctx.opt_bool("strip_metadata", False) else "0"]
        argv.append(str(dst))
        run_command(argv, timeout=ctx.timeout, label="FFmpeg")
        self._check(dst, dst_ext)
        return dst

    @staticmethod
    def _check(dst: Path, dst_ext: str) -> None:
        if not dst.exists() or dst.stat().st_size == 0:
            raise ConversionError(f"FFmpeg hat keine verwertbare {dst_ext.upper()}-Datei erzeugt.")


class AudioEngine(Engine):
    name = "ffmpeg-audio"
    label = "FFmpeg (Audio)"
    requires = "ffmpeg"
    cost = 14
    source_exts = AUDIO_IN + VIDEO_IN
    target_exts = AUDIO_OUT

    def edge_cost(self, src: str, dst: str) -> int:
        # Tonspur aus einem Video zu ziehen ist gewollt, aber nie ein
        # sinnvoller Zwischenschritt auf dem Weg zu einem anderen Ziel.
        if src in VIDEO_IN:
            return self.cost + 20
        return self.cost

    def convert(self, src: Path, dst: Path, src_ext: str, dst_ext: str, ctx: StepContext) -> Path:
        codec, extra = AUDIO_PROFILES[dst_ext]
        argv = _base_argv() + ["-i", str(src), "-vn", "-c:a", codec, *extra]

        bitrate = ctx.opt_str("audio_bitrate")
        if bitrate and codec not in {"pcm_s16le", "pcm_s16be", "flac", "wavpack"}:
            argv += ["-b:a", bitrate]
        sample_rate = ctx.opt_int("sample_rate", 0)
        if sample_rate > 0:
            argv += ["-ar", str(sample_rate)]
        channels = ctx.opt_int("channels", 0)
        if channels > 0:
            argv += ["-ac", str(channels)]

        argv.append(str(dst))
        run_command(argv, timeout=ctx.timeout, label="FFmpeg")
        VideoEngine._check(dst, dst_ext)
        return dst


class VideoThumbnailEngine(Engine):
    """Einzelbild aus einem Video als Vorschau."""

    name = "ffmpeg-thumbnail"
    label = "FFmpeg (Standbild)"
    requires = "ffmpeg"
    cost = 45
    source_exts = VIDEO_IN
    target_exts = ("png", "jpg")

    def convert(self, src: Path, dst: Path, src_ext: str, dst_ext: str, ctx: StepContext) -> Path:
        timestamp = ctx.opt_str("timestamp", "00:00:01") or "00:00:01"
        argv = _base_argv() + ["-ss", timestamp, "-i", str(src), "-frames:v", "1", "-q:v", "2", str(dst)]
        try:
            run_command(argv, timeout=ctx.timeout, label="FFmpeg")
        except ConversionError:
            # Sehr kurze Videos haben bei 1 Sekunde kein Bild mehr.
            argv = _base_argv() + ["-i", str(src), "-frames:v", "1", "-q:v", "2", str(dst)]
            run_command(argv, timeout=ctx.timeout, label="FFmpeg")
        VideoEngine._check(dst, dst_ext)
        return dst


class AnimationEngine(Engine):
    """Kurze Videosequenz als animiertes GIF."""

    name = "ffmpeg-gif"
    label = "FFmpeg (GIF-Animation)"
    requires = "ffmpeg"
    # Teurer als das Standbild, damit Wege zu anderen Bildformaten nicht
    # unnoetig ueber ein animiertes GIF laufen.
    cost = 48
    source_exts = VIDEO_IN
    target_exts = ("gif",)

    def convert(self, src: Path, dst: Path, src_ext: str, dst_ext: str, ctx: StepContext) -> Path:
        fps = max(1, min(30, ctx.opt_int("fps", 12)))
        width = max(120, min(1920, ctx.opt_int("gif_width", 640)))
        duration = ctx.opt_str("duration", "")
        palette = ctx.scratch / "gif-palette.png"

        chain = f"fps={fps},scale={width}:-1:flags=lanczos"
        pre: list[str] = ["-t", duration] if duration else []

        run_command(
            _base_argv() + ["-i", str(src), *pre, "-vf", f"{chain},palettegen=stats_mode=diff", str(palette)],
            timeout=ctx.timeout,
            label="FFmpeg (Palette)",
        )
        run_command(
            _base_argv()
            + ["-i", str(src), "-i", str(palette), *pre,
               "-lavfi", f"{chain}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3", str(dst)],
            timeout=ctx.timeout,
            label="FFmpeg (GIF)",
        )
        VideoEngine._check(dst, dst_ext)
        return dst


class SubtitleEngine(Engine):
    name = "ffmpeg-subtitle"
    label = "FFmpeg (Untertitel)"
    requires = "ffmpeg"
    cost = 8
    source_exts = SUBTITLE_IN + VIDEO_IN
    target_exts = SUBTITLE_OUT

    def edge_cost(self, src: str, dst: str) -> int:
        return self.cost + (30 if src in VIDEO_IN else 0)

    def convert(self, src: Path, dst: Path, src_ext: str, dst_ext: str, ctx: StepContext) -> Path:
        argv = _base_argv() + ["-i", str(src)]
        if src_ext in VIDEO_IN:
            # Nur die erste eingebettete Untertitelspur uebernehmen.
            argv += ["-map", "0:s:0"]
        argv.append(str(dst))
        try:
            run_command(argv, timeout=ctx.timeout, label="FFmpeg")
        except ConversionError as exc:
            if src_ext in VIDEO_IN:
                raise ConversionError(
                    "Diese Videodatei enthaelt keine eingebettete Untertitelspur.", exc.detail
                ) from exc
            raise
        VideoEngine._check(dst, dst_ext)
        return dst


def engines() -> list[Engine]:
    return [VideoEngine(), AudioEngine(), VideoThumbnailEngine(), AnimationEngine(), SubtitleEngine()]
