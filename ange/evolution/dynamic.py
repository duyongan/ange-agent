"""动态工具(dsh 语义的简化版):会话内定义、易失、可晋升。

agent 面向三个工具:
- define_tool_code  写 Python 实现 + schema 到 ~/.ange/dynamic/<sid>/(语法校验,不执行)
- call_tool         分发器:按名加载并执行动态工具(固定 schema,无需重建图)
- promote_tool      晋升:移动到 ~/.ange/tools/(备份现有版,双版本上限),下次启动一等注册
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

NAME_RE = r"^[a-z0-9_]+$"


class DynamicSpec(BaseModel):
    name: str = Field(pattern=NAME_RE, max_length=48)
    description: str = Field(max_length=500)
    args: dict = Field(default_factory=dict)  # JSON Schema parameters


class DynamicRegistry:
    def __init__(self, session_dir: Path, tools_dir: Path, versions) -> None:  # noqa: ANN001
        self.session_dir = session_dir
        self.tools_dir = tools_dir
        self.versions = versions

    def _code_path(self, name: str) -> Path:
        return self.session_dir / f"{name}.py"

    def _spec_path(self, name: str) -> Path:
        return self.session_dir / f"{name}.json"

    def define(self, name: str, description: str, code: str, args: dict) -> str:
        code_path = self._code_path(name)
        code_path.write_text(code, encoding="utf-8")
        self._spec_path(name).write_text(
            json.dumps({"name": name, "description": description, "args": args}, ensure_ascii=False), encoding="utf-8"
        )
        return f"动态工具 {name} 已定义。用 call_tool 执行;确认好用后用 promote_tool 晋升。"

    def call(self, name: str, arguments: str) -> str:
        code = self._code_path(name)
        if not code.exists():
            return f"动态工具 {name} 不存在(会话易失,重启即弃;promote_tool 可持久)"
        mod = _import_module(code, f"ange_dyn_{name}")
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError as e:
            return f"arguments 不是合法 JSON: {e}"
        if not hasattr(mod, "run"):
            return f"{name}.py 缺少 run(**kwargs) 函数"
        return str(mod.run(**args))[:8000]

    def list(self) -> list[dict]:
        out = []
        for spec_file in sorted(self.session_dir.glob("*.json")):
            try:
                out.append(json.loads(spec_file.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
        return out

    def promote(self, name: str, reason: str = "") -> str:
        """双轨制晋升:动态 → ~/.ange/tools/。有现版则先备份(双版本上限)。"""
        code, spec_file = self._code_path(name), self._spec_path(name)
        if not code.exists():
            return f"动态工具 {name} 不存在"
        dest = self.tools_dir / f"{name}.py"
        if dest.exists():
            self.versions.backup("tool", name, dest)
        shutil.copy2(code, dest)
        spec_file.unlink(missing_ok=True)
        code.unlink(missing_ok=True)
        return f"工具 {name} 已晋升为持久工具(reason: {reason or '未说明'}),下次启动自动注册。"


def _import_module(path: Path, modname: str):
    spec = importlib.util.spec_from_file_location(modname, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


def make_dynamic_tools(registry: DynamicRegistry) -> list[Any]:
    @tool
    def define_tool_code(name: str, description: str, code: str, args_schema: str = '{"type":"object","properties":{},"required":[]}') -> str:
        """定义会话内动态工具(易失,重启即弃)。

        code 必须是完整 Python 模块:模块级 NAME/DESCRIPTION/ARGS 常量 + run(**kwargs) -> str。
        args_schema 是 JSON Schema 的 JSON 字符串。语法校验通过即注册,不预执行。
        """
        import re as _re

        if not _re.match(NAME_RE, name or ""):
            return f"名字非法(需匹配 {NAME_RE})"
        try:
            args = json.loads(args_schema)
            if not isinstance(args, dict):
                raise ValueError("args_schema 必须是 JSON object")
        except (json.JSONDecodeError, ValueError) as e:
            return f"args_schema 非法: {e}"
        try:
            compile(code, f"<{name}>", "exec")
        except SyntaxError as e:
            return f"code 语法错误: {e}"
        DynamicSpec(name=name, description=description, args=args)  # 校验
        return registry.define(name, description, code, args)

    @tool
    def call_tool(name: str, arguments: str = "{}") -> str:
        """执行会话内动态工具。arguments 为 JSON 对象字符串,如 '{"q": "test"}'。"""
        return registry.call(name, arguments)

    @tool
    def promote_tool(name: str, reason: str = "") -> str:
        """把好用的动态工具晋升为持久工具(下次启动一等注册;自动备份旧版,双版本上限)。"""
        return registry.promote(name, reason)

    return [define_tool_code, call_tool, promote_tool]
