"""Tests der HTTP-Schnittstelle."""

import io
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security import SECURITY_HEADERS


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_startseite_wird_ausgeliefert(client):
    antwort = client.get("/")
    assert antwort.status_code == 200
    assert "Dokumentenkonverter" in antwort.text


def test_sicherheitskopfzeilen_sind_gesetzt(client):
    antwort = client.get("/")
    for kopfzeile in SECURITY_HEADERS:
        assert kopfzeile in antwort.headers, f"{kopfzeile} fehlt"
    assert "default-src 'self'" in antwort.headers["Content-Security-Policy"]
    # Keine externen Quellen erlaubt.
    assert "http://" not in antwort.headers["Content-Security-Policy"]
    assert antwort.headers["X-Frame-Options"] == "DENY"


def test_auskunft_nennt_grenzwerte_und_formate(client):
    from app.registry import registry

    daten = client.get("/api/info").json()
    assert daten["limits"]["maxUploadBytes"] > 0
    assert daten["categories"]
    # Die gemeldete Zahl muss zum tatsaechlich verfuegbaren Graphen passen.
    # Ausserhalb des Containers fehlen einzelne Programme; dann faellt der
    # Umfang kleiner aus, ohne dass der Dienst ausfaellt.
    assert daten["counts"]["inputs"] == len(registry.input_formats())
    assert daten["counts"]["inputs"] > 50


def test_gesundheitspruefung(client):
    daten = client.get("/api/health").json()
    assert daten["status"] == "ok"


def test_zielformate_einer_endung(client):
    daten = client.get("/api/targets?ext=csv").json()
    ziele = {z["ext"] for z in daten["targets"]}
    assert {"xlsx", "json", "pdf"} <= ziele


def test_zielformate_bilden_schnittmenge(client):
    """Bei gemischten Stapeln darf nur uebrig bleiben, was fuer alle geht."""
    gemischt = {z["ext"] for z in client.get("/api/targets?ext=docx,jpg").json()["targets"]}
    nur_docx = {z["ext"] for z in client.get("/api/targets?ext=docx").json()["targets"]}
    nur_jpg = {z["ext"] for z in client.get("/api/targets?ext=jpg").json()["targets"]}
    assert gemischt == nur_docx & nur_jpg
    assert "pdf" in gemischt


def test_unbekannte_endung_wird_gemeldet(client):
    daten = client.get("/api/targets?ext=exe").json()
    assert daten["unknown"] == ["exe"]
    assert daten["targets"] == []


def test_fehlende_endung_gibt_fehler(client):
    assert client.get("/api/targets?ext=").status_code == 400


def test_robots_verbietet_indexierung(client):
    antwort = client.get("/robots.txt")
    assert "Disallow: /" in antwort.text


def test_unbekannter_auftrag_gibt_404(client):
    antwort = client.get("/api/jobs/gibtesnicht")
    assert antwort.status_code == 404
    assert "error" in antwort.json()


def test_unbekanntes_zielformat_wird_abgelehnt(client):
    antwort = client.post(
        "/api/jobs",
        files={"files": ("a.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")},
        data={"target": "exe"},
    )
    assert antwort.status_code == 400


def test_nicht_unterstuetzte_datei_wird_abgewiesen(client):
    antwort = client.post(
        "/api/jobs",
        files={"files": ("schadcode.exe", io.BytesIO(b"MZ\x90\x00"), "application/octet-stream")},
        data={"target": "pdf"},
    )
    assert antwort.status_code == 400
    daten = antwort.json()
    assert daten["rejected"]
    assert "nicht unterstuetzt" in daten["rejected"][0]["reason"].lower()


def test_leere_datei_wird_abgewiesen(client):
    antwort = client.post(
        "/api/jobs",
        files={"files": ("leer.csv", io.BytesIO(b""), "text/csv")},
        data={"target": "json"},
    )
    assert antwort.status_code == 400
    assert "leer" in antwort.json()["rejected"][0]["reason"].lower()


