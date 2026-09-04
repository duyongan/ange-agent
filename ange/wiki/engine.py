"""Wiki 引擎核心:raw/(不可变)/ *.md 页面 / index.md / log.md + ingest/lint/query。

query 走渐进式披露:系统提示只放 index.md,agent 经 wiki_search / wiki_read 按需取页。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .page import Page

UTC = timezone.utc


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class WikiEngine:
    def __init__(self, wiki_dir: Path) -> None:
        self.dir = wiki_dir
        self.raw_dir = wiki_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = wiki_dir / "index.md"
        self.log_path = wiki_dir / "log.md"
        for p in (self.index_path, self.log_path):
            if not p.exists():
                p.write_text("", encoding="utf-8")

    # ---------- 页面存取 ----------
    def pages(self) -> list[Page]:
        out = []
        for md in sorted(self.dir.glob("*.md")):
            if md.name in {"index.md", "log.md"}:
                continue
            out.append(Page.parse(md.read_text(encoding="utf-8"), md))
        return out

    def read(self, title: str) -> Page | None:
        p = self.dir / f"{Page.slug(title)}.md"
        return Page.parse(p.read_text(encoding="utf-8"), p) if p.exists() else None

    def write(self, page: Page, source: str = "agent") -> Path:
        page.frontmatter.setdefault("created", _now())
        page.frontmatter["updated"] = _now()
        path = page.save(self.dir)
        self.reindex()
        self.append_log("write", {"title": page.title, "source": source})
        return path

    def append_log(self, action: str, detail: dict) -> None:
        line = f"- {_now()} {action} {json.dumps(detail, ensure_ascii=False)}\n"
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(line)

    # ---------- index ----------
    def reindex(self) -> None:
        lines = ["# Wiki Index", ""]
        for page in self.pages():
            desc = str(page.frontmatter.get("description", ""))[:80]
            links = ", ".join(sorted(set(page.links()))[:8])
            row = f"- [[{page.title}]] — {desc}"
            if links:
                row += f"(关联: {links})"
            lines.append(row)
        lines.append("")
        self.index_path.write_text("\n".join(lines), encoding="utf-8")

    def index_for_prompt(self, max_chars: int = 4000) -> str:
        text = self.index_path.read_text(encoding="utf-8")
        return text[:max_chars] if len(text) > max_chars else text + ("\n(wiki 为空)" if len(text) < 30 else "")

    # ---------- raw 摄入 ----------
    def store_raw(self, filename: str, text: str) -> Path:
        safe = Page.slug(filename)
        raw_path = self.raw_dir / f"{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{safe}"
        raw_path.write_text(text, encoding="utf-8")
        return raw_path

    # ---------- query(渐进式披露的取页面) ----------
    def search(self, query: str, limit: int = 8) -> str:
        q = query.lower()
        scored: list[tuple[int, str]] = []
        for page in self.pages():
            haystack = (page.title + " " + str(page.frontmatter.get("tags", "")) + " " + page.body).lower()
            score = haystack.count(q)
            if score:
                scored.append((score, page.title))
        if not scored:
            return "(无命中)"
        scored.sort(reverse=True)
        return "\n".join(f"- {t}(命中 {s} 次)" for s, t in scored[:limit])

    # ---------- lint ----------
    def lint(self) -> list[str]:
        """断链 / 孤儿页 / 索引过期 三查。"""
        issues: list[str] = []
        pages = self.pages()
        titles = {p.title for p in pages}
        linked: set[str] = set()
        for p in pages:
            for target in p.links():
                linked.add(target)
                if target not in titles:
                    issues.append(f"断链: [[{p.title}]] → [[{target}]] 不存在")
        for p in pages:
            if p.title not in linked and len(pages) > 1:
                issues.append(f"孤儿页: [[{p.title}]] 无任何入链")
        index_text = self.index_path.read_text(encoding="utf-8")
        for t in titles:
            if f"[[{t}]]" not in index_text:
                issues.append(f"索引过期: [[{t}]] 未出现在 index.md")
                break
        return issues

    def fix_lint(self) -> list[str]:
        """能自动修的只有索引过期;断链/孤儿交给 /evolve 的 LLM 复盘处理。"""
        self.reindex()
        return self.lint()
