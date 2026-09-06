"""HTTP-Schnittstelle des Dokumentenkonverters."""

from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app import formats
from app.config import settings
from app.engines.base import ConversionError
from app.jobs import Job, store
from app.pipeline import SourceFile
from app.registry import registry
from app.security import (
    SECURITY_HEADERS,
    RateLimiter,
    sanitize_filename,
    split_extension,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("converter")

VERSION = "1.0.0"
STATIC_DIR = Path(__file__).parent / "static"

limiter = RateLimiter(settings.rate_limit_jobs, settings.rate_limit_window)

# Nur diese Einstellungen duerfen aus dem Formular an die Engines gereicht
# werden. Alles andere wird verworfen.
ALLOWED_OPTIONS: dict[str, type] = {
    "quality": int,
    "max_edge": int,
    "dpi": int,
    "page": int,
    "background": str,
    "lossless": bool,
    "optimize": bool,
    "strip_metadata": bool,
    "tiff_compression": str,
    "crf": int,
    "preset": str,
    "max_height": int,
    "audio_bitrate": str,
    "sample_rate": int,
    "channels": int,
    "fps": int,
    "gif_width": int,
    "duration": str,
    "timestamp": str,
    "delimiter": str,
    "out_delimiter": str,
    "excel_bom": bool,
    "sheet": str,
    "sheet_title": str,
    "table": str,
    "record_tag": str,
    "root_tag": str,
    "keep_layout": bool,
    "ocr": bool,
    "ocr_language": str,
    "deskew": bool,
    "compress": bool,
    "compress_preset": str,
    "compression_level": int,
    "title": str,
}

_TEXT_PRESETS = {"screen", "ebook", "printer", "prepress"}
_FFMPEG_PRESETS = {
    "ultrafast", "superfast", "veryfast", "faster", "fast",
    "medium", "slow", "slower", "veryslow",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    store.start()
    log.info(
        "%s %s gestartet - %d Eingabeformate, %d Ausgabeformate",
        settings.app_name,
        VERSION,
        len(registry.input_formats()),
        len(registry.output_formats()),
    )
    yield
    store.shutdown()


app = FastAPI(
    title="Dokumentenkonverter",
    version=VERSION,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    response = await call_next(request)
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    # Keine Hinweise auf die eingesetzte Software nach aussen geben.
    response.headers["Server"] = settings.app_name
    return response


def client_key(request: Request) -> str:
    """Kennung des Aufrufers fuer die Lastbegrenzung."""
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unbekannt"


# ----------------------------------------------------------------------
# Auskunft
# ----------------------------------------------------------------------

@app.get("/api/info")
async def info() -> JSONResponse:
    inputs = registry.input_formats()
    grouped = formats.by_category(inputs)
    return JSONResponse(
        {
            "name": settings.app_name,
            "organisation": settings.organisation,
            "version": VERSION,
            "footerNote": settings.footer_note,
            "limits": {
                "maxUploadBytes": settings.max_upload_bytes,
                "maxFilesPerJob": settings.max_files_per_job,
                "retentionMinutes": settings.retention_seconds // 60,
            },
            "counts": {
                "inputs": len(inputs),
                "outputs": len(registry.output_formats()),
                "engines": len(registry.engines),
            },
            "categories": [
                {
                    "key": key,
                    "label": formats.CATEGORIES.get(key, key),
                    "formats": [
                        {"ext": f.ext, "label": f.label, "note": f.note} for f in entries
                    ],
                }
                for key, entries in grouped.items()
            ],
        }
    )


@app.get("/api/targets")
async def targets(ext: str = "") -> JSONResponse:
    """Zielformate fuer eine oder mehrere Eingabeendungen.

    Werden mehrere Endungen mit Komma uebergeben, wird die Schnittmenge
    gebildet - so bleibt bei gemischten Stapeln nur uebrig, was fuer alle
    Dateien funktioniert.
    """
    requested = [e for e in (part.strip() for part in ext.split(",")) if e]
    if not requested:
        raise HTTPException(status_code=400, detail="Es wurde kein Quellformat angegeben.")

    unknown = [e for e in requested if formats.canonical(e) is None]
    catalogs = [registry.target_catalog(e) for e in requested if formats.canonical(e)]
    if not catalogs:
        return JSONResponse({"targets": [], "unknown": unknown, "sources": requested})

    common = set.intersection(*({str(entry["ext"]) for entry in cat} for cat in catalogs))
    merged = [entry for entry in catalogs[0] if entry["ext"] in common]
    if len(catalogs) > 1:
        # Bei gemischten Stapeln gilt ein Weg nur dann als direkt, wenn er es
        # fuer jede einzelne Datei ist. Die Wegbeschreibung entfaellt, weil sie
        # je Datei unterschiedlich ausfaellt.
        direct_counts: dict[str, int] = dict.fromkeys(common, 0)
        for cat in catalogs:
            for entry in cat:
                if entry["ext"] in common and entry["direct"]:
                    direct_counts[str(entry["ext"])] += 1
        for entry in merged:
            entry["direct"] = direct_counts[str(entry["ext"])] == len(catalogs)
            entry["via"] = ""

    return JSONResponse({"targets": merged, "unknown": unknown, "sources": requested})


@app.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "version": VERSION, **store.stats()})


# ----------------------------------------------------------------------
# Auftraege
# ----------------------------------------------------------------------

@app.post("/api/jobs")
async def create_job(
    request: Request,
    files: list[UploadFile] = File(...),
    target: str = Form(...),
    options: str = Form("{}"),
    merge: str = Form("false"),
) -> JSONResponse:
    allowed, wait = limiter.check(client_key(request))
    if not allowed:
        return JSONResponse(
            {
                "error": "Zu viele Auftraege in kurzer Zeit.",
                "detail": f"Bitte {wait} Sekunden warten.",
            },
            status_code=429,
            headers={"Retry-After": str(wait)},
        )

    target_ext = formats.canonical(target)
    if target_ext is None:
        raise HTTPException(status_code=400, detail=f"Unbekanntes Zielformat: {target}")

    if not files:
        raise HTTPException(status_code=400, detail="Es wurde keine Datei uebermittelt.")
    if len(files) > settings.max_files_per_job:
        raise HTTPException(
            status_code=400,
            detail=f"Es sind hoechstens {settings.max_files_per_job} Dateien je Auftrag erlaubt.",
        )

    parsed_options = _parse_options(options)
    merge_wanted = str(merge).strip().lower() in {"1", "true", "yes", "on", "ja"}
    if merge_wanted and target_ext not in {"pdf", "pdfa"}:
        merge_wanted = False

    try:
        job = store.create(target_ext, parsed_options, merge=merge_wanted)
    except ConversionError as exc:
        return JSONResponse({"error": exc.message, "detail": exc.detail}, status_code=503)

    rejected: list[dict[str, str]] = []
    try:
        for index, upload in enumerate(files):
            stored = await _store_upload(job, index, upload, rejected)
            if stored is not None:
                job.sources.append(stored)
    except HTTPException:
        store.delete(job.job_id)
        raise

    if not job.sources:
        store.delete(job.job_id)
        return JSONResponse(
            {
                "error": "Keine der Dateien konnte angenommen werden.",
                "rejected": rejected,
            },
            status_code=400,
        )

    store.submit(job)
    return JSONResponse({**job.to_dict(), "rejected": rejected}, status_code=202)


async def _store_upload(
    job: Job, index: int, upload: UploadFile, rejected: list[dict[str, str]]
) -> SourceFile | None:
    original = upload.filename or f"datei{index + 1}"
    safe_name = sanitize_filename(original)
    _, extension = split_extension(safe_name)
    canonical_ext = formats.canonical(extension)

    target_path = job.upload_dir / f"{index:03d}-{safe_name}"
    written = 0
    try:
        with target_path.open("wb") as sink:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    sink.close()
                    target_path.unlink(missing_ok=True)
                    rejected.append(
                        {
                            "name": original,
                            "reason": f"Die Datei ist groesser als das Limit von "
                                      f"{settings.max_upload_bytes // (1024 * 1024)} MB.",
                        }
                    )
                    return None
                sink.write(chunk)
    finally:
        await upload.close()

    if written == 0:
        target_path.unlink(missing_ok=True)
        rejected.append({"name": original, "reason": "Die Datei ist leer."})
        return None

    if canonical_ext is None:
        canonical_ext = _detect_extension(target_path)
    if canonical_ext is None:
        target_path.unlink(missing_ok=True)
        rejected.append(
            {
                "name": original,
                "reason": f"Das Format '{extension or 'ohne Endung'}' wird nicht unterstuetzt.",
            }
        )
        return None

    if canonical_ext not in registry.graph:
        target_path.unlink(missing_ok=True)
        rejected.append(
            {
                "name": original,
                "reason": f"{formats.label(canonical_ext)} kann nicht umgewandelt werden.",
            }
        )
        return None

    return SourceFile(
        file_id=f"{index:03d}",
        original_name=original[:200],
        path=target_path,
        ext=canonical_ext,
        size=written,
    )


def _detect_extension(path: Path) -> str | None:
    """Format anhand des Inhalts bestimmen, wenn die Endung fehlt."""
    try:
        import magic

        mime_type = magic.from_file(str(path), mime=True)
    except Exception:
        return None
    for fmt in formats.FORMATS.values():
        if fmt.mime == mime_type:
            return fmt.ext
    fallback = {
        "text/plain": "txt",
        "application/zip": "zip",
        "application/x-empty": None,
    }.get(mime_type)
    return fallback


def _parse_options(raw: str) -> dict[str, object]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}

    cleaned: dict[str, object] = {}
    for key, value in data.items():
        expected = ALLOWED_OPTIONS.get(str(key))
        if expected is None:
            continue
        try:
            if expected is bool:
                cleaned[key] = (
                    value if isinstance(value, bool)
                    else str(value).strip().lower() in {"1", "true", "yes", "on", "ja"}
                )
            elif expected is int:
                cleaned[key] = max(-1_000_000, min(1_000_000, int(value)))
            else:
                cleaned[key] = str(value)[:120]
        except (TypeError, ValueError):
            continue

    preset = cleaned.get("preset")
    if isinstance(preset, str) and preset not in _FFMPEG_PRESETS:
        cleaned.pop("preset")
    compress_preset = cleaned.get("compress_preset")
    if isinstance(compress_preset, str) and compress_preset not in _TEXT_PRESETS:
        cleaned.pop("compress_preset")
    return cleaned


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str) -> JSONResponse:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Der Auftrag ist unbekannt oder bereits geloescht.")
    return JSONResponse(job.to_dict())


