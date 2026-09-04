"""搜索工具:文件名 glob + 内容 grep,纯 Python 免外部依赖。"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from langchain_core.tools import tool

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".ange", "dist", "target"}
MAX_HITS = 60


def _walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        yield Path(dirpath), filenames


@tool
def search_files(pattern: str, content: str = "", directory: str = ".") -> str:
    """按文件名 glob(必填)与内容正则(可选)搜索目录。返回匹配文件与命中行,最多 60 条。

    例:search_files(pattern="*.py", content="def main", directory="src")
    """
    root = Path(directory).expanduser().resolve()
    hits: list[str] = []
    rx = re.compile(content) if content else None
    for dirpath, filenames in _walk(root):
        for fn in filenames:
            if not fnmatch.fnmatch(fn, pattern):
                continue
            fpath = dirpath / fn
            if rx is None:
                hits.append(str(fpath))
            else:
                try:
                    text = fpath.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for i, line in enumerate(text.splitlines(), 1):
                    if rx.search(line):
                        hits.append(f"{fpath}:{i}: {line.strip()[:160]}")
            if len(hits) >= MAX_HITS:
                hits.append(f"…(截断至 {MAX_HITS} 条)")
                return "\n".join(hits)
    return "\n".join(hits) or "(无匹配)"
