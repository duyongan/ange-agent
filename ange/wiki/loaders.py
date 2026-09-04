"""原文加载器:v1 格式钉死 markdown / txt / pdf(PyMuPDF)/ url(httpx)。"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from pathlib import Path

import httpx

MAX_TEXT = 200_000  # 超长原文截断,防止把上下文打爆


def load_source(source: str) -> tuple[str, str]:
    """加载本地路径或 URL → (建议文件名, 纯文本)。"""
    source = source.strip()
    if re.match(r"^https?://", source):
        return _load_url(source)
    return _load_file(Path(source).expanduser())


def _load_file(p: Path) -> tuple[str, str]:
    if not p.exists():
        raise FileNotFoundError(f"文件不存在: {p}")
    if p.suffix.lower() == ".pdf":
        return p.name, _pdf_text(p)
    if p.suffix.lower() in {".md", ".markdown", ".txt", ""}:
        return p.name, p.read_text(encoding="utf-8", errors="replace")[:MAX_TEXT]
    raise ValueError(f"v1 不支持的格式: {p.suffix}(支持 md/txt/pdf/url)")


def _pdf_text(p: Path) -> str:
    import fitz  # pymupdf

    doc = fitz.open(p)
    try:
        parts = [page.get_text() for page in doc]
    finally:
        doc.close()
    return "\n".join(parts)[:MAX_TEXT]


def _load_url(url: str) -> tuple[str, str]:
    resp = httpx.get(url, follow_redirects=True, timeout=30, headers={"User-Agent": "ange-agent/0.1"})
    resp.raise_for_status()
    ctype = resp.headers.get("content-type", "")
    if "html" in ctype:
        name = re.sub(r"[^A-Za-z0-9_-]+", "-", url.split("//", 1)[-1])[:60] + ".md"
        return name, _html_to_text(resp.text)[:MAX_TEXT]
    return url.rsplit("/", 1)[-1] or "download.bin", resp.text[:MAX_TEXT]


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "nav", "header", "footer"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in self._SKIP:
            self._skip_depth += 1
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth and data.strip():
            self.parts.append(data)


def _html_to_text(html_text: str) -> str:
    parser = _TextExtractor()
    parser.feed(html.unescape(html_text))
    text = "".join(parser.parts)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
