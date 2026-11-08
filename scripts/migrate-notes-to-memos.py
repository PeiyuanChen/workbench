#!/usr/bin/env python3
"""T2 一次性迁移 CLI（issue #3 / ADR 0001）：备忘 notes 布局 → memos 布局。

这是整个 notes→memos 特性唯一的不可逆操作点，设计以"可审计、可回滚"为先：

  1. 预检：<user>/notes/ 必须存在、<user>/memos/ 不得存在（防重复执行/覆盖）；
  2. 备份：把整个 <user>/ 打成 zip 放到仓库外 .migration-backups/（默认）；
  3. 改名：notes/ 整体重命名为 memos/（.backup/ 冷快照、assets/ 随目录一起搬）；
  4. 重写：仅活跃 md（memos/*.md，非递归）frontmatter 的 id 前缀 note- → memo-，
     正文与其他 frontmatter 字段不动；.backup/ 冷快照 id 不重写（票 #3 明文要求）；
  5. 校验：文件数一致、活跃 md 的 frontmatter 全部可被 python-frontmatter 重新解析
     且 id/tags/related 齐全、旧目录消失、活跃 id 无任何 note- 形态残留；
     冷备份另做可解析性统计（只警告不阻断——冷快照保持原样、不参与应用读取）。
  任一步失败：删除半成品 memos/，从 zip 原样恢复 notes/，再以非零码退出；
  连回滚都失败时给出手工解压指引（zip 路径始终保留）。

脚本刻意保持独立：只依赖标准库 + python-frontmatter，不 import 应用代码，
便于脱离服务审计与单独执行。测试见 backend/tests/test_migrate_notes_to_memos.py。

用法（git-bash 仓库根）：
    backend/.venv/Scripts/python.exe scripts/migrate-notes-to-memos.py
    backend/.venv/Scripts/python.exe scripts/migrate-notes-to-memos.py \
        --user-dir data/users/me --backup-dir D:/backups
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import frontmatter

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_USER_DIR = REPO_ROOT / "data" / "users" / "me"
# 票 #3 与 ADR 0001 均要求备份在仓库外：默认仓库同级 .migration-backups/
DEFAULT_BACKUP_DIR = REPO_ROOT.parent / ".migration-backups"

BACKUP_DIRNAME = ".backup"
# 重写目标：契约形态活跃 id YYYYMMDD-note-<其余部分>
_NOTE_ID_RE = re.compile(r"^(\d{8}-)note-(.+)$")
# 残留检测：任意 note- 形态（含非契约 id，如 note-x），覆盖比 _NOTE_ID_RE 更宽
_ANY_NOTE_PREFIX_RE = re.compile(r"(^|-)note-")
# 外部引用审计：related/正文里出现的 note- 形态 id（预期真实数据为 0，见 ADR 0001）
_NOTE_REF_RE = re.compile(r"\d{8}-note-[^\s\]\)]+")


class MigrationError(Exception):
    """迁移预检失败或校验失败（失败场景已回滚或尚未产生写入）。"""


@dataclass
class RewriteOutcome:
    """活跃 md 重写结果（具名结构，避免匿名 tuple 语义漂移）。"""

    rewritten: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    external_note_refs: list[str] = field(default_factory=list)


@dataclass
class MigrationReport:
    """迁移证据：所有字段都由实际磁盘操作统计而来，供验收与审计。"""

    user_dir: Path
    backup_zip: Path
    files_before: int
    files_after: int
    active_total: int
    rewritten: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    residue_count: int = 0
    cold_backups_checked: int = 0
    cold_backup_warnings: list[str] = field(default_factory=list)
    external_note_refs: list[str] = field(default_factory=list)


def _count_files(path: Path) -> int:
    return sum(1 for p in path.rglob("*") if p.is_file())


def make_backup(user_dir: Path, backup_dir: Path, now: datetime | None = None) -> Path:
    """把整个 user_dir 打成 zip；arcname 带用户目录名（如 me/notes/...），
    回滚时解压到 user_dir.parent 即可原样还原。

    同名（秒级精度冲突）自动追加 -1/-2 后缀，绝不覆盖既有备份；
    写盘失败时清理半成品 zip 并抛 MigrationError（此时数据尚未改动）。
    """
    now = now or datetime.now()
    backup_dir.mkdir(parents=True, exist_ok=True)
    zip_path = backup_dir / f"{user_dir.name}-{now:%Y%m%dT%H%M%S}.zip"
    for i in range(1, 100):
        if not zip_path.exists():
            break
        zip_path = backup_dir / f"{user_dir.name}-{now:%Y%m%dT%H%M%S}-{i}.zip"
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(user_dir.rglob("*")):
                if p.is_file():
                    zf.write(p, p.relative_to(user_dir.parent))
    except Exception:
        zip_path.unlink(missing_ok=True)
        raise MigrationError(f"备份失败，数据未改动（已清理半成品 {zip_path}）")
    return zip_path


def _preflight(user_dir: Path) -> tuple[Path, Path]:
    if not user_dir.is_dir():
        raise MigrationError(f"用户数据目录不存在：{user_dir}")
    notes_dir = user_dir / "notes"
    memos_dir = user_dir / "memos"
    if not notes_dir.is_dir():
        raise MigrationError(f"找不到 notes/ 目录：{notes_dir}（可能已经迁移过）")
    if memos_dir.exists():
        raise MigrationError(f"memos/ 已存在：{memos_dir}，拒绝覆盖（请人工确认后再处理）")
    return notes_dir, memos_dir


def _rewrite_active_ids(memos_dir: Path) -> RewriteOutcome:
    """重写活跃 md 的 id 前缀；非递归 glob 天然跳过 .backup/ 与 assets/。"""
    outcome = RewriteOutcome()
    for path in sorted(memos_dir.glob("*.md")):
        post = frontmatter.load(path)
        old_id = str(post.get("id") or "")
        match = _NOTE_ID_RE.match(old_id)
        if match:
            post["id"] = f"{match.group(1)}memo-{match.group(2)}"
            path.write_text(frontmatter.dumps(post, sort_keys=False), encoding="utf-8")
            outcome.rewritten.append(post["id"])
        else:
            outcome.skipped.append(old_id or path.name)
        # 外部引用只审计不改动（id 行本身不在扫描范围内）
        haystacks = [str(v) for v in (post.get("related") or [])] + [post.content]
        for text in haystacks:
            for token in _NOTE_REF_RE.findall(text):
                outcome.external_note_refs.append(f"{path.name}: {token}")
    return outcome


def _check_cold_backups(memos_dir: Path) -> tuple[int, list[str]]:
    """冷备份可解析性统计：只警告不阻断（冷快照须保持原样，且不参与应用读取）。"""
    cold_dir = memos_dir / BACKUP_DIRNAME
    warnings: list[str] = []
    files = sorted(cold_dir.glob("*.md")) if cold_dir.is_dir() else []
    for path in files:
        try:
            frontmatter.load(path)
        except Exception as e:  # noqa: BLE001 统计用途：记录后继续
            warnings.append(f"{path.name} 无法解析（冷备份保持原样，不阻断迁移）：{e}")
    return len(files), warnings


def _verify_post_migration(
    user_dir: Path,
    notes_dir: Path,
    memos_dir: Path,
    files_before: int,
    report: MigrationReport,
) -> None:
    """内置校验闸门；任一不满足抛 RuntimeError，由上层回滚。"""
    problems: list[str] = []
    if notes_dir.exists():
        problems.append(f"旧目录仍存在：{notes_dir}")
    if not memos_dir.is_dir():
        problems.append(f"新目录缺失：{memos_dir}")
    files_after = _count_files(user_dir)
    report.files_after = files_after
    if files_after != files_before:
        problems.append(f"文件数不一致：迁移前 {files_before} → 迁移后 {files_after}")
    residue = 0
    active = list(memos_dir.glob("*.md")) if memos_dir.is_dir() else []
    for path in active:
        try:
            post = frontmatter.load(path)
        except Exception as e:  # noqa: BLE001 校验要把解析异常转成失败证据
            problems.append(f"frontmatter 无法重新解析：{path.name}（{e}）")
            continue
        missing = [k for k in ("id", "tags", "related") if k not in post.metadata]
        if missing:
            problems.append(f"{path.name} 缺契约键：{missing}")
        doc_id = str(post.get("id") or "")
        if _ANY_NOTE_PREFIX_RE.search(doc_id):
            residue += 1
            problems.append(f"{path.name} 仍带 note- 前缀：{doc_id}")
    report.residue_count = residue
    report.cold_backups_checked, report.cold_backup_warnings = _check_cold_backups(memos_dir)
    if problems:
        raise RuntimeError("；".join(problems))


def _extract_all(zf: zipfile.ZipFile, path: Path) -> None:
    """解压并尽量启用 PEP 706 路径过滤。

    标准做法是 3.12+ 传 filter='data'；但实测存在解释器自报 3.12、标准库
    zipfile 却被降级为无该参数的环境，故以调用探测为准，失败回退默认行为。
    回退风险可控：zip 为本脚本自生成，arcname 全部取自受控的相对路径。
    """
    try:
        zf.extractall(path, filter="data")
    except TypeError:
        zf.extractall(path)


def _rollback(backup_zip: Path, user_dir: Path, memos_dir: Path, notes_dir: Path) -> None:
    """从 zip 原样恢复用户目录；回滚自身失败时抛 MigrationError 附手工恢复指引。"""
    try:
        shutil.rmtree(memos_dir, ignore_errors=True)
        with zipfile.ZipFile(backup_zip) as zf:
            _extract_all(zf, user_dir.parent)
    except Exception as e:  # noqa: BLE001 回滚失败必须留下可操作指引
        raise MigrationError(
            f"迁移失败且自动回滚也失败：{e}；请手工解压备份 {backup_zip} 到 {user_dir.parent}"
        ) from e
    if not notes_dir.is_dir():
        raise MigrationError(
            f"回滚后 notes/ 仍缺失，请手工解压备份 {backup_zip} 到 {user_dir.parent}"
        )


def migrate_user_dir(user_dir: Path, backup_dir: Path) -> MigrationReport:
    """对单个用户数据目录执行迁移；失败自动从 zip 回滚后抛 MigrationError。"""
    notes_dir, memos_dir = _preflight(user_dir)
    files_before = _count_files(user_dir)
    backup_zip = make_backup(user_dir, backup_dir)

    try:
        notes_dir.rename(memos_dir)
        outcome = _rewrite_active_ids(memos_dir)
        report = MigrationReport(
            user_dir=user_dir,
            backup_zip=backup_zip,
            files_before=files_before,
            files_after=0,  # 由 _verify_post_migration 回填
            active_total=len(outcome.rewritten) + len(outcome.skipped),
            rewritten=outcome.rewritten,
            skipped=outcome.skipped,
            external_note_refs=outcome.external_note_refs,
        )
        _verify_post_migration(user_dir, notes_dir, memos_dir, files_before, report)
    except MigrationError:
        raise  # 备份阶段的 MigrationError 不触发回滚（数据未动）
    except Exception as e:
        _rollback(backup_zip, user_dir, memos_dir, notes_dir)
        raise MigrationError(f"迁移失败已回滚（备份：{backup_zip}）：{e}") from e
    return report


def _print_evidence(report: MigrationReport) -> None:
    print(f"[T2 迁移] 用户目录：{report.user_dir}")
    print("[1/5] 预检通过：notes/ 存在、memos/ 不存在")
    print(f"[2/5] 整目录 zip 备份（仓库外）：{report.backup_zip}（{report.files_before} 个文件）")
    print("[3/5] 目录改名 notes/ → memos/（.backup/ 冷快照、assets/ 随目录搬迁）")
    print(
        f"[4/5] 活跃 md id 重写 note- → memo-：{len(report.rewritten)} 篇，"
        f"跳过 {len(report.skipped)} 篇；冷备份 .backup/ {report.cold_backups_checked} 篇保持原样"
    )
    print("[5/5] 内置校验：")
    print(f"  - 文件数一致：迁移前 {report.files_before} = 迁移后 {report.files_after}")
    print(f"  - 活跃 frontmatter 全部可重新解析且 id/tags/related 齐全：{report.active_total} 篇")
    print(f"  - 旧目录 notes/ 已消失；活跃文件 note- 前缀残留：{report.residue_count}")
    print(
        f"  - 冷备份 .backup/ 可解析性统计：{report.cold_backups_checked} 篇，"
        f"警告 {len(report.cold_backup_warnings)} 条（id 不重写、保持原样）"
    )
    for w in report.cold_backup_warnings:
        print(f"    ! {w}")
    if report.external_note_refs:
        print(f"[外部引用审计] related/正文 note- 引用 {len(report.external_note_refs)} 处（未自动改写）：")
        for ref in report.external_note_refs:
            print(f"  - {ref}")
    else:
        print("[外部引用审计] related/正文 note- 引用：0 处")
    print("[迁移完成]")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="备忘 notes → memos 一次性迁移（#3）")
    parser.add_argument("--user-dir", type=Path, default=DEFAULT_USER_DIR, help="待迁移用户数据目录")
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR, help="zip 备份存放目录（默认仓库外）")
    args = parser.parse_args(argv)
    try:
        report = migrate_user_dir(args.user_dir, args.backup_dir)
    except MigrationError as e:
        print(f"[迁移失败] {e}", file=sys.stderr)
        return 1
    _print_evidence(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
