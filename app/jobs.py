"""Auftragsverwaltung.

Auftraege leben ausschliesslich im Arbeitsspeicher und auf der Platte des
Servers; es gibt keine Datenbank und keine Benutzerkonten. Jeder Auftrag
bekommt eine zufaellige, nicht erratbare Kennung und wird nach Ablauf der
Aufbewahrungsfrist restlos geloescht.
"""

from __future__ import annotations

import logging
import os
import secrets
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from app import formats
from app.config import settings
from app.engines.base import ConversionError, StepContext
from app.pipeline import (
    FileOutcome,
    SourceFile,
    build_zip,
    convert_file,
    merge_pdfs,
)

log = logging.getLogger("converter.jobs")


def new_id() -> str:
    """Zufaellige Kennung - der einzige Zugriffsschutz auf ein Ergebnis."""
    return secrets.token_urlsafe(24)


@dataclass
class Job:
    job_id: str
    target_ext: str
    options: dict[str, object]
    sources: list[SourceFile]
    directory: Path
    created: float = field(default_factory=time.time)
    status: str = "wartet"  # wartet | laeuft | fertig | fehler | abgebrochen
    outcomes: list[FileOutcome] = field(default_factory=list)
    error: str = ""
    bundle_path: Path | None = None
    bundle_name: str = ""
    finished: float = 0.0
    merge: bool = False
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    # -- Zustand -----------------------------------------------------
    @property
    def result_dir(self) -> Path:
        return self.directory / "ergebnis"

    @property
    def upload_dir(self) -> Path:
        return self.directory / "eingang"

    @property
    def scratch_dir(self) -> Path:
        return self.directory / "arbeit"

    @property
    def expires_at(self) -> float:
        return self.created + settings.retention_seconds

    @property
    def done_count(self) -> int:
        return sum(1 for o in self.outcomes if o.status in {"fertig", "fehler"})

    @property
    def success_count(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "fertig")

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def to_dict(self, include_files: bool = True) -> dict[str, object]:
        target = formats.get(self.target_ext)
        data: dict[str, object] = {
            "id": self.job_id,
            "status": self.status,
            "target": self.target_ext,
            "targetLabel": target.label if target else self.target_ext.upper(),
            "total": len(self.sources),
            "done": self.done_count,
            "successful": self.success_count,
            "failed": sum(1 for o in self.outcomes if o.status == "fehler"),
            "error": self.error,
            "merge": self.merge,
            "createdAt": self.created,
            "expiresAt": self.expires_at,
            "expiresInSeconds": max(0, int(self.expires_at - time.time())),
            "bundleName": self.bundle_name,
            "hasBundle": self.bundle_path is not None and self.bundle_path.exists(),
        }
        if include_files:
            data["files"] = [o.to_dict() for o in self.outcomes]
        return data


