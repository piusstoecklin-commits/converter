/* Dokumentenkonverter - Oberflaeche
   Reines JavaScript ohne Fremdbibliotheken: die Seite laedt nichts aus dem
   Internet nach und funktioniert damit auch in abgeschotteten Netzen. */

"use strict";

const zustand = {
  dateien: [],          // { id, datei, endung }
  ziel: null,           // gewaehltes Zielformat
  zieleListe: [],       // Antwort von /api/targets
  auftrag: null,        // aktueller Auftrag
  grenzen: { maxUploadBytes: 0, maxFilesPerJob: 50, retentionMinutes: 30 },
  abfrage: null,        // Zeitgeber fuer die Statusabfrage
  naechsteId: 1,
};

const $ = (id) => document.getElementById(id);

/* ---------------------------------------------------------------- */
/* Hilfsfunktionen                                                   */
/* ---------------------------------------------------------------- */

function groesse(bytes) {
  if (!bytes) return "0 B";
  const einheiten = ["B", "KB", "MB", "GB"];
  let wert = bytes;
  let i = 0;
  while (wert >= 1024 && i < einheiten.length - 1) { wert /= 1024; i++; }
  return `${i === 0 ? wert : wert.toFixed(1)} ${einheiten[i]}`;
}

function endungVon(name) {
  const klein = name.toLowerCase();
  for (const zusammen of [".tar.gz", ".tar.bz2", ".tar.xz"]) {
    if (klein.endsWith(zusammen)) return zusammen.slice(1);
  }
  const punkt = klein.lastIndexOf(".");
  return punkt > 0 ? klein.slice(punkt + 1) : "";
}

function text(element, inhalt) { element.textContent = inhalt; }

function zeige(element, sichtbar) { element.hidden = !sichtbar; }

function meldung(art, inhalt) {
  const feld = $("ergebnis-meldung");
  feld.className = `meldung ${art}`;
  feld.textContent = inhalt;
  zeige(feld, Boolean(inhalt));
}

async function holen(pfad, optionen) {
  const antwort = await fetch(pfad, optionen);
  let daten = null;
  try { daten = await antwort.json(); } catch (fehler) { daten = null; }
  if (!antwort.ok) {
    const grund = (daten && (daten.error || daten.detail)) || `HTTP ${antwort.status}`;
    throw new Error(grund);
  }
  return daten;
}

/* ---------------------------------------------------------------- */
/* Start                                                             */
/* ---------------------------------------------------------------- */

async function start() {
  ablageVorbereiten();
  $("starten").addEventListener("click", auftragStarten);
  $("zuruecksetzen").addEventListener("click", allesZuruecksetzen);
  $("jetzt-loeschen").addEventListener("click", auftragLoeschen);
  $("zielsuche").addEventListener("input", zieleZeichnen);
  $("uebersicht-schalter").addEventListener("click", uebersichtUmschalten);

  try {
    const info = await holen("/api/info");
    zustand.grenzen = info.limits;
    text($("organisation"), info.organisation);
    text($("anwendungsname"), info.name);
    text($("fuss-name"), info.name);
    text($("fuss-version"), info.version);
    text($("fuss-aufbewahrung"), String(info.limits.retentionMinutes));
    document.title = `${info.name} – ${info.organisation}`;
    text(
      $("limit-hinweis"),
      `je Datei bis ${groesse(info.limits.maxUploadBytes)}, ` +
      `bis zu ${info.limits.maxFilesPerJob} Dateien`
    );
    text(
      $("format-zaehler"),
      `${info.counts.inputs} Eingabeformate, ${info.counts.outputs} Zielformate, ` +
      `${info.counts.engines} Konvertierungsmodule.`
    );
    if (info.footerNote) {
      text($("fuss-notiz"), info.footerNote);
      zeige($("fuss-notiz"), true);
    }
    uebersichtZeichnen(info.categories);
  } catch (fehler) {
    meldung("fehler", `Die Serverinformationen konnten nicht geladen werden: ${fehler.message}`);
    zeige($("karte-ergebnis"), true);
  }
}

/* ---------------------------------------------------------------- */
/* Dateiauswahl                                                      */
/* ---------------------------------------------------------------- */

