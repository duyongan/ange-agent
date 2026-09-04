"""CLI REPL:对话循环 + 斜杠命令 + 每轮异步复盘。"""

from __future__ import annotations

import logging
import sys
import uuid

from langchain_core.messages import AIMessage, HumanMessage
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from . import __version__
from .agent import build_agent
from .config import Settings, load_settings
from .evolution.dynamic import DynamicRegistry, make_dynamic_tools
from .evolution.retire import EvolvePass
from .evolution.review import ReviewPass
from .evolution.signals import SignalCapture, UsageLog, compute_stats
from .evolution.versioning import VersionStore
from .provider import build_chat_model
from .wiki.engine import WikiEngine

console = Console()
log = logging.getLogger("ange")

HELP = """\
/ help           本帮助
/ new            新会话(清空上下文,换 thread)
/ skills         列出 skill 库
/ stats          信号统计(使用/好坏/陈旧度)
/ wiki <词>      wiki 检索;/wiki lint 检查
/ ingest <路径>  摄入资料(md/txt/pdf/url)
/ evolve         大扫除:lint + skill 退役 + 工具回滚检查
/ versions <kind> <name>   查看备份版本(tool/skill)
/ exit           退出"""


def _cmd(argv: str) -> tuple[str, str]:
    parts = argv.strip().split(None, 1)
    return (parts[0] if parts else ""), (parts[1] if len(parts) > 1 else "")


def main() -> None:
    settings: Settings = load_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    for noisy in ("httpx", "httpx2", "openai", "openai._base_client"):
        logging.getLogger(noisy).setLevel(logging.WARNING)  # 每条 HTTP 请求的 INFO 噪音,关掉

    console.print(Panel(f"ange-agent v{__version__} · 模型 {settings.model} · 数据 {settings.home}", title="ange"))

    wiki = WikiEngine(settings.wiki_dir)
    usage = UsageLog(settings.usage_log)
    versions = VersionStore(settings.versions_dir)

    if not settings.api_key:
        console.print("[red]缺少 ANGE_API_KEY(复制 .env.example 为 .env 并填写)。工具命令仍可用,对话不可用。[/red]")

    session_id = uuid.uuid4().hex[:8]
    registry = DynamicRegistry(settings.session_dynamic_dir(session_id), settings.tools_dir, versions)
    agent = None
    review = None
    if settings.api_key:
        model = build_chat_model(settings)
        review_model = build_chat_model(settings, review=True)
        agent = build_agent(settings, model, review_model, wiki, make_dynamic_tools(registry))
        review = ReviewPass(settings, review_model, usage, wiki)
    evolve = EvolvePass(settings, usage, wiki, versions)

    thread_id = uuid.uuid4().hex
    ps = None
    if sys.stdin.isatty():  # 管道/重定向下 prompt_toolkit 在 Windows 不可用,回退 input()
        ps = PromptSession(history=FileHistory(str(settings.home / "history")))

    while True:
        try:
            line = (ps.prompt("ange> ") if ps else input("ange> ")).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue

        if line.startswith("/"):
            cmd, arg = _cmd(line[1:])
            if cmd in {"exit", "quit", "q"}:
                break
            if cmd == "help":
                console.print(HELP)
            elif cmd == "new":
                thread_id = uuid.uuid4().hex
                console.print("[green]新会话已开启[/green]")
            elif cmd == "skills":
                for d in sorted(settings.skills_dir.iterdir()):
                    if (d / "SKILL.md").exists():
                        console.print(f"• {d.name}")
            elif cmd == "stats":
                stats = compute_stats(usage)
                if not stats:
                    console.print("(暂无信号)")
                for name, s in sorted(stats.items()):
                    console.print(f"• {name}: 用 {s['uses']} | 好 {s['good']} | 坏 {s['bad']} | 错 {s['errors']} | 末次 {s['last_used'] or '-'}")
            elif cmd == "wiki":
                if arg == "lint":
                    for i in wiki.lint() or ["(干净)"]:
                        console.print(f"- {i}")
                else:
                    console.print(wiki.search(arg) if arg else wiki.index_for_prompt())
            elif cmd == "ingest":
                if not arg:
                    console.print("用法:/ingest <路径或URL>")
                else:
                    console.print(_safe_ingest(review_model, wiki, arg))
            elif cmd == "evolve":
                console.print(evolve.run())
            elif cmd == "versions":
                kind, name = _cmd(arg)
                snaps = versions.versions(kind, name) if kind and name else []
                console.print("\n".join(s.name for s in snaps) or "(无版本)")
            else:
                console.print(f"未知命令,试试 /help")
            continue

        if agent is None:
            console.print("[red]无 API key,无法对话。[/red]")
            continue

        capture = SignalCapture(usage, session_id)
        try:
            result = agent.invoke(
                {"messages": [HumanMessage(content=line)]},
                config={"configurable": {"thread_id": thread_id}, "callbacks": [capture]},
            )
        except KeyboardInterrupt:
            console.print("[yellow](已中断本轮)[/yellow]")
            continue
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]执行失败: {e}[/red]")
            log.exception("agent invoke 失败")
            continue

        msgs = result["messages"]
        used = [tc["name"] for m in msgs if isinstance(m, AIMessage) for tc in (m.tool_calls or [])]
        last = next((m for m in reversed(msgs) if isinstance(m, AIMessage) and m.content), None)
        if last:
            console.print(Panel(Markdown(last.content if isinstance(last.content, str) else str(last.content)), title="ange"))
        if used:
            console.print(f"[dim]工具: {', '.join(dict.fromkeys(used))}[/dim]")

        review.spawn_async(msgs, used, session_id)  # 每轮复盘:异步,不阻塞输入

    console.print("再见。")


def _safe_ingest(review_model, wiki: WikiEngine, source: str) -> str:
    from .wiki.ingest import ingest

    try:
        return ingest(wiki, review_model, source)
    except Exception as e:  # noqa: BLE001
        return f"摄入失败: {e}"


if __name__ == "__main__":
    main()
