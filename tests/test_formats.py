"""Tests fuer den Formatkatalog."""

from app import formats


def test_katalog_ist_konsistent():
    for ext, fmt in formats.FORMATS.items():
        assert fmt.ext == ext, "Schluessel und Kennung muessen uebereinstimmen"
        assert fmt.category in formats.CATEGORIES, f"{ext} hat eine unbekannte Kategorie"
        assert fmt.label, f"{ext} hat keinen Anzeigenamen"
        assert not (fmt.read_only and fmt.write_only), f"{ext} kann nicht beides sein"


def test_aliase_zeigen_auf_bekannte_formate():
    for alias, ziel in formats._ALIAS_MAP.items():
        assert ziel in formats.FORMATS, f"Alias {alias} zeigt ins Leere"


def test_normalisierung():
    assert formats.canonical(".JPEG") == "jpg"
    assert formats.canonical("jpg") == "jpg"
    assert formats.canonical("  PDF ") == "pdf"
    assert formats.canonical("yml") == "yaml"
    assert formats.canonical("gibtsnicht") is None
    assert formats.canonical("") is None


def test_dateiendung_fuer_pseudoformate():
    assert formats.file_suffix("pdfa") == "pdf"
    assert formats.file_suffix("tgz") == "tar.gz"
    assert formats.file_suffix("docx") == "docx"


def test_kategorien_sind_vollstaendig_sortiert():
    assert set(formats.CATEGORY_ORDER) == set(formats.CATEGORIES)


def test_gruppierung_haelt_reihenfolge_ein():
    gruppen = formats.by_category(["mp3", "docx", "png"])
    assert list(gruppen) == ["document", "image", "audio"]
