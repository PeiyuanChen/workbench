"""原子写 / 写前备份 / 写后回读闸门：格式无关的写入安全原语。

SPEC-M2 决策 #3（写入安全，数据主权的运行时底线）：
① 原子写：同目录临时文件（<名>.tmp）→ flush + os.fsync → os.replace() 原子替换；
② 写前备份：旧文件复制到 <数据目录>/.backup/<原名>-<UTC时间戳>.<扩展名>，
   滚动保留最近 keep（默认 10）份，超量删最旧；
③ 写后回读：verify 回调重新解析新文件，任何异常 = 文件损坏 →
   恢复备份（首写无备份则删除损坏新文件，不留坏数据）并抛 AtomicWriteError；
④ .backup/ 是数据目录内部实现，API 永不读取/展示它。

本模块不 import icalendar/frontmatter——回读校验逻辑由调用方以回调注入，
保持 datastore 底层原语格式无关（ics 与 md 共用）。
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 备份子目录名（数据目录内部实现，禁止 API 暴露）
BACKUP_DIRNAME = ".backup"
# 滚动保留份数（SPEC-M2 拍板：每用户最近 10 份）
DEFAULT_KEEP = 10

# 备份名内嵌时间戳：<stem>-<YYYYmmddTHHMMSS-ffffff>Z<suffix>
# 微秒精度防同秒冲突；字典序 = 时间序（滚动清理按此排序）
_STAMP_FMT = "%Y%m%dT%H%M%S-%fZ"
_STAMP_IN_NAME = re.compile(r"-(\d{8}T\d{6}-\d{6}Z)\.[A-Za-z0-9]+$")


class AtomicWriteError(RuntimeError):
    """原子写/回读校验失败（现场已恢复或删除，磁盘上不留损坏数据）。"""


def _backup_sort_key(p: Path) -> tuple[int, str, str]:
    """滚动清理排序键：按备份名内嵌时间戳（字典序=时间序）。

    不含标准时间戳的文件视为最旧（优先被清理），避免误删正常备份。
    """
    m = _STAMP_IN_NAME.search(p.name)
    if m is None:
        return (0, "", p.name)
    return (1, m.group(1), p.name)


def _prune_backups(backup_dir: Path, keep: int) -> None:
    """滚动清理：只保留最新 keep 份，删最旧（跨文件合并计数）。"""
    files = [p for p in backup_dir.iterdir() if p.is_file()]
    if len(files) <= keep:
        return
    files.sort(key=_backup_sort_key)
    for p in files[: len(files) - keep]:
        p.unlink(missing_ok=True)


def backup_file(src: Path, backup_dir: Path, keep: int = DEFAULT_KEEP) -> Path | None:
    """把 src 复制进 backup_dir（存在才备份），滚动保留最近 keep 份。

    返回备份文件路径；src 不存在（首写）返回 None，不创建备份目录。
    """
    src = Path(src)
    if not src.exists():
        return None
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    # 同微秒冲突时时间戳递增 1µs，保证备份名唯一且保持时序
    dt = datetime.now(timezone.utc)
    while True:
        stamp = dt.strftime(_STAMP_FMT)
        dst = backup_dir / f"{src.stem}-{stamp}{src.suffix}"
        if not dst.exists():
            break
        dt += timedelta(microseconds=1)
    shutil.copy2(src, dst)
    _prune_backups(backup_dir, keep)
    return dst


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """原子写字节：同目录 .tmp → write → flush → fsync → os.replace。

    tmp 必须与目标同目录（Windows os.replace 要求同卷）；
    任何失败都清理 tmp，目标文件保持原样。
    """
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except PermissionError as e:
        # Windows 常见：文件被编辑器/杀软/同步盘占用
        tmp.unlink(missing_ok=True)
        raise AtomicWriteError(f"文件被占用，无法写入：{path}") from e
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise AtomicWriteError(f"磁盘写入失败：{path}：{e}") from e


def safe_write(
    path: Path,
    data: bytes,
    verify: Callable[[Path], None],
    backup_dir: Path,
    keep: int = DEFAULT_KEEP,
) -> Path | None:
    """安全写闸门：备份 → 原子写 → 回读校验。

    verify(path) 由调用方注入（如 Calendar.from_ical / frontmatter 重读），
    抛任何异常都视为文件损坏：恢复备份并抛 AtomicWriteError；
    首写（无备份可恢复）则删除损坏新文件——磁盘上永远不留坏数据。
    返回本次生成的备份路径（首写为 None）。
    """
    path = Path(path)
    backup = backup_file(path, backup_dir, keep)
    atomic_write_bytes(path, data)
    try:
        verify(path)
    except Exception as e:  # noqa: BLE001 回读失败即损坏，任何异常都触发恢复
        if backup is not None:
            shutil.copy2(backup, path)  # 恢复旧文件（备份保留作现场）
        else:
            path.unlink(missing_ok=True)  # 首写损坏：删除，不留坏数据
        raise AtomicWriteError(f"写后回读校验失败，已回滚：{path}") from e
    return backup
