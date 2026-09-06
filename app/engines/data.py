"""Engines fuer strukturierte Daten- und Konfigurationsformate.

Alles laeuft in Python ohne externe Programme. XML wird bewusst mit
defusedxml gelesen, damit praeparierte Dateien keine Entity-Expansion oder
externe Referenzen ausloesen koennen.
"""

from __future__ import annotations

import configparser
import csv
import io
import json
import re
from pathlib import Path
from typing import Any

from app.engines.base import ConversionError, Engine, StepContext

# --- Tabellarische Formate --------------------------------------------
TABLE_IN = ("csv", "tsv", "xlsx", "json", "jsonl")
TABLE_OUT = ("csv", "tsv", "xlsx", "json", "jsonl", "html", "md", "xml", "sql")

# --- Baumartige Formate -----------------------------------------------
TREE_IN = ("json", "yaml", "toml", "ini", "xml")
TREE_OUT = ("json", "yaml", "toml", "ini", "xml")

_MAX_CELLS = 5_000_000
_SQL_NAME = re.compile(r"[^A-Za-z0-9_]+")


def _sniff_delimiter(sample: str, default: str = ",") -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return default


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


class TableEngine(Engine):
    """Wandelt Tabellen zwischen CSV, Excel, JSON, HTML, Markdown, XML und SQL."""

    name = "tabellen"
    label = "Tabellenumwandlung"
    cost = 7
    source_exts = TABLE_IN
    target_exts = TABLE_OUT

    def supports(self, src: str, dst: str) -> bool:
        if not super().supports(src, dst):
            return False
        # Hierarchische Umwandlungen wie JSON -> XML gehoeren zur Baum-Engine,
        # die die Struktur erhaelt. Hier geht es ausschliesslich um Tabellen.
        if src == "json" and dst == "xml":
            return False
        return True

    def edge_cost(self, src: str, dst: str) -> int:
        if dst in {"html", "md"}:
            return self.cost + 3
        return self.cost

    def convert(self, src: Path, dst: Path, src_ext: str, dst_ext: str, ctx: StepContext) -> Path:
        header, rows = self._load(src, src_ext, ctx)
        self._write(dst, dst_ext, header, rows, ctx)
        return dst

    # -- Lesen -------------------------------------------------------
    def _load(self, src: Path, src_ext: str, ctx: StepContext) -> tuple[list[str], list[list[Any]]]:
        if src_ext in {"csv", "tsv"}:
            return self._load_delimited(src, src_ext, ctx)
        if src_ext == "xlsx":
            return self._load_xlsx(src, ctx)
        if src_ext == "jsonl":
            records = []
            for line in _read_text(src).splitlines():
                line = line.strip()
                if line:
                    records.append(json.loads(line))
            return self._records_to_table(records)
        if src_ext == "json":
            data = json.loads(_read_text(src))
            if isinstance(data, dict):
                for value in data.values():
                    if isinstance(value, list):
                        data = value
                        break
            if not isinstance(data, list):
                raise ConversionError(
                    "Diese JSON-Datei enthaelt keine Tabelle.",
                    "Erwartet wird eine Liste von Objekten, zum Beispiel [{\"a\": 1}, {\"a\": 2}].",
                )
            return self._records_to_table(data)
        raise ConversionError(f"{src_ext.upper()} wird von der Tabellenumwandlung nicht gelesen.")

    def _load_delimited(self, src: Path, src_ext: str, ctx: StepContext):
        text = _read_text(src)
        delimiter = ctx.opt_str("delimiter") or ("\t" if src_ext == "tsv" else _sniff_delimiter(text[:8192]))
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        rows = [row for row in reader]
        if not rows:
            return [], []
        header = [str(cell).strip() for cell in rows[0]]
        return header, [list(row) for row in rows[1:]]

    def _load_xlsx(self, src: Path, ctx: StepContext):
        try:
            from openpyxl import load_workbook
        except ImportError as exc:  # pragma: no cover
            raise ConversionError("Das Modul openpyxl ist nicht installiert.", str(exc)) from exc

        # data_only=True liefert die zuletzt berechneten Werte statt Formeln.
        workbook = load_workbook(src, read_only=True, data_only=True)
        sheet_name = ctx.opt_str("sheet")
        sheet = workbook[sheet_name] if sheet_name and sheet_name in workbook.sheetnames else workbook.worksheets[0]
        if len(workbook.worksheets) > 1 and not sheet_name:
            ctx.note(
                f"Die Mappe enthaelt {len(workbook.worksheets)} Tabellenblaetter. "
                f"Umgewandelt wurde '{sheet.title}'."
            )
        rows_iter = sheet.iter_rows(values_only=True)
        header_row = next(rows_iter, None)
        header = [str(c) if c is not None else f"Spalte{i + 1}" for i, c in enumerate(header_row or [])]
        rows: list[list[Any]] = []
        cells = 0
        for row in rows_iter:
            values = ["" if v is None else v for v in row]
            cells += len(values)
            if cells > _MAX_CELLS:
                raise ConversionError("Die Tabelle ist zu gross fuer die Umwandlung.")
            rows.append(list(values))
        workbook.close()
        return header, rows

    @staticmethod
    def _records_to_table(records: list[Any]) -> tuple[list[str], list[list[Any]]]:
        header: list[str] = []
        seen: set[str] = set()
        for record in records:
            if isinstance(record, dict):
                for key in record:
                    if key not in seen:
                        seen.add(key)
                        header.append(str(key))
        if not header:
            header = ["wert"]
            return header, [[r] for r in records]
        rows = []
        for record in records:
            if isinstance(record, dict):
                rows.append([_flatten(record.get(key, "")) for key in header])
            else:
                rows.append([_flatten(record)] + [""] * (len(header) - 1))
        return header, rows

    # -- Schreiben ---------------------------------------------------
    def _write(self, dst: Path, dst_ext: str, header: list[str], rows: list[list[Any]], ctx: StepContext) -> None:
        if dst_ext in {"csv", "tsv"}:
            delimiter = ctx.opt_str("out_delimiter") or ("\t" if dst_ext == "tsv" else ",")
            # BOM, damit Excel unter Windows UTF-8 korrekt erkennt.
            encoding = "utf-8-sig" if ctx.opt_bool("excel_bom", True) and dst_ext == "csv" else "utf-8"
            with dst.open("w", newline="", encoding=encoding) as handle:
                writer = csv.writer(handle, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL)
                if header:
                    writer.writerow(header)
                writer.writerows(rows)
            return

        if dst_ext == "xlsx":
            from openpyxl import Workbook

            workbook = Workbook(write_only=True)
            sheet = workbook.create_sheet(title=(ctx.opt_str("sheet_title") or "Tabelle")[:31])
            if header:
                sheet.append(header)
            for row in rows:
                sheet.append([_excel_safe(cell) for cell in row])
            workbook.save(dst)
            return

        if dst_ext == "json":
            records = [dict(zip(header, row)) for row in rows]
            dst.write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            return

        if dst_ext == "jsonl":
            with dst.open("w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(dict(zip(header, row)), ensure_ascii=False, default=str) + "\n")
            return

        if dst_ext == "html":
            dst.write_text(_table_html(header, rows, ctx.opt_str("title", dst.stem)), encoding="utf-8")
            return

        if dst_ext == "md":
            dst.write_text(_table_markdown(header, rows), encoding="utf-8")
            return

        if dst_ext == "xml":
            dst.write_text(_table_xml(header, rows, ctx.opt_str("record_tag", "eintrag")), encoding="utf-8")
            return

        if dst_ext == "sql":
            table = _SQL_NAME.sub("_", ctx.opt_str("table", dst.stem) or "daten").strip("_") or "daten"
            dst.write_text(_table_sql(table, header, rows), encoding="utf-8")
            return

        raise ConversionError(f"{dst_ext.upper()} wird von der Tabellenumwandlung nicht geschrieben.")


class TreeEngine(Engine):
    """Wandelt hierarchische Konfigurations- und Datenformate ineinander."""

    name = "strukturdaten"
    label = "Strukturdatenumwandlung"
    cost = 6
    source_exts = TREE_IN
    target_exts = TREE_OUT

    def convert(self, src: Path, dst: Path, src_ext: str, dst_ext: str, ctx: StepContext) -> Path:
        data = self._load(src, src_ext)
        self._write(dst, dst_ext, data, ctx)
        return dst

    def _load(self, src: Path, src_ext: str) -> Any:
        text = _read_text(src)
        try:
            if src_ext == "json":
                return json.loads(text)
            if src_ext == "yaml":
                import yaml

                # safe_load fuehrt keine Python-Objekte aus.
                return yaml.safe_load(text)
            if src_ext == "toml":
                import tomllib

                return tomllib.loads(text)
            if src_ext == "ini":
                parser = configparser.ConfigParser(interpolation=None)
                parser.read_string(text)
                return {
                    section: dict(parser.items(section))
                    for section in [*parser.sections(), *(["DEFAULT"] if parser.defaults() else [])]
                }
            if src_ext == "xml":
                from defusedxml import ElementTree as SafeET

                return _xml_to_dict(SafeET.fromstring(text))
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(
                f"Die {src_ext.upper()}-Datei konnte nicht gelesen werden.",
                f"{type(exc).__name__}: {exc}",
            ) from exc
        raise ConversionError(f"{src_ext.upper()} wird hier nicht gelesen.")

    def _write(self, dst: Path, dst_ext: str, data: Any, ctx: StepContext) -> None:
        try:
            if dst_ext == "json":
                dst.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
                return
            if dst_ext == "yaml":
                import yaml

                dst.write_text(
                    yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
                    encoding="utf-8",
                )
                return
            if dst_ext == "toml":
                import tomli_w

                if not isinstance(data, dict):
                    raise ConversionError("TOML benoetigt eine Zuordnung auf oberster Ebene.")
                dst.write_bytes(tomli_w.dumps(_toml_safe(data)).encode("utf-8"))
                return
            if dst_ext == "ini":
                if not isinstance(data, dict):
                    raise ConversionError("INI benoetigt eine Zuordnung auf oberster Ebene.")
                parser = configparser.ConfigParser(interpolation=None)
                for section, values in data.items():
                    parser[str(section)] = (
                        {str(k): str(v) for k, v in values.items()}
                        if isinstance(values, dict)
                        else {"wert": str(values)}
                    )
                with dst.open("w", encoding="utf-8") as handle:
                    parser.write(handle)
                return
            if dst_ext == "xml":
                dst.write_text(
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    + _dict_to_xml(data, ctx.opt_str("root_tag", "daten") or "daten", 0),
                    encoding="utf-8",
                )
                return
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(
                f"Die Daten liessen sich nicht als {dst_ext.upper()} schreiben.",
                f"{type(exc).__name__}: {exc}",
            ) from exc
        raise ConversionError(f"{dst_ext.upper()} wird hier nicht geschrieben.")


# --- Hilfsfunktionen ---------------------------------------------------

def _flatten(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _excel_safe(value: Any) -> Any:
    """Verhindert, dass Zellinhalte in Excel als Formel ausgefuehrt werden."""
    if isinstance(value, str) and value[:1] in {"=", "+", "-", "@"}:
        return "'" + value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _escape(text: Any) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _table_html(header: list[str], rows: list[list[Any]], title: str) -> str:
    head = "".join(f"<th>{_escape(c)}</th>" for c in header)
    body = "".join(
        "<tr>" + "".join(f"<td>{_escape(cell)}</td>" for cell in row) + "</tr>" for row in rows
    )
    return (
        "<!doctype html>\n<html lang=\"de\">\n<head>\n<meta charset=\"utf-8\">\n"
        f"<title>{_escape(title)}</title>\n<style>\n"
        "body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:2rem;color:#111}\n"
        "table{border-collapse:collapse;width:100%}\n"
        "th,td{border:1px solid #ccd;padding:.45rem .6rem;text-align:left;font-size:14px}\n"
        "th{background:#eef2f7}\ntr:nth-child(even) td{background:#fafbfd}\n"
        "</style>\n</head>\n<body>\n"
        f"<h1>{_escape(title)}</h1>\n<table>\n<thead><tr>{head}</tr></thead>\n"
        f"<tbody>{body}</tbody>\n</table>\n</body>\n</html>\n"
    )


def _table_markdown(header: list[str], rows: list[list[Any]]) -> str:
    def cell(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = ["| " + " | ".join(cell(c) for c in header) + " |"]
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in rows:
        padded = list(row) + [""] * (len(header) - len(row))
        lines.append("| " + " | ".join(cell(c) for c in padded[: len(header)]) + " |")
    return "\n".join(lines) + "\n"


def _xml_tag(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", str(name)).strip("_")
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"f_{cleaned}" if cleaned else "feld"
    return cleaned


def _table_xml(header: list[str], rows: list[list[Any]], record_tag: str) -> str:
    tag = _xml_tag(record_tag)
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', "<daten>"]
    for row in rows:
        parts.append(f"  <{tag}>")
        for name, value in zip(header, row):
            field = _xml_tag(name)
            parts.append(f"    <{field}>{_escape(value)}</{field}>")
        parts.append(f"  </{tag}>")
    parts.append("</daten>")
    return "\n".join(parts) + "\n"


def _table_sql(table: str, header: list[str], rows: list[list[Any]]) -> str:
    columns = [_SQL_NAME.sub("_", str(c)).strip("_") or f"spalte{i}" for i, c in enumerate(header, 1)]
    lines = [
        f"CREATE TABLE IF NOT EXISTS {table} (",
        ",\n".join(f"  {c} TEXT" for c in columns),
        ");",
        "",
    ]
    for row in rows:
        values = []
        for cell in list(row) + [""] * (len(columns) - len(row)):
            if cell is None or cell == "":
                values.append("NULL")
            elif isinstance(cell, (int, float)) and not isinstance(cell, bool):
                values.append(str(cell))
            else:
                values.append("'" + str(cell).replace("'", "''") + "'")
        lines.append(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(values)});")
    return "\n".join(lines) + "\n"


def _xml_to_dict(element) -> Any:
    result: dict[str, Any] = {}
    if element.attrib:
        result.update({f"@{k}": v for k, v in element.attrib.items()})
    children = list(element)
    if not children:
        text = (element.text or "").strip()
        if not result:
            return text
        if text:
            result["#text"] = text
        return result
    for child in children:
        value = _xml_to_dict(child)
        if child.tag in result:
            if not isinstance(result[child.tag], list):
                result[child.tag] = [result[child.tag]]
            result[child.tag].append(value)
        else:
            result[child.tag] = value
    return result


def _dict_to_xml(data: Any, tag: str, depth: int) -> str:
    indent = "  " * depth
    tag = _xml_tag(tag)
    if isinstance(data, dict):
        inner = "".join(_dict_to_xml(value, key, depth + 1) for key, value in data.items())
        return f"{indent}<{tag}>\n{inner}{indent}</{tag}>\n"
    if isinstance(data, list):
        return "".join(_dict_to_xml(item, "eintrag", depth) for item in data)
    return f"{indent}<{tag}>{_escape(data)}</{tag}>\n"


def _toml_safe(data: Any) -> Any:
    """TOML kennt keine Nullwerte - diese werden zu leeren Zeichenketten."""
    if isinstance(data, dict):
        return {str(k): _toml_safe(v) for k, v in data.items() if v is not None}
    if isinstance(data, list):
        return [_toml_safe(v) for v in data if v is not None]
    if isinstance(data, (str, int, float, bool)):
        return data
    return str(data)


def engines() -> list[Engine]:
    return [TableEngine(), TreeEngine()]