function ablageVorbereiten() {
  const ablage = $("ablage");
  const auswahl = $("dateiauswahl");

  ablage.addEventListener("click", () => auswahl.click());
  ablage.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); auswahl.click(); }
  });
  auswahl.addEventListener("change", () => {
    dateienAufnehmen(Array.from(auswahl.files || []));
    auswahl.value = "";
  });

  ["dragenter", "dragover"].forEach((typ) =>
    ablage.addEventListener(typ, (e) => {
      e.preventDefault();
      ablage.classList.add("aktiv");
    })
  );
  ["dragleave", "drop"].forEach((typ) =>
    ablage.addEventListener(typ, (e) => {
      e.preventDefault();
      ablage.classList.remove("aktiv");
    })
  );
  ablage.addEventListener("drop", (e) => {
    dateienAufnehmen(Array.from(e.dataTransfer ? e.dataTransfer.files : []));
  });
}

function dateienAufnehmen(neue) {
  if (!neue.length) return;
  const platz = zustand.grenzen.maxFilesPerJob - zustand.dateien.length;
  if (platz <= 0) {
    meldung("warnung", `Es sind höchstens ${zustand.grenzen.maxFilesPerJob} Dateien je Auftrag möglich.`);
    zeige($("karte-ergebnis"), true);
    return;
  }
  for (const datei of neue.slice(0, platz)) {
    zustand.dateien.push({
      id: zustand.naechsteId++,
      datei,
      endung: endungVon(datei.name),
      zuGross: datei.size > zustand.grenzen.maxUploadBytes,
    });
  }
  dateilisteZeichnen();
  zieleLaden();
}

function dateiEntfernen(id) {
  zustand.dateien = zustand.dateien.filter((e) => e.id !== id);
  dateilisteZeichnen();
  zieleLaden();
}

function dateilisteZeichnen() {
  const liste = $("dateiliste");
  liste.replaceChildren();

  for (const eintrag of zustand.dateien) {
    const zeile = document.createElement("li");

    const kennung = document.createElement("span");
    kennung.className = "datei-kennung";
    kennung.textContent = (eintrag.endung || "?").toUpperCase().slice(0, 6);

    const textblock = document.createElement("div");
    textblock.className = "datei-text";
    const name = document.createElement("span");
    name.className = "datei-name";
    name.textContent = eintrag.datei.name;
    const meta = document.createElement("span");
    meta.className = eintrag.zuGross ? "datei-warnung" : "datei-meta";
    meta.textContent = eintrag.zuGross
      ? `${groesse(eintrag.datei.size)} – überschreitet das Limit von ${groesse(zustand.grenzen.maxUploadBytes)}`
      : groesse(eintrag.datei.size);
    textblock.append(name, meta);

    const entfernen = document.createElement("button");
    entfernen.type = "button";
    entfernen.className = "entfernen";
    entfernen.textContent = "×";
    entfernen.setAttribute("aria-label", `${eintrag.datei.name} entfernen`);
    entfernen.addEventListener("click", () => dateiEntfernen(eintrag.id));

    zeile.append(kennung, textblock, entfernen);
    liste.append(zeile);
  }

  zeige($("dateiliste-leer"), zustand.dateien.length === 0);
  zusammenfassungAktualisieren();
}

/* ---------------------------------------------------------------- */
/* Zielformate                                                       */
/* ---------------------------------------------------------------- */

