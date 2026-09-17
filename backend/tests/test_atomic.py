"""datastore.atomic 测试：原子写、滚动备份、回读闸门恢复（SPEC-M2 决策 #3）。"""

import re
from pathlib import Path

import pytest

from app.datastore import atomic
from app.datastore.atomic import (
    AtomicWriteError,
    atomic_write_bytes,
    backup_file,
    safe_write,
)


def _ok_verify(path: Path) -> None:
    """回读成功：什么都不做。"""


def _bad_verify(path: Path) -> None:
    """回读失败：模拟解析器抛错。"""
    raise ValueError("模拟解析失败")


# ---------------------------------------------------------------- 原子写


def test_atomic_write_replaces_and_no_tmp_leftover(tmp_path: Path) -> None:
    target = tmp_path / "calendar.ics"
    target.write_bytes(b"old")
    atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"new"
    assert list(tmp_path.glob("*.tmp")) == [], "tmp 文件不得残留"


def test_atomic_write_first_write_creates_file(tmp_path: Path) -> None:
    target = tmp_path / "a.ics"
    atomic_write_bytes(target, b"data")
    assert target.read_bytes() == b"data"


def test_permission_error_wrapped_and_tmp_cleaned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows 文件被占用：PermissionError → 中文 AtomicWriteError，tmp 清理。"""
    target = tmp_path / "calendar.ics"

    def _deny(src, dst):
        raise PermissionError("模拟占用")

    monkeypatch.setattr(atomic.os, "replace", _deny)
    with pytest.raises(AtomicWriteError) as ei:
        atomic_write_bytes(target, b"x")
    assert "占用" in str(ei.value)
    assert list(tmp_path.glob("*.tmp")) == []


# ---------------------------------------------------------------- 备份


def test_backup_created_with_timestamp_name(tmp_path: Path) -> None:
    src = tmp_path / "calendar.ics"
    src.write_bytes(b"original content")
    dst = backup_file(src, tmp_path / ".backup")
    assert dst is not None and dst.exists()
    assert re.fullmatch(r"calendar-\d{8}T\d{6}-\d{6}Z\.ics", dst.name), dst.name
    assert dst.read_bytes() == b"original content"


def test_backup_skipped_when_src_missing(tmp_path: Path) -> None:
    """首写（目标不存在）：不备份、也不创建备份目录。"""
    assert backup_file(tmp_path / "nope.ics", tmp_path / ".backup") is None
    assert not (tmp_path / ".backup").exists()


def test_backup_rolling_keep_10(tmp_path: Path) -> None:
    src = tmp_path / "calendar.ics"
    bak_dir = tmp_path / ".backup"
    names: list[str] = []
    for i in range(12):
        src.write_bytes(f"v{i}".encode())
        dst = backup_file(src, bak_dir)
        assert dst is not None
        names.append(dst.name)
    left = {p.name for p in bak_dir.iterdir()}
    assert len(left) == 10, "滚动保留最近 10 份"
    assert names[0] not in left and names[1] not in left, "最旧 2 份应被删"
    assert names[-1] in left


def test_backup_same_name_collision_unique(tmp_path: Path) -> None:
    """同微秒连续备份：时间戳递增保证不互相覆盖。"""
    src = tmp_path / "calendar.ics"
    bak_dir = tmp_path / ".backup"
    src.write_bytes(b"a")
    first = backup_file(src, bak_dir)
    second = backup_file(src, bak_dir)
    assert first is not None and second is not None
    assert first.name != second.name
    assert len(list(bak_dir.iterdir())) == 2


# ---------------------------------------------------------------- 安全写闸门


def test_safe_write_success_verifies_and_backs_up(tmp_path: Path) -> None:
    target = tmp_path / "calendar.ics"
    target.write_bytes(b"old")
    seen: list[bytes] = []

    def verify(p: Path) -> None:
        seen.append(p.read_bytes())

    bak = safe_write(target, b"new", verify=verify, backup_dir=tmp_path / ".backup")
    assert target.read_bytes() == b"new"
    assert seen == [b"new"], "verify 必须拿到落盘后的新文件"
    assert bak is not None and bak.read_bytes() == b"old"


def test_safe_write_verify_failure_restores_backup(tmp_path: Path) -> None:
    target = tmp_path / "calendar.ics"
    original = b"BEGIN:VCALENDAR...original bytes"
    target.write_bytes(original)
    with pytest.raises(AtomicWriteError):
        safe_write(target, b"BROKEN", verify=_bad_verify, backup_dir=tmp_path / ".backup")
    assert target.read_bytes() == original, "回读失败必须字节级恢复旧文件"
    assert len(list((tmp_path / ".backup").iterdir())) == 1, "备份保留作现场"


def test_safe_write_verify_failure_first_write_removes_corrupt(tmp_path: Path) -> None:
    """首写损坏：无备份可恢复 → 删除坏文件，磁盘上不留坏数据。"""
    target = tmp_path / "calendar.ics"
    with pytest.raises(AtomicWriteError):
        safe_write(target, b"BROKEN", verify=_bad_verify, backup_dir=tmp_path / ".backup")
    assert not target.exists()
