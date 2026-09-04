"""每轮异步复盘:打分(层2信号)+ 提议新 skill(查重 + 高门槛)。

异步是生死线:后台 daemon 线程跑,REPL 不等它。
防崩阀:①提示词高门槛;②输入里带现有 skill 索引让其查重;③名字冲突硬校验。
"""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from ..config import Settings
from ..wiki.engine import WikiEngine
from .signals import UsageLog

logger = logging.getLogger(__name__)

_REVIEW_PROMPT = """你是 ange-agent 的复盘官。复盘刚结束的一轮对话,只输出 JSON。

本轮对话(可能截断):
{transcript}

本轮实际使用的工具/skill:
{used}

现有 skill 索引(name — description):
{skill_index}

只输出 JSON:
{{"scores": [{{"target": "工具或skill名", "verdict": "good|bad|neutral", "reason": "一句话"}}],
  "new_skill": null 或 {{{{"name": "kebab-case名", "description": "做什么用,何时用", "body": "SKILL.md 正文,步骤化指令"}}}},
  "knowledge": null 或 {{{{"title": "wiki页名", "body": "值得沉淀的知识,markdown"}}}}}}

创建 new_skill 的门槛(必须全部满足,否则给 null):
1. 本轮学到的做法确实可复用于未来任务(不是一次性操作)
2. 不与现有 skill 索引里的任何一条重叠
3. 正文是可执行的步骤化指令,不是感想

knowledge 门槛:本轮产生了值得长期保留的事实/结论/偏好,且不是常识。"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_KEBAB_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _skill_index(settings: Settings) -> str:
    lines = []
    for d in sorted(settings.skills_dir.iterdir()):
        sm = d / "SKILL.md"
        if d.is_dir() and sm.exists():
            text = sm.read_text(encoding="utf-8")
            m = re.search(r"description:\s*(.+)", text)
            lines.append(f"{d.name} — {m.group(1).strip()[:100] if m else '(无描述)'}")
    return "\n".join(lines) or "(空)"


def _transcript(messages: list[BaseMessage], limit: int = 6000) -> str:
    parts = []
    for m in messages[-20:]:
        role = m.__class__.__name__.replace("Message", "")
        content = m.content if isinstance(m.content, str) else str(m.content)
        parts.append(f"[{role}] {content[:600]}")
    text = "\n".join(parts)
    return text[-limit:]


class ReviewPass:
    def __init__(self, settings: Settings, llm: BaseChatModel, usage: UsageLog, wiki: WikiEngine) -> None:
        self.settings = settings
        self.llm = llm
        self.usage = usage
        self.wiki = wiki

    def spawn_async(self, messages: list[BaseMessage], used: list[str], session: str) -> None:
        """非阻塞入口:REPL 每轮结束后调这个。"""

        def _run() -> None:
            try:
                self.run(messages, used, session)
            except Exception:  # noqa: BLE001 —— 复盘失败不该影响主循环
                logger.warning("复盘失败", exc_info=True)

        threading.Thread(target=_run, daemon=True, name="ange-review").start()

    def run(self, messages: list[BaseMessage], used: list[str], session: str) -> dict:
        prompt = _REVIEW_PROMPT.format(
            transcript=_transcript(messages),
            used=", ".join(used) or "(无)",
            skill_index=_skill_index(self.settings),
        )
        raw = self.llm.invoke([HumanMessage(content=prompt)]).content
        result = self._parse(raw)
        if not result:
            self.usage.append("review", "review-pass", "neutral", session, detail="JSON 解析失败")
            return {}

        for s in result.get("scores", []):
            v = s.get("verdict", "neutral")
            if v in {"good", "bad"}:
                self.usage.append("review", str(s.get("target", "")), v, session, detail=str(s.get("reason", ""))[:200])

        skill = result.get("new_skill")
        if skill and self._valid_skill(skill):
            self._create_skill(skill, session)

        knowledge = result.get("knowledge")
        if knowledge and knowledge.get("title") and knowledge.get("body"):
            self._write_wiki(knowledge, session)

        return result

    def _parse(self, raw: str) -> dict:
        m = _JSON_RE.search(raw if isinstance(raw, str) else str(raw))
        if not m:
            return {}
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return {}

    def _valid_skill(self, skill: dict) -> bool:
        name = str(skill.get("name", ""))
        if not _KEBAB_RE.match(name) or len(name) > 64:
            return False
        if (self.settings.skills_dir / name / "SKILL.md").exists():  # 硬查重:名字冲突直接拒
            return False
        return bool(skill.get("description") and skill.get("body"))

    def _create_skill(self, skill: dict, session: str) -> None:
        d: Path = self.settings.skills_dir / skill["name"]
        d.mkdir(parents=True, exist_ok=True)
        fm = f"---\nname: {skill['name']}\ndescription: {skill['description']}\n---\n\n"
        (d / "SKILL.md").write_text(fm + skill["body"].strip() + "\n", encoding="utf-8")
        self.usage.append("review", f"skill:{skill['name']}", "created", session)
        logger.info("复盘创建新 skill: %s(下轮启动生效)", skill["name"])

    def _write_wiki(self, knowledge: dict, session: str) -> None:
        from ..wiki.page import Page

        page = Page(title=str(knowledge["title"]), body=str(knowledge["body"]).strip() + "\n", frontmatter={"sources": ["conversation"]})
        self.wiki.write(page, source="review")
        self.usage.append("review", f"wiki:{page.title}", "created", session)