async function zieleLaden() {
  const endungen = [...new Set(zustand.dateien.map((e) => e.endung).filter(Boolean))];
  if (!endungen.length) {
    zustand.zieleListe = [];
    zustand.ziel = null;
    zeige($("karte-ziel"), false);
    zeige($("karte-optionen"), false);
    zeige($("karte-start"), false);
    return;
  }

  zeige($("karte-ziel"), true);
  text($("ziel-status"), "Mögliche Zielformate werden ermittelt …");

  try {
    const daten = await holen(`/api/targets?ext=${encodeURIComponent(endungen.join(","))}`);
    zustand.zieleListe = daten.targets || [];

    if (daten.unknown && daten.unknown.length) {
      text($("ziel-status"),
        `Nicht unterstützt: ${daten.unknown.join(", ").toUpperCase()}. ` +
        `Diese Dateien werden übersprungen.`);
    } else if (!zustand.zieleListe.length) {
      text($("ziel-status"),
        "Für diese Mischung aus Dateitypen gibt es kein gemeinsames Zielformat. " +
        "Bitte die Dateien in getrennten Aufträgen umwandeln.");
    } else if (endungen.length > 1) {
      text($("ziel-status"),
        `${zustand.zieleListe.length} Zielformate, die für alle ${endungen.length} Dateitypen funktionieren.`);
    } else {
      text($("ziel-status"), `${zustand.zieleListe.length} mögliche Zielformate.`);
    }

    if (zustand.ziel && !zustand.zieleListe.some((z) => z.ext === zustand.ziel)) {
      zustand.ziel = null;
    }
    zieleZeichnen();
  } catch (fehler) {
    text($("ziel-status"), `Zielformate konnten nicht geladen werden: ${fehler.message}`);
  }
}

function zieleZeichnen() {
  const bereich = $("zielbereich");
  bereich.replaceChildren();

  const suche = $("zielsuche").value.trim().toLowerCase();
  const gefiltert = suche
    ? zustand.zieleListe.filter(
        (z) => z.ext.includes(suche) || z.label.toLowerCase().includes(suche)
      )
    : zustand.zieleListe;

  const gruppen = new Map();
  for (const ziel of gefiltert) {
    if (!gruppen.has(ziel.categoryLabel)) gruppen.set(ziel.categoryLabel, []);
    gruppen.get(ziel.categoryLabel).push(ziel);
  }

  if (!gruppen.size) {
    const leer = document.createElement("p");
    leer.className = "hinweis";
    leer.textContent = suche
      ? `Kein Zielformat passt zu „${$("zielsuche").value.trim()}“.`
      : "Keine Zielformate verfügbar.";
    bereich.append(leer);
  }

  for (const [kategorie, ziele] of gruppen) {
    const gruppe = document.createElement("div");
    gruppe.className = "zielgruppe";

    const titel = document.createElement("h3");
    titel.textContent = kategorie;

    const raster = document.createElement("div");
    raster.className = "zielraster";

    for (const ziel of ziele) {
      const knopf = document.createElement("button");
      knopf.type = "button";
      knopf.className = "zielknopf";
      knopf.setAttribute("aria-pressed", String(zustand.ziel === ziel.ext));

      const kuerzel = document.createElement("span");
      kuerzel.className = "kuerzel";
      kuerzel.textContent = ziel.ext.toUpperCase();

      const beschreibung = document.createElement("span");
      beschreibung.className = "beschreibung";
      beschreibung.textContent = ziel.label;

      knopf.append(kuerzel, beschreibung);

      if (!ziel.direct) {
        const weg = document.createElement("span");
        weg.className = "weg";
        weg.textContent = ziel.via ? `über ${ziel.via}` : "mehrstufig";
        knopf.append(weg);
        knopf.title =
          "Diese Umwandlung läuft über Zwischenschritte. " +
          "Das Ergebnis kann vom Original abweichen.";
      }
      if (ziel.note) knopf.title = ziel.note;

      knopf.addEventListener("click", () => zielWaehlen(ziel.ext));
      raster.append(knopf);
    }

    gruppe.append(titel, raster);
    bereich.append(gruppe);
  }
}

function zielWaehlen(ext) {
  zustand.ziel = zustand.ziel === ext ? null : ext;
  zieleZeichnen();
  optionenZeichnen();
  zusammenfassungAktualisieren();
  zeige($("karte-start"), Boolean(zustand.ziel));
}

/* ---------------------------------------------------------------- */
/* Einstellungen                                                     */
/* ---------------------------------------------------------------- */

