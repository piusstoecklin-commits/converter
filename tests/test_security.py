"""Tests der Schutzfunktionen."""

import pytest

from app.security import RateLimiter, sanitize_filename, split_extension


@pytest.mark.parametrize(
    "eingabe",
    [
        "../../etc/passwd",
        "..\\..\\windows\\system32\\config",
        "/absolut/pfad/datei.txt",
        "ordner/unterordner/datei.txt",
    ],
)
def test_pfadanteile_werden_entfernt(eingabe):
    ergebnis = sanitize_filename(eingabe)
    assert "/" not in ergebnis
    assert "\\" not in ergebnis
    assert ".." not in ergebnis


def test_umlaute_bleiben_erhalten():
    assert sanitize_filename("Bescheid Müller.docx") == "Bescheid_Müller.docx"


def test_reservierte_namen_werden_ersetzt():
    assert sanitize_filename("CON.txt").startswith("datei")
    assert sanitize_filename("lpt1.pdf").startswith("datei")


def test_steuerzeichen_werden_entfernt():
    assert "\x00" not in sanitize_filename("datei\x00name.png")
    assert "\n" not in sanitize_filename("zeile\nbruch.png")


def test_leerer_name_bekommt_ersatz():
    assert sanitize_filename("") == "datei"
    assert sanitize_filename("   ") == "datei"
    assert sanitize_filename("...") == "datei"


def test_laenge_wird_begrenzt():
    ergebnis = sanitize_filename("a" * 500 + ".pdf")
    assert len(ergebnis) <= 130
    assert ergebnis.endswith(".pdf")


def test_zusammengesetzte_endungen():
    assert split_extension("archiv.tar.gz") == ("archiv", "tar.gz")
    assert split_extension("Bild.JPEG") == ("Bild", "jpeg")
    assert split_extension("ohne_endung") == ("ohne_endung", "")


def test_lastbegrenzung_greift():
    begrenzer = RateLimiter(limit=3, window_seconds=60)
    for _ in range(3):
        erlaubt, _ = begrenzer.check("10.0.0.1")
        assert erlaubt
    erlaubt, wartezeit = begrenzer.check("10.0.0.1")
    assert not erlaubt
    assert wartezeit > 0
    # Andere Aufrufer bleiben unberuehrt.
    assert begrenzer.check("10.0.0.2")[0]


def test_lastbegrenzung_abschaltbar():
    begrenzer = RateLimiter(limit=0, window_seconds=60)
    for _ in range(50):
        assert begrenzer.check("10.0.0.1")[0]
