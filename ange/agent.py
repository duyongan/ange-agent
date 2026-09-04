"""agent 装配:deepagents 循环 + skills(说明书轨)+ 工具(代码轨)+ wiki + 会话持久化。"""

from __future__ import annotations

import sqlite3
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import tool

from .config import Settings
from .tools import collect_tools
from .wiki.engine import WikiEngine
from .wiki.ingest import ingest as wiki_ingest_fn
from .wiki.page import Page

SYSTEM_PROMPT = """你是 ange —— 一个自进化的个人 CLI 助手。

## 工作方式
- 先想后做:复杂任务先列计划再执行
- 善用 skill 库:匹配任务时先 read_file 读 SKILL.md
- wiki 是你的长期知识:回答事实类问题前先 wiki_search

## 知识沉淀(每轮复盘官在后台工作,你也可以主动)
- 学到可复用做法 → 当场告诉用户"建议沉淀为 skill",复盘官会查重后创建
- 产生值得长期保留的事实/结论 → 用 wiki_write 主动记入知识库
- 需要摄入外部资料(md/txt/pdf/url)→ 用 wiki_ingest

## 动态工具
- 会话中缺一个趁手的工具 → define_tool_code 现写一个,call_tool 试跑
- 确认好用 → promote_tool 晋升为持久工具(下次启动自动可用)

## 当前 Wiki 索引(渐进式披露:只列目录,内容按需 wiki_read)
{wiki_index}"""


def make_wiki_tools(wiki: WikiEngine, llm: BaseChatModel) -> list[Any]:
    @tool
    def wiki_search(query: str) -> str:
        """在知识库中按关键词检索,返回页面标题与命中次数。"""
        return wiki.search(query)

    @tool
    def wiki_read(title: str) -> str:
        """读取知识库一页的完整内容。"""
        page = wiki.read(title)
        return page.render() if page else f"页面 [[{title}]] 不存在"

    @tool
    def wiki_write(title: str, body: str, description: str = "") -> str:
        """写入/更新知识库一页(markdown,可含 [[其他页名]] 交叉引用)。"""
        page = Page(title=title, body=body.strip() + "\n", frontmatter={"description": description, "sources": ["conversation"]})
        wiki.write(page, source="agent")
        return f"已写入 [[{title}]] 并重建索引"

    @tool
    def wiki_ingest(source: str) -> str:
        """摄入一个外部资料到知识库:本地 md/txt/pdf 路径或 URL。两步分析后自动建页/更新页。"""
        return wiki_ingest_fn(wiki, llm, source)

    return [wiki_search, wiki_read, wiki_write, wiki_ingest]


def build_agent(settings: Settings, model: BaseChatModel, review_model: BaseChatModel, wiki: WikiEngine, extra_tools: list[Any]):
    """组装 deepagents 图。checkpointer 让会话可 /resume(SQLite)。"""
    import deepagents

    all_tools = collect_tools(settings.tools_dir) + make_wiki_tools(wiki, review_model) + extra_tools
    conn = sqlite3.connect(settings.sessions_db, check_same_thread=False)
    checkpointer = __import__("langgraph.checkpoint.sqlite", fromlist=["SqliteSaver"]).SqliteSaver(conn)
    return deepagents.create_deep_agent(
        model=model,
        tools=all_tools,
        system_prompt=SYSTEM_PROMPT.format(wiki_index=wiki.index_for_prompt()),
        skills=[str(settings.skills_dir)],
        checkpointer=checkpointer,
    )