const OPTIONSFELDER = {
  bild: [
    { schluessel: "quality", art: "bereich", beschriftung: "Bildqualität",
      min: 40, max: 100, standard: 88, einheit: "%",
      erklaerung: "Höhere Werte bedeuten bessere Qualität und größere Dateien." },
    { schluessel: "max_edge", art: "zahl", beschriftung: "Längste Kante begrenzen",
      min: 0, max: 20000, standard: 0, einheit: "Pixel",
      erklaerung: "0 bedeutet: Größe unverändert lassen." },
    { schluessel: "strip_metadata", art: "schalter", beschriftung: "Metadaten entfernen",
      standard: true,
      erklaerung: "Entfernt EXIF-Daten wie Aufnahmeort und Kameramodell." },
  ],
  ocr: [
    { schluessel: "ocr", art: "schalter", beschriftung: "Texterkennung (OCR) durchführen",
      standard: false,
      erklaerung: "Macht eingescannte Dokumente durchsuchbar. Verlängert die Bearbeitung deutlich." },
    { schluessel: "ocr_language", art: "auswahl", beschriftung: "Sprache der Texterkennung",
      standard: "deu+eng", abhaengigVon: "ocr",
      werte: [
        ["deu+eng", "Deutsch und Englisch"],
        ["deu", "Deutsch"],
        ["eng", "Englisch"],
        ["fra", "Französisch"],
        ["ita", "Italienisch"],
        ["spa", "Spanisch"],
        ["tur", "Türkisch"],
        ["rus", "Russisch"],
      ] },
  ],
  pdfklein: [
    { schluessel: "compress", art: "schalter", beschriftung: "PDF verkleinern",
      standard: false,
      erklaerung: "Reduziert die Auflösung eingebetteter Bilder." },
    { schluessel: "compress_preset", art: "auswahl", beschriftung: "Stufe der Verkleinerung",
      standard: "ebook", abhaengigVon: "compress",
      werte: [
        ["screen", "Bildschirm (72 dpi, kleinste Datei)"],
        ["ebook", "Standard (150 dpi)"],
        ["printer", "Druck (300 dpi)"],
        ["prepress", "Druckvorstufe (farbtreu)"],
      ] },
  ],
  video: [
    { schluessel: "crf", art: "bereich", beschriftung: "Videoqualität",
      min: 18, max: 34, standard: 23, einheit: "CRF", umgekehrt: true,
      erklaerung: "Kleinere Werte bedeuten bessere Qualität und größere Dateien." },
    { schluessel: "max_height", art: "auswahl", beschriftung: "Auflösung begrenzen",
      standard: "0",
      werte: [["0", "Unverändert"], ["2160", "4K (2160p)"], ["1080", "Full HD (1080p)"],
              ["720", "HD (720p)"], ["480", "SD (480p)"]] },
  ],
  audio: [
    { schluessel: "audio_bitrate", art: "auswahl", beschriftung: "Datenrate",
      standard: "",
      werte: [["", "Voreinstellung des Formats"], ["320k", "320 kbit/s (sehr hoch)"],
              ["192k", "192 kbit/s (hoch)"], ["128k", "128 kbit/s (Standard)"],
              ["64k", "64 kbit/s (Sprache)"]] },
    { schluessel: "sample_rate", art: "auswahl", beschriftung: "Abtastrate",
      standard: "0",
      werte: [["0", "Unverändert"], ["48000", "48 kHz"], ["44100", "44,1 kHz"],
              ["22050", "22,05 kHz"], ["16000", "16 kHz (Sprache)"]] },
  ],
  tabelle: [
    { schluessel: "excel_bom", art: "schalter", beschriftung: "Excel-kompatibles CSV",
      standard: true,
      erklaerung: "Schreibt eine Byte-Reihenfolge-Markierung, damit Excel Umlaute korrekt anzeigt." },
    { schluessel: "out_delimiter", art: "auswahl", beschriftung: "Trennzeichen",
      standard: ",",
      werte: [[",", "Komma"], [";", "Semikolon (deutsches Excel)"], ["\t", "Tabulator"], ["|", "Senkrechter Strich"]] },
  ],
};

// Zielformate, bei denen sich eine Texterkennung der Quelle lohnt.
const TEXTZIELE = new Set(["pdf", "pdfa", "txt", "docx", "odt", "md", "html", "rtf", "epub"]);

