"""Shared HTML → plain text for Odoo chatter / notes."""

import html
from html.parser import HTMLParser
from typing import Any, List


class _HTMLToText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: List[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4"):
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "table", "ul", "ol"):
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    def text(self) -> str:
        return "".join(self._chunks)


def html_to_plain_text(body: str) -> str:
    raw = (body or "").strip()
    if not raw:
        return ""
    if "<" in raw and ">" in raw:
        parser = _HTMLToText()
        parser.feed(raw)
        parser.close()
        text = parser.text()
    else:
        text = raw
    text = html.unescape(text)
    lines = [ln.rstrip() for ln in text.splitlines()]
    return "\n".join(lines).strip()
