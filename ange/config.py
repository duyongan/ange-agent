"""配置与数据目录布局。

~/.ange/
├── skills/          # SKILL.md 说明书轨(deepagents SkillsMiddleware 直接扫描)
├── tools/           # 晋升后的动态工具(代码轨,启动时 importlib 注册)
├── dynamic/<sid>/   # 本会话易失动态工具(会话结束即弃)
├── wiki/            # 知识引擎:index.md / log.md / *.md / raw/(不可变原文)
├── retired/         # 退役 skill 的存放处(正文已蒸馏进 wiki 墓地页)
├── versions/        # 双版本备份(max 2),回滚源
├── sessions.db      # LangGraph SQLite checkpointer
└── usage.jsonl      # 结局信号日志(代理信号 + 复盘自评)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # Python 3.11+ 标准 tomllib;.env 手动解析,不引第三方
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


def _load_env_file(path: Path) -> None:
    """极简 .env 解析:KEY=VALUE,忽略注释与空行。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


@dataclass
class Settings:
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    review_model: str = ""  # 复盘/进化用模型,空 = 主模型
    home: Path = field(default_factory=lambda: Path.home() / ".ange")

    @property
    def effective_review_model(self) -> str:
        return self.review_model or self.model

    # ---- 数据目录(懒建) ----
    @property
    def skills_dir(self) -> Path:
        return self._ensure(self.home / "skills")

    @property
    def tools_dir(self) -> Path:
        return self._ensure(self.home / "tools")

    @property
    def dynamic_dir(self) -> Path:
        return self._ensure(self.home / "dynamic")

    @property
    def wiki_dir(self) -> Path:
        return self._ensure(self.home / "wiki")

    @property
    def retired_dir(self) -> Path:
        return self._ensure(self.home / "retired")

    @property
    def versions_dir(self) -> Path:
        return self._ensure(self.home / "versions")

    @property
    def usage_log(self) -> Path:
        return self.home / "usage.jsonl"

    @property
    def sessions_db(self) -> Path:
        return self.home / "sessions.db"

    def _ensure(self, p: Path) -> Path:
        p.mkdir(parents=True, exist_ok=True)
        return p

    def session_dynamic_dir(self, session_id: str) -> Path:
        return self._ensure(self.dynamic_dir / session_id)


def load_settings() -> Settings:
    """环境变量 > .env(项目目录)> 默认值。"""
    project_env = Path(__file__).resolve().parent.parent / ".env"
    _load_env_file(project_env)
    home = Path(os.environ.get("ANGE_HOME", "")).expanduser() if os.environ.get("ANGE_HOME") else Path.home() / ".ange"
    s = Settings(
        api_key=os.environ.get("ANGE_API_KEY", ""),
        base_url=os.environ.get("ANGE_BASE_URL", DEFAULT_BASE_URL),
        model=os.environ.get("ANGE_MODEL", DEFAULT_MODEL),
        review_model=os.environ.get("ANGE_REVIEW_MODEL", ""),
        home=home,
    )
    s.home.mkdir(parents=True, exist_ok=True)
    return s