function optionsgruppen() {
  const ziel = zustand.ziel;
  if (!ziel) return [];
  const eintrag = zustand.zieleListe.find((z) => z.ext === ziel);
  const kategorie = eintrag ? eintrag.category : "";
  const gruppen = [];

  // Eingescannte Vorlagen brauchen eine Texterkennung, damit im Ergebnis
  // ueberhaupt Text steht - unabhaengig davon, ob das Ziel ein PDF ist.
  const scanQuelle = zustand.dateien.some(
    (e) => e.endung === "pdf" || ["jpg", "jpeg", "png", "tiff", "tif", "bmp"].includes(e.endung)
  );
  if (TEXTZIELE.has(ziel) && scanQuelle) gruppen.push("ocr");
  if (ziel === "pdf" || ziel === "pdfa") gruppen.push("pdfklein");
  if (kategorie === "image") gruppen.push("bild");
  if (kategorie === "video") gruppen.push("video");
  if (kategorie === "audio") gruppen.push("audio");
  if (ziel === "csv" || ziel === "tsv") gruppen.push("tabelle");
  return gruppen;
}

function optionenZeichnen() {
  const bereich = $("optionsbereich");
  bereich.replaceChildren();
  const gruppen = optionsgruppen();

  const mehrfach = zustand.dateien.length > 1;
  const zusammenfuehrbar = mehrfach && (zustand.ziel === "pdf" || zustand.ziel === "pdfa");

  if (!gruppen.length && !zusammenfuehrbar) {
    zeige($("karte-optionen"), false);
    return;
  }
  zeige($("karte-optionen"), true);

  if (zusammenfuehrbar) {
    bereich.append(
      feldSchalter({
        schluessel: "__merge",
        beschriftung: "Zu einem einzigen PDF zusammenfügen",
        standard: false,
        erklaerung: "Die Dateien werden in der Reihenfolge der Liste aneinandergehängt.",
      })
    );
  }

  for (const gruppe of gruppen) {
    for (const feld of OPTIONSFELDER[gruppe]) {
      bereich.append(feldBauen(feld));
    }
  }
  abhaengigkeitenPruefen();
}

function feldBauen(feld) {
  if (feld.art === "schalter") return feldSchalter(feld);
  if (feld.art === "auswahl") return feldAuswahl(feld);
  if (feld.art === "bereich") return feldBereich(feld);
  return feldZahl(feld);
}

function feldRahmen(feld, klasse) {
  const wrapper = document.createElement("div");
  wrapper.className = klasse || "option";
  wrapper.dataset.schluessel = feld.schluessel;
  if (feld.abhaengigVon) wrapper.dataset.abhaengigVon = feld.abhaengigVon;
  return wrapper;
}

function erklaerungAnhaengen(wrapper, feld) {
  if (!feld.erklaerung) return;
  const hinweis = document.createElement("span");
  hinweis.className = "option-erklaerung";
  hinweis.textContent = feld.erklaerung;
  wrapper.append(hinweis);
}

function feldSchalter(feld) {
  const wrapper = feldRahmen(feld, "option option-schalter");
  const kasten = document.createElement("input");
  kasten.type = "checkbox";
  kasten.id = `opt-${feld.schluessel}`;
  kasten.checked = Boolean(feld.standard);
  kasten.addEventListener("change", abhaengigkeitenPruefen);

  const textblock = document.createElement("div");
  const beschriftung = document.createElement("label");
  beschriftung.htmlFor = kasten.id;
  beschriftung.className = "feldbeschriftung";
  beschriftung.textContent = feld.beschriftung;
  textblock.append(beschriftung);
  erklaerungAnhaengen(textblock, feld);

  wrapper.append(kasten, textblock);
  return wrapper;
}

function feldAuswahl(feld) {
  const wrapper = feldRahmen(feld);
  const beschriftung = document.createElement("label");
  beschriftung.className = "feldbeschriftung";
  beschriftung.htmlFor = `opt-${feld.schluessel}`;
  beschriftung.textContent = feld.beschriftung;

  const auswahl = document.createElement("select");
  auswahl.id = `opt-${feld.schluessel}`;
  for (const [wert, anzeige] of feld.werte) {
    const eintrag = document.createElement("option");
    eintrag.value = wert;
    eintrag.textContent = anzeige;
    if (String(feld.standard) === wert) eintrag.selected = true;
    auswahl.append(eintrag);
  }
  wrapper.append(beschriftung, auswahl);
  erklaerungAnhaengen(wrapper, feld);
  return wrapper;
}

