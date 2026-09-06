"""Engines fuer E-Mail-Dateien.

E-Mails aus Outlook (MSG) oder als MIME-Datei (EML) werden in ein lesbares
HTML- bzw. Textdokument ueberfuehrt. Von dort aus fuehrt der Weg ueber
LibreOffice weiter zu PDF - der ueblichen Form fuer die Aktenablage.
"""

from __future__ import annotations

import email
import email.policy
import html as html_lib
import mailbox
from email.header import decode_header, make_header
from email.message import EmailMessage
from pathlib import Path

from app.engines.base import ConversionError, Engine, StepContext

_HEADERS = [
    ("From", "Von"),
    ("To", "An"),
    ("Cc", "Kopie"),
    ("Bcc", "Blindkopie"),
    ("Date", "Datum"),
    ("Subject", "Betreff"),
]


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _render_html(headers: list[tuple[str, str]], body_html: str, body_text: str, attachments: list[str]) -> str:
    rows = "".join(
        f"<tr><th>{html_lib.escape(name)}</th><td>{html_lib.escape(value)}</td></tr>"
        for name, value in headers
        if value
    )
    if body_html.strip():
        content = body_html
    else:
        content = f"<pre class=\"text\">{html_lib.escape(body_text)}</pre>"
    anhang = ""
    if attachments:
        items = "".join(f"<li>{html_lib.escape(name)}</li>" for name in attachments)
        anhang = f"<h2>Anhaenge</h2>\n<ul class=\"anhang\">{items}</ul>"
    return (
        "<!doctype html>\n<html lang=\"de\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<title>E-Mail</title>\n<style>\n"
        "body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:2rem;color:#111;line-height:1.5}\n"
        "table.kopf{border-collapse:collapse;margin-bottom:1.5rem;width:100%}\n"
        "table.kopf th{text-align:left;padding:.3rem .8rem .3rem 0;vertical-align:top;"
        "white-space:nowrap;color:#445;width:1%}\n"
        "table.kopf td{padding:.3rem 0;word-break:break-word}\n"
        "hr{border:0;border-top:1px solid #ccd;margin:1.5rem 0}\n"
        "pre.text{white-space:pre-wrap;word-wrap:break-word;font-family:inherit;font-size:14px}\n"
        "ul.anhang{padding-left:1.2rem}\n"
        "</style>\n</head>\n<body>\n"
        f"<table class=\"kopf\">{rows}</table>\n<hr>\n{content}\n{anhang}\n</body>\n</html>\n"
    )


def _render_text(headers: list[tuple[str, str]], body_text: str, attachments: list[str]) -> str:
    lines = [f"{name}: {value}" for name, value in headers if value]
    lines.append("-" * 60)
    lines.append(body_text.strip())
    if attachments:
        lines.append("")
        lines.append("Anhaenge:")
        lines.extend(f"  - {name}" for name in attachments)
    return "\n".join(lines) + "\n"


def _parts_from_message(message: EmailMessage) -> tuple[str, str, list[str]]:
    body_html = ""
    body_text = ""
    attachments: list[str] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or "").lower()
        content_type = part.get_content_type()
        if disposition == "attachment":
            attachments.append(_decode(part.get_filename()) or f"({content_type})")
            continue
        try:
            payload = part.get_content()
        except Exception:
            raw = part.get_payload(decode=True) or b""
            payload = raw.decode(part.get_content_charset() or "utf-8", "replace")
        if content_type == "text/html" and not body_html:
            body_html = payload if isinstance(payload, str) else ""
        elif content_type == "text/plain" and not body_text:
            body_text = payload if isinstance(payload, str) else ""
        elif disposition == "inline" and part.get_filename():
            attachments.append(_decode(part.get_filename()))
    return body_html, body_text, attachments