def _auftrag_abwarten(client, auftrag_id: str, sekunden: float = 30.0) -> dict:
    frist = time.time() + sekunden
    while time.time() < frist:
        daten = client.get(f"/api/jobs/{auftrag_id}").json()
        if daten["status"] not in {"wartet", "laeuft"}:
            return daten
        time.sleep(0.15)
    raise AssertionError("Der Auftrag wurde nicht rechtzeitig fertig.")


def test_vollstaendiger_auftrag_csv_nach_json(client):
    """Der komplette Weg: hochladen, umwandeln, herunterladen, loeschen."""
    antwort = client.post(
        "/api/jobs",
        files={"files": ("faelle.csv", io.BytesIO("Name,Ort\nMüller,Freiburg\n".encode()), "text/csv")},
        data={"target": "json", "options": "{}"},
    )
    assert antwort.status_code == 202
    auftrag_id = antwort.json()["id"]

    fertig = _auftrag_abwarten(client, auftrag_id)
    assert fertig["status"] == "fertig", fertig
    assert fertig["successful"] == 1
    datei = fertig["files"][0]
    assert datei["status"] == "fertig"
    assert datei["resultName"] == "faelle.json"

    laden = client.get(f"/api/jobs/{auftrag_id}/dateien/{datei['id']}")
    assert laden.status_code == 200
    assert "attachment" in laden.headers["content-disposition"]
    assert json.loads(laden.content)[0]["Ort"] == "Freiburg"

    assert client.delete(f"/api/jobs/{auftrag_id}").status_code == 200
    assert client.get(f"/api/jobs/{auftrag_id}").status_code == 404


def test_mehrere_dateien_ergeben_ein_sammelpaket(client):
    antwort = client.post(
        "/api/jobs",
        files=[
            ("files", ("eins.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")),
            ("files", ("zwei.csv", io.BytesIO(b"a,b\n3,4\n"), "text/csv")),
        ],
        data={"target": "json"},
    )
    auftrag_id = antwort.json()["id"]
    fertig = _auftrag_abwarten(client, auftrag_id)

    assert fertig["successful"] == 2
    assert fertig["hasBundle"] is True
    assert fertig["bundleName"].endswith(".zip")

    paket = client.get(f"/api/jobs/{auftrag_id}/paket")
    assert paket.status_code == 200

    import zipfile

    with zipfile.ZipFile(io.BytesIO(paket.content)) as archiv:
        assert sorted(archiv.namelist()) == ["eins.json", "zwei.json"]


def test_gefaehrlicher_dateiname_wird_entschaerft(client):
    antwort = client.post(
        "/api/jobs",
        files={"files": ("../../../etc/passwd.csv", io.BytesIO(b"a\n1\n"), "text/csv")},
        data={"target": "json"},
    )
    auftrag_id = antwort.json()["id"]
    fertig = _auftrag_abwarten(client, auftrag_id)
    ergebnisname = fertig["files"][0]["resultName"]
    assert "/" not in ergebnisname and ".." not in ergebnisname
    assert ergebnisname == "passwd.json"


def test_unmoeglicher_weg_meldet_fehler_pro_datei(client):
    antwort = client.post(
        "/api/jobs",
        files={"files": ("liste.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")},
        data={"target": "woff2"},
    )
    auftrag_id = antwort.json()["id"]
    fertig = _auftrag_abwarten(client, auftrag_id)
    assert fertig["status"] == "fehler"
    assert "keinen Weg" in fertig["files"][0]["error"]


def test_unerlaubte_optionen_werden_verworfen():
    from app.main import _parse_options

    ergebnis = _parse_options(json.dumps({
        "quality": 90,
        "ocr": True,
        "boeses_feld": "rm -rf /",
        "preset": "; rm -rf /",
        "compress_preset": "../../etc",
    }))
    assert ergebnis == {"quality": 90, "ocr": True}


def test_optionen_werden_auf_grenzen_beschnitten():
    from app.main import _parse_options

    ergebnis = _parse_options(json.dumps({"quality": 10**9, "title": "x" * 500}))
    assert ergebnis["quality"] == 1_000_000
    assert len(ergebnis["title"]) == 120


def test_kaputte_optionen_fuehren_nicht_zum_absturz():
    from app.main import _parse_options

    assert _parse_options("kein json") == {}
    assert _parse_options("[1,2,3]") == {}
    assert _parse_options("") == {}