function feldBereich(feld) {
  const wrapper = feldRahmen(feld);
  const beschriftung = document.createElement("label");
  beschriftung.className = "feldbeschriftung";
  beschriftung.htmlFor = `opt-${feld.schluessel}`;

  const anzeige = document.createElement("span");
  anzeige.className = "option-wert";
  anzeige.textContent = ` ${feld.standard} ${feld.einheit || ""}`.trimEnd();
  beschriftung.textContent = feld.beschriftung + ":";
  beschriftung.append(anzeige);

  const regler = document.createElement("input");
  regler.type = "range";
  regler.id = `opt-${feld.schluessel}`;
  regler.min = String(feld.min);
  regler.max = String(feld.max);
  regler.value = String(feld.standard);
  regler.addEventListener("input", () => {
    anzeige.textContent = ` ${regler.value} ${feld.einheit || ""}`.trimEnd();
  });

  wrapper.append(beschriftung, regler);
  erklaerungAnhaengen(wrapper, feld);
  return wrapper;
}

function feldZahl(feld) {
  const wrapper = feldRahmen(feld);
  const beschriftung = document.createElement("label");
  beschriftung.className = "feldbeschriftung";
  beschriftung.htmlFor = `opt-${feld.schluessel}`;
  beschriftung.textContent = feld.einheit
    ? `${feld.beschriftung} (${feld.einheit})`
    : feld.beschriftung;

  const eingabe = document.createElement("input");
  eingabe.type = "number";
  eingabe.id = `opt-${feld.schluessel}`;
  eingabe.min = String(feld.min);
  eingabe.max = String(feld.max);
  eingabe.value = String(feld.standard);

  wrapper.append(beschriftung, eingabe);
  erklaerungAnhaengen(wrapper, feld);
  return wrapper;
}

function abhaengigkeitenPruefen() {
  for (const wrapper of $("optionsbereich").querySelectorAll("[data-abhaengig-von]")) {
    const quelle = $(`opt-${wrapper.dataset.abhaengigVon}`);
    const aktiv = quelle ? quelle.checked : true;
    wrapper.style.display = aktiv ? "" : "none";
  }
}

function optionenSammeln() {
  const optionen = {};
  let merge = false;
  for (const wrapper of $("optionsbereich").querySelectorAll("[data-schluessel]")) {
    const schluessel = wrapper.dataset.schluessel;
    const feld = $(`opt-${schluessel}`);
    if (!feld) continue;
    if (schluessel === "__merge") { merge = feld.checked; continue; }
    if (feld.type === "checkbox") optionen[schluessel] = feld.checked;
    else if (feld.value !== "") optionen[schluessel] = feld.value;
  }
  return { optionen, merge };
}

/* ---------------------------------------------------------------- */
/* Auftrag                                                           */
/* ---------------------------------------------------------------- */

function zusammenfassungAktualisieren() {
  const anzahl = zustand.dateien.length;
  const gesamt = zustand.dateien.reduce((summe, e) => summe + e.datei.size, 0);
  if (!anzahl || !zustand.ziel) {
    text($("auswahl-zusammenfassung"), "");
    return;
  }
  text(
    $("auswahl-zusammenfassung"),
    `${anzahl} ${anzahl === 1 ? "Datei" : "Dateien"} (${groesse(gesamt)}) ` +
    `nach ${zustand.ziel.toUpperCase()}`
  );
}

