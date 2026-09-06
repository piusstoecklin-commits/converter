"""Tests der Wegesuche zwischen Formaten."""

import pytest

from app import formats
from app.registry import Registry, route_is_sensible


@pytest.fixture(scope="module")
def registry() -> Registry:
    # Ohne Pruefung auf installierte Programme, damit die Tests auch
    # ausserhalb des Containers vollstaendig laufen.
    return Registry(require_binaries=False)


def test_graph_ist_umfangreich(registry):
    assert len(registry.input_formats()) > 130
    assert len(registry.output_formats()) > 100


def test_wichtige_wege_existieren(registry):
    erwartet = [
        ("docx", "pdf"), ("doc", "pdf"), ("odt", "pdf"), ("rtf", "pdf"),
        ("xlsx", "pdf"), ("xlsx", "csv"), ("csv", "xlsx"), ("ods", "xlsx"),
        ("pptx", "pdf"), ("pptx", "odp"), ("pdf", "docx"), ("pdf", "txt"),
        ("pdf", "pdfa"), ("pdf", "jpg"), ("jpg", "pdf"), ("heic", "jpg"),
        ("png", "webp"), ("tiff", "pdf"), ("svg", "png"), ("eml", "pdf"),
        ("msg", "pdf"), ("md", "docx"), ("md", "pdf"), ("html", "pdf"),
        ("epub", "pdf"), ("mp4", "mp3"), ("mov", "mp4"), ("wav", "mp3"),
        ("json", "yaml"), ("json", "csv"), ("xml", "json"), ("zip", "7z"),
        ("ttf", "woff2"), ("srt", "vtt"), ("vsdx", "pdf"), ("cr2", "jpg"),
    ]
    fehlend = [(a, b) for a, b in erwartet if registry.route(a, b) is None]
    assert not fehlend, f"Diese Wege fehlen: {fehlend}"


def test_kein_weg_auf_sich_selbst(registry):
    assert registry.route("pdf", "pdf") is None
    assert registry.route("jpg", "jpeg") is None  # gleicher Kanon


def test_unbekannte_formate_liefern_nichts(registry):
    assert registry.route("exe", "pdf") is None
    assert registry.route("pdf", "exe") is None


def test_unsinnige_ketten_werden_gefiltert(registry):
    # Aus einem Video laesst sich zwar ein Standbild gewinnen, der Weg zu
    # einem Textdokument ist aber fachlich sinnlos.
    assert registry.route("mp4", "docx") is None
    assert registry.route("mp3", "pdf") is None
    assert registry.route("zip", "pdf") is None
    assert registry.route("ttf", "png") is None
    # Der direkte Weg zum Standbild bleibt erhalten.
    assert registry.route("mp4", "png") is not None


def test_domaenenregel():
    assert route_is_sensible("docx", "pdf", 1)
    assert route_is_sensible("docx", "png", 2)
    assert not route_is_sensible("docx", "exr", 2)
    assert not route_is_sensible("mp4", "docx", 3)
    assert route_is_sensible("mp4", "gif", 1)


def test_direkte_wege_werden_bevorzugt(registry):
    weg = registry.route("docx", "pdf")
    assert weg is not None and weg.direct
    assert weg.hops == 1


def test_pfadlaenge_wird_eingehalten(registry):
    for ziel_ext in registry.input_formats()[:40]:
        for ziel in registry.targets_for(ziel_ext).values():
            assert ziel.hops <= 3


def test_keine_schleifen_im_weg(registry):
    weg = registry.route("msg", "pdfa")
    assert weg is not None
    stationen = [weg.steps[0].src_ext] + [s.dst_ext for s in weg.steps]
    assert len(stationen) == len(set(stationen)), "Ein Format darf nicht doppelt vorkommen"


def test_zielkatalog_ist_sortiert_und_beschriftet(registry):
    katalog = registry.target_catalog("docx")
    assert katalog
    for eintrag in katalog:
        assert eintrag["ext"] in formats.FORMATS
        assert eintrag["label"]
        assert eintrag["categoryLabel"]
        # Nur-Lese-Formate duerfen nie als Ziel erscheinen.
        assert not formats.FORMATS[str(eintrag["ext"])].read_only


def test_nur_lese_formate_sind_kein_ziel(registry):
    nur_lesbar = [e for e, f in formats.FORMATS.items() if f.read_only]
    assert nur_lesbar
    for quelle in ("docx", "pdf", "jpg"):
        ziele = {str(e["ext"]) for e in registry.target_catalog(quelle)}
        assert not ziele & set(nur_lesbar)


def test_jedes_eingabeformat_erreicht_mindestens_ein_ziel(registry):
    ohne_ziel = [ext for ext in registry.input_formats() if not registry.target_catalog(ext)]
    assert not ohne_ziel, f"Ohne Zielformat: {ohne_ziel}"


def test_fehlende_programme_legen_den_dienst_nicht_lahm():
    """Fehlt ein externes Programm, entfallen nur dessen Wege."""
    from app.engines.data import TableEngine, TreeEngine
    from app.engines.images import PillowEngine

    beschraenkt = Registry(engines=[TableEngine(), TreeEngine(), PillowEngine()])
    assert beschraenkt.route("csv", "xlsx") is not None
    assert beschraenkt.route("png", "jpg") is not None
    # LibreOffice fehlt in dieser Zusammenstellung.
    assert beschraenkt.route("docx", "pdf") is None
    assert beschraenkt.input_formats()


def test_registry_meldet_nur_verfuegbare_engines():
    """available() entscheidet, ob eine Engine in den Graphen aufgenommen wird."""
    from app.engines.base import Engine

    class NichtVerfuegbar(Engine):
        name = "test-fehlt"
        requires = "gibt-es-garantiert-nicht-xyz"
        source_exts = ("txt",)
        target_exts = ("md",)

    assert not NichtVerfuegbar().available()
    assert Registry(engines=[NichtVerfuegbar()]).route("txt", "md") is None
    assert Registry(engines=[NichtVerfuegbar()], require_binaries=False).route("txt", "md") is not None
