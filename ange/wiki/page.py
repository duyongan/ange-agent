"""Wiki 页面模型:frontmatter + 正文 + [[wikilink]]。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:#[^\]]*)?\]\]")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def _dump_yaml_value(v: Any) -> str:
    if isinstance(v, list):
        return "[" + ", ".join(str(x) for x in v) + "]"
    s = str(v)
    return f'"{s}"' if any(c in s for c in ":[]#") and not s.startswith('"') else s


@dataclass
class Page:
    title: str  # 同时是文件名(title.md)
    body: str = ""
    frontmatter: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None

    @staticmethod
    def slug(title: str) -> str:
        """文件名安全化:非法字符 → -,保留中文。"""
        return re.sub(r"[\\/:*?\"<>|]+", "-", title).strip() or "untitled"

    @classmethod
    def parse(cls, text: str, path: Path | None = None) -> "Page":
        fm: dict[str, Any] = {}
        m = FRONTMATTER_RE.match(text)
        if m:
            import yaml

            try:
                fm = yaml.safe_load(m.group(1)) or {}
            except yaml.YAMLError:
                fm = {}
            text = text[m.end():]
        title = str(fm.get("title") or (path.stem if path else "untitled"))
        return cls(title=title, body=text.rstrip() + "\n", frontmatter=fm, path=path)

    def render(self) -> str:
        lines = ["---"]
        for k, v in self.frontmatter.items():
            lines.append(f"{k}: {_dump_yaml_value(v)}")
        lines += ["---", ""]
        return "\n".join(lines) + self.body

    def links(self) -> list[str]:
        return [m.group(1).strip() for m in WIKILINK_RE.finditer(self.body)]

    def save(self, wiki_dir: Path) -> Path:
        p = wiki_dir / f"{self.slug(self.title)}.md"
        self.frontmatter["title"] = self.title
        p.write_text(self.render(), encoding="utf-8")
        self.path = p
        return p