async function auftragStarten() {
  if (!zustand.dateien.length || !zustand.ziel) return;

  const zuGross = zustand.dateien.filter((e) => e.zuGross);
  if (zuGross.length) {
    meldung("fehler",
      `${zuGross.length} Datei(en) überschreiten die zulässige Größe und müssen entfernt werden.`);
    zeige($("karte-ergebnis"), true);
    return;
  }

  const { optionen, merge } = optionenSammeln();
  const formular = new FormData();
  for (const eintrag of zustand.dateien) formular.append("files", eintrag.datei, eintrag.datei.name);
  formular.append("target", zustand.ziel);
  formular.append("options", JSON.stringify(optionen));
  formular.append("merge", String(merge));

  $("starten").disabled = true;
  text($("starten"), "Wird hochgeladen …");
  zeige($("karte-ergebnis"), true);
  zeige($("fortschritt"), true);
  meldung("", "");
  $("ergebnisliste").replaceChildren();
  zeige($("paket-laden"), false);
  zeige($("jetzt-loeschen"), false);
  fortschrittSetzen(0, "Dateien werden übertragen …");

  try {
    const auftrag = await holen("/api/jobs", { method: "POST", body: formular });
    zustand.auftrag = auftrag;
    if (auftrag.rejected && auftrag.rejected.length) {
      meldung("warnung",
        "Nicht angenommen: " +
        auftrag.rejected.map((r) => `${r.name} (${r.reason})`).join("; "));
    }
    statusAbfragen();
  } catch (fehler) {
    meldung("fehler", `Der Auftrag konnte nicht angelegt werden: ${fehler.message}`);
    zeige($("fortschritt"), false);
  } finally {
    $("starten").disabled = false;
    text($("starten"), "Umwandlung starten");
  }
}

function fortschrittSetzen(anteil, beschreibung) {
  $("fortschritt-fuellung").style.width = `${Math.round(anteil * 100)}%`;
  text($("fortschritt-text"), beschreibung);
}

function statusAbfragen() {
  if (zustand.abfrage) clearTimeout(zustand.abfrage);
  if (!zustand.auftrag) return;

  const abfragen = async () => {
    try {
      const auftrag = await holen(`/api/jobs/${encodeURIComponent(zustand.auftrag.id)}`);
      zustand.auftrag = auftrag;
      ergebnisZeichnen(auftrag);

      if (auftrag.status === "wartet" || auftrag.status === "laeuft") {
        zustand.abfrage = setTimeout(abfragen, 1000);
      }
    } catch (fehler) {
      meldung("fehler", `Der Status konnte nicht abgerufen werden: ${fehler.message}`);
      zeige($("fortschritt"), false);
    }
  };
  abfragen();
}

function ergebnisZeichnen(auftrag) {
  const laeuft = auftrag.status === "wartet" || auftrag.status === "laeuft";
  const anteil = auftrag.total ? auftrag.done / auftrag.total : 0;
  zeige($("fortschritt"), laeuft);
  if (laeuft) {
    fortschrittSetzen(anteil, `${auftrag.done} von ${auftrag.total} Dateien verarbeitet …`);
  }

  const liste = $("ergebnisliste");
  liste.replaceChildren();

  for (const datei of auftrag.files || []) {
    const zeile = document.createElement("li");
    zeile.className = datei.status;

    const textblock = document.createElement("div");
    textblock.className = "ergebnis-text";

    const name = document.createElement("div");
    name.className = "ergebnis-name";
    name.textContent = datei.status === "fertig" ? datei.resultName : datei.name;
    textblock.append(name);

    const meta = document.createElement("div");
    meta.className = "ergebnis-meta";
    if (datei.status === "fertig") {
      meta.textContent = `${groesse(datei.size)} · ${datei.route} · ${datei.duration} s`;
    } else if (datei.status === "laeuft") {
      meta.textContent = "Wird umgewandelt …";
    } else if (datei.status === "wartet") {
      meta.textContent = "Wartet auf Bearbeitung";
    } else {
      meta.textContent = datei.name;
    }
    textblock.append(meta);

    if (datei.error) {
      const fehler = document.createElement("div");
      fehler.className = "ergebnis-fehler";
      fehler.textContent = datei.error;
      textblock.append(fehler);

      if (datei.detail) {
        const details = document.createElement("details");
        details.className = "ergebnis-detail";
        const titel = document.createElement("summary");
        titel.textContent = "Technische Einzelheiten";
        const inhalt = document.createElement("pre");
        inhalt.textContent = datei.detail;
        details.append(titel, inhalt);
        textblock.append(details);
      }
    }

    for (const notiz of datei.notes || []) {
      const hinweis = document.createElement("div");
      hinweis.className = "ergebnis-notiz";
      hinweis.textContent = notiz;
      textblock.append(hinweis);
    }

    zeile.append(textblock);

    if (datei.status === "fertig") {
      const laden = document.createElement("a");
      laden.className = "laden-knopf";
      laden.href = `/api/jobs/${encodeURIComponent(auftrag.id)}/dateien/${encodeURIComponent(datei.id)}`;
      laden.setAttribute("download", datei.resultName);
      laden.textContent = "Herunterladen";
      zeile.append(laden);
    }

    liste.append(zeile);
  }

  if (!laeuft) {
    if (auftrag.hasBundle) {
      const paket = $("paket-laden");
      paket.href = `/api/jobs/${encodeURIComponent(auftrag.id)}/paket`;
      paket.setAttribute("download", auftrag.bundleName);
      text(paket, auftrag.merge ? "Zusammengeführtes PDF laden" : "Alle Ergebnisse als ZIP laden");
      zeige(paket, true);
    }
    zeige($("jetzt-loeschen"), true);

    if (auftrag.status === "fertig" && !auftrag.failed) {
      meldung("erfolg",
        `${auftrag.successful} ${auftrag.successful === 1 ? "Datei wurde" : "Dateien wurden"} ` +
        `erfolgreich umgewandelt.`);
    } else if (auftrag.successful) {
      meldung("warnung",
        `${auftrag.successful} von ${auftrag.total} Dateien umgewandelt, ` +
        `${auftrag.failed} fehlgeschlagen.`);
    } else {
      meldung("fehler", auftrag.error || "Keine Datei konnte umgewandelt werden.");
    }

    const minuten = Math.ceil((auftrag.expiresInSeconds || 0) / 60);
    text($("aufbewahrung"),
      minuten > 0
        ? `Ergebnisse werden in ${minuten} Minute${minuten === 1 ? "" : "n"} automatisch gelöscht.`
        : "Die Ergebnisse werden in Kürze gelöscht.");
  }
}

