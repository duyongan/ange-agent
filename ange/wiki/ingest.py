"""两步思维链摄入(Karpathy 方法论):先分析规划,再逐页生成。

step1:读原文 + 现有 index → 计划(新建哪些页 / 更新哪些页,JSON)
step2:按计划逐页生成带 [[wikilink]] 的 markdown
"""

from __future__ import annotations

import json
import logging
import re

from langchain_core.language_models.chat_models import BaseChatModel

from .engine import WikiEngine
from .loaders import load_source
from .page import Page

logger = logging.getLogger(__name__)

_ANALYZE_PROMPT = """你是个人知识库的维护者。根据新原文与现有 wiki 索引,规划摄入方案。

现有索引:
{index}

新原文(文件名: {name},可能截断):
{excerpt}

只输出 JSON,不要其他文字:
{{"summary": "原文一句话概括",
  "new_pages": [{{"title": "页名", "reason": "为何新建", "description": "一句话页面描述"}}],
  "update_pages": [{{"title": "现有页名", "change": "要补充什么"}}]}}

规则:新知识建新页;与现有页相关则更新现有页;一次摄入新建+更新合计不超过 5 页;页名用简洁中文名词。"""

_WRITE_PROMPT = """为 wiki 写一页知识。要求:

- 只输出 markdown 正文(不要 frontmatter,系统会加)
- 开头一段定义式描述,然后分节展开
- 提到相关概念时用 [[页名]] 交叉引用(仅当确有其页或本次会创建)
- 来源信息:本页内容整理自「{source_name}」
- 篇幅 300-800 字,宁可精确不要长

任务:{task}
相关现有页面(可引用):{related}"""

JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _ask(llm: BaseChatModel, prompt: str) -> str:
    from langchain_core.messages import HumanMessage

    return llm.invoke([HumanMessage(content=prompt)]).content


def _parse_json(text: str) -> dict:
    m = JSON_RE.search(text)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def ingest(engine: WikiEngine, llm: BaseChatModel, source: str, *, excerpt_chars: int = 6000) -> str:
    """摄入一个来源(md/txt/pdf/url)→ raw 存储 + 页面生成。返回人可读报告。"""
    name, text = load_source(source)
    engine.store_raw(name, text)
    engine.append_log("ingest", {"source": name, "chars": len(text)})

    plan = _parse_json(
        _ask(llm, _ANALYZE_PROMPT.format(index=engine.index_for_prompt() or "(空)", name=name, excerpt=text[:excerpt_chars]))
    )
    if not plan:
        return f"摄入失败:{name} 的分析步骤未返回有效 JSON(原文已存 raw/)"

    report: list[str] = [f"摄入 {name}:{plan.get('summary', '')}"]

    existing = {p.title: p for p in engine.pages()}
    for item in plan.get("update_pages", [])[:3]:
        title = str(item.get("title", "")).strip()
        page = existing.get(title)
        if not page:
            continue
        body = _ask(
            llm,
            _WRITE_PROMPT.format(
                task=f"更新 [[{title}]]:{item.get('change', '')}",
                source_name=name,
                related=", ".join(f"[[{t}]]" for t in existing if t != title)[:500] or "(无)",
            ),
        )
        page.body = page.body.rstrip() + "\n\n## 增补\n\n" + body.strip() + "\n"
        page.frontmatter["sources"] = sorted(set(page.frontmatter.get("sources", [])) | {name})
        engine.write(page, source=f"ingest:{name}")
        report.append(f"更新 [[{title}]]")

    for item in plan.get("new_pages", [])[:5]:
        title = str(item.get("title", "")).strip()
        if not title or title in existing:
            continue
        body = _ask(
            llm,
            _WRITE_PROMPT.format(
                task=f"新建 [[{title}]]:{item.get('reason', '')}",
                source_name=name,
                related=", ".join(f"[[{t}]]" for t in existing)[:500] or "(无)",
            ),
        )
        page = Page(title=title, body=body.strip() + "\n", frontmatter={"description": item.get("description", ""), "sources": [name]})
        engine.write(page, source=f"ingest:{name}")
        existing[title] = page
        report.append(f"新建 [[{title}]]")

    return "\n".join(report)
