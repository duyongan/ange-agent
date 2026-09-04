"""双版本备份与回滚:versions/<kind>/<name>/ 下最多保留 2 份,失败回滚上一版。"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

MAX_VERSIONS = 2  # 签收的设计决定:只留两版,损害窗口=检测延迟,降落伞只有一顶


class VersionStore:
    def __init__(self, versions_dir: Path) -> None:
        self.root = versions_dir

    def _dir(self, kind: str, name: str) -> Path:
        return self.root / kind / name

    def backup(self, kind: str, name: str, current: Path) -> Path | None:
        """把当前版存为快照;超额裁到 MAX_VERSIONS。返回快照路径。"""
        if not current.exists():
            return None
        d = self._dir(kind, name)
        d.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        snap = d / f"{stamp}{current.suffix}"
        shutil.copy2(current, snap)
        snaps = sorted(d.glob("*"))
        for old in snaps[:-MAX_VERSIONS]:
            old.unlink(missing_ok=True)
        return snap

    def versions(self, kind: str, name: str) -> list[Path]:
        d = self._dir(kind, name)
        return sorted(d.glob("*")) if d.exists() else []

    def rollback(self, kind: str, name: str, target: Path) -> Path | None:
        """恢复到最近一份与当前内容不同的快照(避免把坏版本本身恢复回去)。"""
        snaps = self.versions(kind, name)
        if not snaps:
            return None
        current = target.read_bytes() if target.exists() else b""
        chosen = next((s for s in reversed(snaps) if s.read_bytes() != current), None)
        if chosen is None:
            return None  # 所有快照都与当前一致,无可回滚
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(chosen, target)
        return chosen
