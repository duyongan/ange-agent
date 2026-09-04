"""退役与 /evolve 重维护:信号驱动地把用废的 skill/工具降格为 wiki 墓地页。"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..config import Settings
from ..wiki.engine import WikiEngine
from ..wiki.page import Page
from .signals import UsageLog, compute_stats

logger = logging.getLogger(__name__)

# 退役判据(签收:无 fitness function,用计数代理 + 时间规则,hermes curator 同款思路)
RETIRE_USES_MIN = 5          # 至少用过这么多次才有资格谈"用废"
BAD_RATIO = 0.5             # bad+error 占比超过一半 → 退役
STALE_DAYS = 30             # 超过 30 天未用 → 退役
ROLLBACK_CONSECUTIVE_BAD = 3  # 晋升工具连续 bad → 回滚上一版


def _days_since(ts: str) -> float:
    if not ts:
        return 999.0
    try:
        last = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return 999.0
    return (datetime.now(timezone.utc) - last).total_seconds() / 86400


class EvolvePass:
    def __init__(self, settings: Settings, usage: UsageLog, wiki: WikiEngine, versions) -> None:  # noqa: ANN001
        self.settings = settings
        self.usage = usage
        self.wiki = wiki
        self.versions = versions

    def run(self) -> str:
        """大扫除:lint 修复 → skill 退役 → 晋升工具回滚检查。返回报告。"""
        lines: list[str] = ["== /evolve 报告 =="]

        issues = self.wiki.fix_lint()
        remaining = self.wiki.lint()
        lines.append(f"lint:自动修复索引;剩余问题 {len(remaining)} 条(断链/孤儿需人工或对话处理)")
        for i in remaining[:5]:
            lines.append(f"  - {i}")

        stats = compute_stats(self.usage)
        lines += self._retire_skills(stats)
        lines += self._check_tool_rollback(stats)
        return "\n".join(lines)

    def _retire_skills(self, stats: dict) -> list[str]:
        """用废的 skill → wiki 墓地页 + 目录移到 retired/。"""
        out = []
        for d in sorted(self.settings.skills_dir.iterdir()):
            if not d.is_dir():
                continue
            s = stats.get(d.name)
            if not s or s["uses"] < RETIRE_USES_MIN:
                continue
            bad = s["bad"] + s["errors"]
            stale = _days_since(s["last_used"]) > STALE_DAYS
            if bad / s["uses"] >= BAD_RATIO or stale:
                note = "长期未用" if stale else f"差评率 {bad}/{s['uses']}"
                self._graveyard(d, note, s)
                out.append(f"skill 退役: {d.name}({note})→ wiki 墓地页")
        return out or ["skill 退役:无符合条件者"]

    def _graveyard(self, skill_dir: Path, reason: str, s: dict) -> None:
        """把 SKILL.md 蒸馏成 wiki 墓地页:"曾经这样做过"。"""
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8") if (skill_dir / "SKILL.md").exists() else ""
        self.versions.backup("skill", skill_dir.name, skill_dir / "SKILL.md")
        body = (
            f"> 退役 skill,记录存档。退役原因:{reason}。\n"
            f"> 生平:使用 {s['uses']} 次,好评 {s['good']},差评 {s['bad']},错误 {s['errors']},"
            f"最后使用 {s['last_used'] or '(未知)'}。\n\n"
            f"{text}\n"
        )
        page = Page(
            title=f"retired/{skill_dir.name}",
            body=body,
            frontmatter={"description": f"退役 skill 存档:{reason}", "sources": ["skill-retirement"]},
        )
        self.wiki.write(page, source="evolve")
        dest = self.settings.retired_dir / skill_dir.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(skill_dir), str(dest))

    def _check_tool_rollback(self, stats: dict) -> list[str]:
        """晋升工具连续 ROLLBACK_CONSECUTIVE_BAD 条 bad → 回滚上一版。"""
        out = []
        recs = [r for r in self.usage.records() if r["kind"] == "review" and r["verdict"] == "bad"]
        for py in sorted(self.settings.tools_dir.glob("*.py")):
            name = py.stem
            tail = [r for r in recs if r["target"] == name][-ROLLBACK_CONSECUTIVE_BAD:]
            if len(tail) == ROLLBACK_CONSECUTIVE_BAD:
                snap = self.versions.rollback("tool", name, py)
                if snap:
                    out.append(f"工具 {name} 连续 {ROLLBACK_CONSECUTIVE_BAD} 次差评 → 已回滚到 {snap.name}")
                else:
                    out.append(f"工具 {name} 连续差评,但无历史版本可回滚(建议删除观察)")
        return out or ["工具回滚检查:无需回滚"]
