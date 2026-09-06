"""Zentrale Konfiguration.

Alle Werte lassen sich per Umgebungsvariable setzen, damit der Betrieb im
Rechenzentrum ohne Codeaenderung angepasst werden kann.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "ja"}


@dataclass(frozen=True)
class Settings:
    # --- Betrieb ---
    app_name: str = field(default_factory=lambda: _env_str("APP_NAME", "Dokumentenkonverter"))
    organisation: str = field(default_factory=lambda: _env_str("ORGANISATION", "Landratsamt"))
    # Hinweistext im Fusszeilenbereich, z. B. Ansprechpartner der IT.
    footer_note: str = field(default_factory=lambda: _env_str("FOOTER_NOTE", ""))

    # --- Verzeichnisse ---
    work_dir: Path = field(default_factory=lambda: Path(_env_str("WORK_DIR", "/data/work")))

    # --- Grenzwerte ---
    # Maximale Groesse einer einzelnen Datei (Bytes).
    max_upload_bytes: int = field(
        default_factory=lambda: _env_int("MAX_UPLOAD_MB", 512) * 1024 * 1024
    )
    # Maximale Anzahl Dateien pro Auftrag.
    max_files_per_job: int = field(default_factory=lambda: _env_int("MAX_FILES_PER_JOB", 50))
    # Zeitlimit fuer einen einzelnen Konvertierungsschritt (Sekunden).
    step_timeout: int = field(default_factory=lambda: _env_int("STEP_TIMEOUT", 900))
    # Zeitlimit fuer einen kompletten Auftrag (Sekunden).
    job_timeout: int = field(default_factory=lambda: _env_int("JOB_TIMEOUT", 3600))
    # Anzahl paralleler Konvertierungen.
    workers: int = field(default_factory=lambda: _env_int("WORKERS", max(2, (os.cpu_count() or 2))))

    # --- Aufbewahrung ---
    # Ergebnisse werden nach dieser Zeit unwiderruflich geloescht (Sekunden).
    retention_seconds: int = field(default_factory=lambda: _env_int("RETENTION_MINUTES", 30) * 60)
    # Intervall des Aufraeumdienstes (Sekunden).
    cleanup_interval: int = field(default_factory=lambda: _env_int("CLEANUP_INTERVAL", 60))
    # Dateien vor dem Loeschen ueberschreiben (langsamer, aber gruendlicher).
    shred_files: bool = field(default_factory=lambda: _env_bool("SHRED_FILES", False))

    # --- Missbrauchsschutz (kein Login, daher IP-basiert) ---
    rate_limit_jobs: int = field(default_factory=lambda: _env_int("RATE_LIMIT_JOBS", 60))
    rate_limit_window: int = field(default_factory=lambda: _env_int("RATE_LIMIT_WINDOW", 600))
    max_active_jobs: int = field(default_factory=lambda: _env_int("MAX_ACTIVE_JOBS", 200))
    # Vertrauenswuerdiger Reverse-Proxy? Nur dann X-Forwarded-For auswerten.
    trust_proxy: bool = field(default_factory=lambda: _env_bool("TRUST_PROXY", False))

    # --- Umfang der Konvertierungskette ---
    # Wie viele Zwischenschritte sind maximal erlaubt (1 = nur direkte Wege).
    max_path_length: int = field(default_factory=lambda: _env_int("MAX_PATH_LENGTH", 3))

    @property
    def upload_dir(self) -> Path:
        return self.work_dir / "uploads"

    @property
    def result_dir(self) -> Path:
        return self.work_dir / "results"

    @property
    def scratch_dir(self) -> Path:
        return self.work_dir / "scratch"

    def ensure_dirs(self) -> None:
        for path in (self.work_dir, self.upload_dir, self.result_dir, self.scratch_dir):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