class JobStore:
    """Haelt Auftraege, fuehrt sie aus und raeumt sie wieder ab."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, settings.workers), thread_name_prefix="konverter"
        )
        self._cleaner: threading.Thread | None = None
        self._stop = threading.Event()

    # -- Verwaltung --------------------------------------------------
    def start(self) -> None:
        settings.ensure_dirs()
        self._purge_orphans()
        if self._cleaner is None:
            self._cleaner = threading.Thread(target=self._cleanup_loop, name="aufraeumen", daemon=True)
            self._cleaner.start()
            log.info(
                "Aufraeumdienst gestartet (Aufbewahrung: %d Minuten)",
                settings.retention_seconds // 60,
            )

    def shutdown(self) -> None:
        self._stop.set()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def create(
        self,
        target_ext: str,
        options: dict[str, object],
        merge: bool = False,
    ) -> Job:
        with self._lock:
            active = sum(1 for j in self._jobs.values() if j.status in {"wartet", "laeuft"})
            if active >= settings.max_active_jobs:
                raise ConversionError(
                    "Der Dienst ist zurzeit ausgelastet.",
                    "Bitte in wenigen Minuten erneut versuchen.",
                )
            job_id = new_id()
            directory = settings.work_dir / "auftraege" / job_id
            job = Job(
                job_id=job_id,
                target_ext=target_ext,
                options=options,
                sources=[],
                directory=directory,
                merge=merge,
            )
            for path in (job.upload_dir, job.result_dir, job.scratch_dir):
                path.mkdir(parents=True, exist_ok=True)
            self._jobs[job_id] = job
            return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def submit(self, job: Job) -> None:
        job.outcomes = [
            FileOutcome(file_id=s.file_id, original_name=s.original_name) for s in job.sources
        ]
        self._pool.submit(self._run, job)

    def stats(self) -> dict[str, object]:
        with self._lock:
            jobs = list(self._jobs.values())
        return {
            "auftraege": len(jobs),
            "laufend": sum(1 for j in jobs if j.status == "laeuft"),
            "wartend": sum(1 for j in jobs if j.status == "wartet"),
            "arbeiter": settings.workers,
        }

    # -- Ausfuehrung -------------------------------------------------
    def _run(self, job: Job) -> None:
        job.status = "laeuft"
        deadline = time.monotonic() + settings.job_timeout
        try:
            for index, source in enumerate(job.sources):
                if job.cancelled:
                    job.status = "abgebrochen"
                    return
                remaining = int(deadline - time.monotonic())
                if remaining <= 5:
                    for pending in job.outcomes[index:]:
                        pending.status = "fehler"
                        pending.error = "Das Zeitlimit des Auftrags ist erreicht."
                    break

                job.outcomes[index].status = "laeuft"
                outcome = convert_file(
                    source=source,
                    target_ext=job.target_ext,
                    options=job.options,
                    scratch_root=job.scratch_dir,
                    result_dir=job.result_dir,
                    timeout=min(settings.step_timeout, remaining),
                )
                job.outcomes[index] = outcome

            self._finalise(job)
        except Exception as exc:  # pragma: no cover
            job.status = "fehler"
            job.error = "Der Auftrag konnte nicht abgeschlossen werden."
            log.exception("Auftrag %s fehlgeschlagen: %s", job.job_id, exc)
        finally:
            job.finished = time.time()
            shutil.rmtree(job.scratch_dir, ignore_errors=True)
            # Die Originaldateien werden sofort nach der Verarbeitung entfernt.
            _remove_tree(job.upload_dir)

    def _finalise(self, job: Job) -> None:
        successful = [o for o in job.outcomes if o.status == "fertig"]
        if not successful:
            job.status = "fehler"
            job.error = "Keine der Dateien konnte umgewandelt werden."
            return

        ctx = StepContext(scratch=job.scratch_dir, timeout=settings.step_timeout)
        if job.merge and len(successful) > 1:
            merged = job.result_dir / "zusammengefuehrt.pdf"
            try:
                merge_pdfs([o.result_path for o in successful if o.result_path], merged, ctx)
                job.bundle_path = merged
                job.bundle_name = merged.name
            except ConversionError as exc:
                job.error = exc.message
        elif len(successful) > 1:
            bundle = job.result_dir / "konvertiert.zip"
            build_zip(successful, bundle)
            job.bundle_path = bundle
            job.bundle_name = bundle.name

        job.status = "fertig"

    # -- Aufraeumen --------------------------------------------------
    def _cleanup_loop(self) -> None:
        while not self._stop.wait(settings.cleanup_interval):
            try:
                self.cleanup()
            except Exception:  # pragma: no cover
                log.exception("Fehler beim Aufraeumen")

    def cleanup(self, force: bool = False) -> int:
        now = time.time()
        with self._lock:
            expired = [
                job for job in self._jobs.values()
                if force or (now > job.expires_at and job.status not in {"laeuft"})
            ]
            for job in expired:
                self._jobs.pop(job.job_id, None)
        for job in expired:
            _remove_tree(job.directory)
        if expired:
            log.info("%d abgelaufene Auftraege geloescht", len(expired))
        return len(expired)

    def delete(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.pop(job_id, None)
        if job is None:
            return False
        job.cancel()
        _remove_tree(job.directory)
        return True

    def _purge_orphans(self) -> None:
        """Reste eines vorherigen Laufs beseitigen (z. B. nach Neustart)."""
        base = settings.work_dir / "auftraege"
        if not base.exists():
            return
        removed = 0
        for entry in base.iterdir():
            if entry.is_dir():
                _remove_tree(entry)
                removed += 1
        if removed:
            log.info("%d Auftragsordner aus einem frueheren Lauf entfernt", removed)


def _shred(path: Path) -> None:
    """Dateiinhalt vor dem Loeschen ueberschreiben."""
    try:
        size = path.stat().st_size
        if size == 0 or size > 256 * 1024 * 1024:
            return
        with path.open("r+b", buffering=0) as handle:
            handle.write(os.urandom(size))
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        pass


def _remove_tree(path: Path) -> None:
    if not path.exists():
        return
    if settings.shred_files:
        for entry in path.rglob("*"):
            if entry.is_file():
                _shred(entry)
    shutil.rmtree(path, ignore_errors=True)


store = JobStore()
