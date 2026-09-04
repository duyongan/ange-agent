"""工具注册表:基础工具 + ~/.ange/tools/ 下晋升工具的启动加载(双轨制的代码轨)。

晋升工具文件约定:每个 .py 定义模块级
    NAME: str          # 工具名(snake_case)
    DESCRIPTION: str   # 给模型看的说明
    ARGS: dict         # JSON Schema parameters,如 {"type":"object","properties":{...},"required":[...]}
    def run(**kwargs)  # 执行体
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

from langchain_core.tools import StructuredTool

from .search import search_files
from .terminal import run_command

logger = logging.getLogger(__name__)


def collect_tools(tools_dir: Path) -> list[StructuredTool]:
    """基础工具 + 扫描晋升目录。坏文件跳过不致命。"""
    tools: list[StructuredTool] = [run_command, search_files]
    tools.extend(_load_promoted(tools_dir))
    return tools


def _load_promoted(tools_dir: Path) -> list[StructuredTool]:
    """importlib 加载 ~/.ange/tools/*.py 为一等工具。"""
    out: list[StructuredTool] = []
    for py in sorted(tools_dir.glob("*.py")):
        if py.name.startswith("_"):
            continue
        try:
            mod = _import_file(py)
            out.append(
                StructuredTool.from_function(
                    func=mod.run,
                    name=mod.NAME,
                    description=mod.DESCRIPTION,
                    args_schema=_schema(mod),
                )
            )
        except Exception:  # noqa: BLE001 —— 坏工具不应炸掉启动
            logger.warning("晋升工具加载失败,跳过: %s", py, exc_info=True)
    return out


def _import_file(py: Path):
    spec = importlib.util.spec_from_file_location(f"ange_promoted_{py.stem}", py)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 {py}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    for attr in ("NAME", "DESCRIPTION", "ARGS", "run"):
        if not hasattr(mod, attr):
            raise ImportError(f"{py} 缺少 {attr}")
    return mod


def _schema(mod) -> dict:
    """ARGS 必须是完整的 JSON Schema object;兜底无参调用。"""
    args = getattr(mod, "ARGS", None)
    if isinstance(args, dict) and args.get("type") == "object":
        return args
    return {"type": "object", "properties": {}, "required": []}
