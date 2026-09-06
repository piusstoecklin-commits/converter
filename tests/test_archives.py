"""Tests der Archiv-Engine, insbesondere der Schutzmechanismen."""

import io
import tarfile
import zipfile

import pytest

from app.engines.archives import ArchiveEngine
from app.engines.base import ConversionError


@pytest.fixture
def engine():
    return ArchiveEngine()


def test_zip_nach_tar_gz(engine, tmp_path, ctx):
    quelle = tmp_path / "akte.zip"
    with zipfile.ZipFile(quelle, "w") as archiv:
        archiv.writestr("bescheid.txt", "Inhalt des Bescheids")
        archiv.writestr("anlagen/plan.txt", "Lageplan")

    ziel = tmp_path / "akte.tar.gz"
    engine.convert(quelle, ziel, "zip", "tgz", ctx)

    with tarfile.open(ziel, "r:gz") as archiv:
        namen = sorted(archiv.getnames())
    assert namen == ["anlagen/plan.txt", "bescheid.txt"]


def test_pfadausbruch_wird_abgewiesen(engine, tmp_path, ctx):
    """Ein Eintrag wie ../../etc/passwd darf nicht entpackt werden."""
    quelle = tmp_path / "boese.zip"
    with zipfile.ZipFile(quelle, "w") as archiv:
        archiv.writestr("../../entkommen.txt", "sollte nie ankommen")

    with pytest.raises(ConversionError) as fehler:
        engine.convert(quelle, tmp_path / "x.tar", "zip", "tar", ctx)
    assert "ausserhalb" in fehler.value.message
    assert not (tmp_path.parent / "entkommen.txt").exists()


def test_absoluter_pfad_im_tar_wird_abgewiesen(engine, tmp_path, ctx):
    """Ein Eintrag mit fuehrendem / darf nicht ins Wurzelverzeichnis schreiben."""
    quelle = tmp_path / "absolut.tar"
    with tarfile.open(quelle, "w") as archiv:
        info = tarfile.TarInfo("/etc/schatten")
        info.size = 1
        archiv.addfile(info, io.BytesIO(b"x"))

    with pytest.raises(ConversionError) as fehler:
        engine.convert(quelle, tmp_path / "x.zip", "tar", "zip", ctx)
    assert "ausserhalb" in fehler.value.message


def test_absoluter_pfad_im_zip_wird_abgewiesen(engine, tmp_path, ctx):
    quelle = tmp_path / "absolut.zip"
    with zipfile.ZipFile(quelle, "w") as archiv:
        archiv.writestr("/etc/schatten", "x")

    with pytest.raises(ConversionError) as fehler:
        engine.convert(quelle, tmp_path / "x.tar", "zip", "tar", ctx)
    assert "ausserhalb" in fehler.value.message


def test_dekompressionsbombe_wird_erkannt(engine, tmp_path, ctx):
    """Stark komprimierte Nullbytes duerfen den Server nicht fluten."""
    quelle = tmp_path / "bombe.zip"
    with zipfile.ZipFile(quelle, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archiv:
        archiv.writestr("gross.bin", b"\0" * (60 * 1024 * 1024))

    with pytest.raises(ConversionError) as fehler:
        engine.convert(quelle, tmp_path / "x.tar", "zip", "tar", ctx)
    assert "bombe" in fehler.value.message.lower()


def test_symbolische_verweise_werden_uebersprungen(engine, tmp_path, ctx):
    quelle = tmp_path / "verweise.tar"
    echte_datei = tmp_path / "echt.txt"
    echte_datei.write_text("harmlos", encoding="utf-8")
    with tarfile.open(quelle, "w") as archiv:
        archiv.add(echte_datei, arcname="echt.txt")
        verweis = tarfile.TarInfo("passwort")
        verweis.type = tarfile.SYMTYPE
        verweis.linkname = "/etc/passwd"
        archiv.addfile(verweis)

    ziel = tmp_path / "sauber.zip"
    engine.convert(quelle, ziel, "tar", "zip", ctx)

    with zipfile.ZipFile(ziel) as archiv:
        assert archiv.namelist() == ["echt.txt"]


def test_leeres_archiv_meldet_fehler(engine, tmp_path, ctx):
    quelle = tmp_path / "leer.zip"
    with zipfile.ZipFile(quelle, "w"):
        pass

    with pytest.raises(ConversionError) as fehler:
        engine.convert(quelle, tmp_path / "x.tar", "zip", "tar", ctx)
    assert "keine Dateien" in fehler.value.message
