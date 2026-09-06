"""Gemeinsame Vorbereitungen fuer die Tests."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Arbeitsverzeichnis auf einen temporaeren Ort legen, bevor die Anwendung
# importiert wird - sonst wuerde /data/work angelegt.
_TEMP = tempfile.mkdtemp(prefix="konverter-tests-")
os.environ.setdefault("WORK_DIR", _TEMP)
os.environ.setdefault("RETENTION_MINUTES", "5")


@pytest.fixture
def scratch(tmp_path: Path) -> Path:
    directory = tmp_path / "arbeit"
    directory.mkdir()
    return directory


@pytest.fixture
def ctx(scratch: Path):
    from app.engines.base import StepContext

    return StepContext(scratch=scratch, timeout=60)