@app.delete("/api/jobs/{job_id}")
async def drop_job(job_id: str) -> JSONResponse:
    if not store.delete(job_id):
        raise HTTPException(status_code=404, detail="Der Auftrag ist unbekannt oder bereits geloescht.")
    return JSONResponse({"status": "geloescht"})


@app.get("/api/jobs/{job_id}/dateien/{file_id}")
async def download_file(job_id: str, file_id: str):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Der Auftrag ist unbekannt oder bereits geloescht.")
    outcome = next((o for o in job.outcomes if o.file_id == file_id), None)
    if outcome is None or outcome.result_path is None or not outcome.result_path.exists():
        raise HTTPException(status_code=404, detail="Zu dieser Datei liegt kein Ergebnis vor.")
    return _deliver(outcome.result_path, outcome.result_name, job.target_ext)


@app.get("/api/jobs/{job_id}/paket")
async def download_bundle(job_id: str):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Der Auftrag ist unbekannt oder bereits geloescht.")
    if job.bundle_path is None or not job.bundle_path.exists():
        raise HTTPException(status_code=404, detail="Fuer diesen Auftrag gibt es kein Sammelpaket.")
    extension = "pdf" if job.merge else "zip"
    return _deliver(job.bundle_path, job.bundle_name, extension)


def _deliver(path: Path, filename: str, ext: str) -> FileResponse:
    return FileResponse(
        path=path,
        filename=filename,
        media_type=formats.mime(ext) if formats.get(ext) else "application/octet-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            # Erzwingt das Herunterladen statt der Anzeige im Browser.
            "Content-Disposition": f'attachment; filename="{sanitize_filename(filename)}"',
        },
    )


# ----------------------------------------------------------------------
# Oberflaeche
# ----------------------------------------------------------------------

@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots() -> str:
    return "User-agent: *\nDisallow: /\n"


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="oberflaeche")