class EmlEngine(Engine):
    name = "eml"
    label = "E-Mail (MIME)"
    cost = 8
    source_exts = ("eml", "mbox")
    target_exts = ("html", "txt")

    def convert(self, src: Path, dst: Path, src_ext: str, dst_ext: str, ctx: StepContext) -> Path:
        if src_ext == "mbox":
            return self._convert_mbox(src, dst, dst_ext, ctx)

        raw = src.read_bytes()
        try:
            message = email.message_from_bytes(raw, policy=email.policy.default)
        except Exception as exc:
            raise ConversionError("Die E-Mail-Datei konnte nicht gelesen werden.", str(exc)) from exc

        headers = [(german, _decode(message.get(field))) for field, german in _HEADERS]
        body_html, body_text, attachments = _parts_from_message(message)  # type: ignore[arg-type]
        if attachments:
            ctx.note(
                f"Die E-Mail enthaelt {len(attachments)} Anhang/Anhaenge. Diese sind im "
                "Ergebnis nur namentlich aufgefuehrt, nicht eingebettet."
            )
        if dst_ext == "html":
            dst.write_text(_render_html(headers, body_html, body_text, attachments), encoding="utf-8")
        else:
            dst.write_text(_render_text(headers, body_text or _strip_tags(body_html), attachments), encoding="utf-8")
        return dst

    def _convert_mbox(self, src: Path, dst: Path, dst_ext: str, ctx: StepContext) -> Path:
        box = mailbox.mbox(str(src))
        blocks: list[str] = []
        count = 0
        try:
            for message in box:
                count += 1
                headers = [(german, _decode(message.get(field))) for field, german in _HEADERS]
                body_html, body_text, attachments = _parts_from_message(message)  # type: ignore[arg-type]
                if dst_ext == "html":
                    blocks.append(
                        f"<section class=\"mail\">\n"
                        + _render_html(headers, body_html, body_text, attachments)
                        .split("<body>\n", 1)[-1]
                        .rsplit("</body>", 1)[0]
                        + "\n</section>\n<hr class=\"trenner\">"
                    )
                else:
                    blocks.append(_render_text(headers, body_text or _strip_tags(body_html), attachments))
        finally:
            box.close()

        if not count:
            raise ConversionError("Das Mailbox-Archiv enthaelt keine Nachrichten.")
        ctx.note(f"{count} Nachrichten aus dem Archiv wurden zusammengefasst.")
        if dst_ext == "html":
            dst.write_text(
                "<!doctype html>\n<html lang=\"de\">\n<head>\n<meta charset=\"utf-8\">\n"
                "<title>Mailbox-Archiv</title>\n<style>\n"
                "body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:2rem;line-height:1.5}\n"
                "hr.trenner{border:0;border-top:3px double #99a;margin:2.5rem 0}\n"
                "table{border-collapse:collapse;margin-bottom:1rem}\n"
                "th{text-align:left;padding-right:.8rem;color:#445;white-space:nowrap}\n"
                "pre.text{white-space:pre-wrap;font-family:inherit}\n"
                "</style>\n</head>\n<body>\n" + "\n".join(blocks) + "\n</body>\n</html>\n",
                encoding="utf-8",
            )
        else:
            dst.write_text(("\n\n" + "=" * 60 + "\n\n").join(blocks), encoding="utf-8")
        return dst


class MsgEngine(Engine):
    name = "msg"
    label = "Outlook-Nachricht"
    cost = 9
    source_exts = ("msg",)
    target_exts = ("html", "txt", "eml")

    def convert(self, src: Path, dst: Path, src_ext: str, dst_ext: str, ctx: StepContext) -> Path:
        try:
            import extract_msg
        except ImportError as exc:  # pragma: no cover
            raise ConversionError("Das Modul extract_msg ist nicht installiert.", str(exc)) from exc

        try:
            message = extract_msg.openMsg(str(src))
        except Exception as exc:
            raise ConversionError("Die Outlook-Nachricht konnte nicht geoeffnet werden.", str(exc)) from exc

        try:
            if dst_ext == "eml":
                data = message.asEmailMessage().as_bytes()
                dst.write_bytes(data)
                return dst

            headers = [
                ("Von", message.sender or ""),
                ("An", message.to or ""),
                ("Kopie", message.cc or ""),
                ("Datum", str(message.date or "")),
                ("Betreff", message.subject or ""),
            ]
            attachments = [
                (getattr(a, "longFilename", None) or getattr(a, "shortFilename", None) or "Anhang")
                for a in (message.attachments or [])
            ]
            body_text = message.body or ""
            body_html = ""
            raw_html = getattr(message, "htmlBody", None)
            if raw_html:
                body_html = raw_html.decode("utf-8", "replace") if isinstance(raw_html, bytes) else str(raw_html)

            if attachments:
                ctx.note(f"Die Nachricht enthaelt {len(attachments)} Anhang/Anhaenge (nur namentlich aufgefuehrt).")
            if dst_ext == "html":
                dst.write_text(_render_html(headers, body_html, body_text, attachments), encoding="utf-8")
            else:
                dst.write_text(_render_text(headers, body_text or _strip_tags(body_html), attachments), encoding="utf-8")
        finally:
            try:
                message.close()
            except Exception:
                pass
        return dst


def _strip_tags(markup: str) -> str:
    import re

    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", markup)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html_lib.unescape(text).strip()


def engines() -> list[Engine]:
    return [EmlEngine(), MsgEngine()]
