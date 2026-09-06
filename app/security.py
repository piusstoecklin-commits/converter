"""Schutzfunktionen fuer den Betrieb ohne Anmeldung.

Der Dienst ist bewusst ohne Login ausgelegt. Der Schutz liegt deshalb im
Netzsegment (Zugriff nur aus dem Behoerdennetz) und in den Massnahmen hier:
strenge Namensbereinigung, Begrenzung der Last je Aufrufer und Kopfzeilen,
die den Browser eng fuehren.
"""

from __future__ import annotations

import re
import threading
import time
import unicodedata
from collections import deque
from pathlib import PurePosixPath, PureWindowsPath

# Alles ausser Buchstaben, Ziffern und wenigen Trennzeichen wird ersetzt.
_UNSAFE = re.compile(r"[^\w.\- ]+", re.UNICODE)
_COLLAPSE = re.compile(r"[\s_]+")
_MULTIDOT = re.compile(r"\.{2,}")

# Unter Windows reservierte Geraetenamen.
_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}

MAX_NAME_LENGTH = 120


def sanitize_filename(name: str, fallback: str = "datei") -> str:
    """Macht aus einem hochgeladenen Namen einen sicheren Dateinamen.

    Pfadanteile, Steuerzeichen und Sonderzeichen werden entfernt. Der
    Rueckgabewert enthaelt garantiert keinen Verzeichnistrenner.
    """
    if not name:
        return fallback

    # Sowohl Windows- als auch Unix-Pfade zerlegen: "..\\..\\etc\\passwd".
    candidate = PureWindowsPath(PurePosixPath(name).name).name or name
    candidate = unicodedata.normalize("NFC", candidate)
    candidate = "".join(ch for ch in candidate if ch.isprintable())
    candidate = candidate.replace("​", "").strip()

    stem, dot, suffix = candidate.rpartition(".")
    if not dot:
        stem, suffix = candidate, ""

    stem = _UNSAFE.sub("-", stem)
    stem = _COLLAPSE.sub("_", stem).strip("-_. ")
    stem = _MULTIDOT.sub(".", stem)
    suffix = _UNSAFE.sub("", suffix).lower()[:12]

    if not stem or stem.lower() in _RESERVED:
        stem = fallback
    if len(stem) > MAX_NAME_LENGTH:
        stem = stem[:MAX_NAME_LENGTH].rstrip("-_. ") or fallback

    return f"{stem}.{suffix}" if suffix else stem


def split_extension(name: str) -> tuple[str, str]:
    """Zerlegt einen Dateinamen in Stamm und Endung (mehrteilige beachtet)."""
    lowered = name.lower()
    for compound in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if lowered.endswith(compound):
            return name[: -len(compound)], compound.lstrip(".")
    stem, dot, suffix = name.rpartition(".")
    if not dot:
        return name, ""
    return stem, suffix.lower()


class RateLimiter:
    """Einfaches Zeitfensterverfahren je Aufrufer, im Arbeitsspeicher."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int]:
        """Gibt (erlaubt, Wartezeit in Sekunden) zurueck."""
        if self.limit <= 0:
            return True, 0
        now = time.monotonic()
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False, int(self.window - (now - bucket[0])) + 1
            bucket.append(now)
            if len(self._hits) > 10_000:
                self._prune(now)
            return True, 0

    def _prune(self, now: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
            self._hits.pop(key, None)


# Der Dienst laedt keine Ressourcen aus dem Internet nach. Die Richtlinie
# haelt das auch dann durch, wenn jemand die Oberflaeche veraendert.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data: blob:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "media-src 'self' blob:; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'self'"
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
    # Ergebnisse sind personenbezogen - niemals zwischenspeichern.
    "Cache-Control": "no-store, max-age=0",
}
