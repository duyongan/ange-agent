"""结局信号:双层。

层1 代理信号 —— LangChain callback 在工具执行现场记录成败(快,但瞎)
层2 复盘自评 —— review.py 每轮异步让 LLM 打分(慢,但看得见)

统一写 ~/.ange/usage.jsonl,统计即时计算(jsonl 是唯一事实源)。
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class UsageLog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, kind: str, target: str, verdict: str, session: str = "", **extra: Any) -> None:
        rec = {"ts": _now(), "kind": kind, "target": target, "verdict": verdict, "session": session, **extra}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out


class SignalCapture(BaseCallbackHandler):
    """层1:挂在 agent invoke 上,按工具调用记录成败。"""

    def __init__(self, usage: UsageLog, session: str) -> None:
        self.usage = usage
        self.session = session
        self._pending: dict[int, str] = {}  # run_id -> tool name

    def on_tool_start(self, serialized: dict | None, input_str: str, *, run_id, **kwargs) -> None:  # noqa: ANN001
        name = (serialized or {}).get("name") or kwargs.get("name") or "unknown"
        self._pending[run_id] = str(name)

    def on_tool_end(self, output: Any, *, run_id, **kwargs) -> None:  # noqa: ANN001
        name = self._pending.pop(run_id, None)
        if name:
            ok = not (isinstance(output, str) and output.startswith("[exit ") and not output.startswith("[exit 0]"))
            self.usage.append("proxy", name, "ok" if ok else "error", self.session)

    def on_tool_error(self, error: BaseException, *, run_id, **kwargs) -> None:  # noqa: ANN001
        name = self._pending.pop(run_id, None)
        if name:
            self.usage.append("proxy", name, "error", self.session, detail=str(error)[:200])


def compute_stats(usage: UsageLog) -> dict[str, dict]:
    """按 target 聚合:uses / errors / bad_reviews / good_reviews / last_used。"""
    stats: dict[str, dict] = defaultdict(lambda: {"uses": 0, "errors": 0, "good": 0, "bad": 0, "last_used": ""})
    for r in usage.records():
        t = stats[r["target"]]
        t["uses"] += 1
        t["last_used"] = max(t["last_used"], r.get("ts", ""))
        if r.get("verdict") == "error":
            t["errors"] += 1
        elif r.get("verdict") == "good":
            t["good"] += 1
        elif r.get("verdict") == "bad":
            t["bad"] += 1
    return dict(stats)