async function auftragLoeschen() {
  if (!zustand.auftrag) return;
  try {
    await holen(`/api/jobs/${encodeURIComponent(zustand.auftrag.id)}`, { method: "DELETE" });
    meldung("erfolg", "Alle Dateien dieses Auftrags wurden vom Server gelöscht.");
    $("ergebnisliste").replaceChildren();
    zeige($("paket-laden"), false);
    zeige($("jetzt-loeschen"), false);
    text($("aufbewahrung"), "");
    zustand.auftrag = null;
  } catch (fehler) {
    meldung("fehler", `Löschen nicht möglich: ${fehler.message}`);
  }
}

function allesZuruecksetzen() {
  if (zustand.abfrage) clearTimeout(zustand.abfrage);
  zustand.dateien = [];
  zustand.ziel = null;
  zustand.zieleListe = [];
  zustand.auftrag = null;
  $("zielsuche").value = "";
  $("ergebnisliste").replaceChildren();
  $("optionsbereich").replaceChildren();
  dateilisteZeichnen();
  zeige($("karte-ziel"), false);
  zeige($("karte-optionen"), false);
  zeige($("karte-start"), false);
  zeige($("karte-ergebnis"), false);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* ---------------------------------------------------------------- */
/* Formatübersicht                                                   */
/* ---------------------------------------------------------------- */

function uebersichtZeichnen(kategorien) {
  const bereich = $("uebersicht");
  bereich.replaceChildren();
  for (const kategorie of kategorien || []) {
    const gruppe = document.createElement("div");
    gruppe.className = "uebersicht-gruppe";

    const titel = document.createElement("h3");
    titel.textContent = `${kategorie.label} (${kategorie.formats.length})`;

    const wolke = document.createElement("div");
    wolke.className = "kuerzelwolke";
    for (const format of kategorie.formats) {
      const kuerzel = document.createElement("span");
      kuerzel.textContent = format.ext.toUpperCase();
      kuerzel.title = format.label;
      wolke.append(kuerzel);
    }

    gruppe.append(titel, wolke);
    bereich.append(gruppe);
  }
}

function uebersichtUmschalten() {
  const schalter = $("uebersicht-schalter");
  const offen = schalter.getAttribute("aria-expanded") === "true";
  schalter.setAttribute("aria-expanded", String(!offen));
  text(schalter, offen ? "Übersicht anzeigen" : "Übersicht ausblenden");
  zeige($("uebersicht"), !offen);
}

document.addEventListener("DOMContentLoaded", start);
