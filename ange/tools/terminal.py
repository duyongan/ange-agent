"""terminal 工具:跨平台 shell 执行(Windows 优先 Git Bash)。"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from langchain_core.tools import tool

TIMEOUT = 120  # 秒


def _shell() -> tuple[str, list[str]] | None:
    """有 bash 用 bash(Git Bash),否则交给 cmd。"""
    bash = shutil.which("bash")
    if bash:
        return bash, ["-c"]
    return None  # shell=True 走 cmd


@tool
def run_command(command: str) -> str:
    """执行 shell 命令并返回 stdout/stderr(合并,截断至 8000 字符)。超时 120 秒。"""
    shell = _shell()
    if shell:
        bash, prefix = shell
        proc = subprocess.run(  # noqa: S603 —— 个人工具,裸信任已签收
            [bash, *prefix, command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
        )
    else:
        proc = subprocess.run(  # noqa: S603
            command,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
        )
    out: str = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr.strip() else "")
    out = out.strip() or "(无输出)"
    return f"[exit {proc.returncode}]\n{out[:8000]}"
