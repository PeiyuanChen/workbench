"""T2 一次性迁移 CLI 测试（#3）：notes 布局 → memos 布局。

接缝：独立 CLI 脚本 scripts/migrate-notes-to-memos.py（仅依赖 stdlib +
python-frontmatter），用 importlib 按文件路径加载，全程在 tmp_path 数据根运行，
不碰真实 data/users/me/。覆盖：成功路径、预检失败、校验失败自动回滚、
冷备份不重写、外部 note- 引用审计、CLI 入口与证据输出。
"""

import importlib.util
import sys
import zipfile
from pathlib import Path

import frontmatter
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "migrate-notes-to-memos.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("migrate_notes_to_memos", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # 注册到 sys.modules：Python 3.12 dataclasses 处理期会回查模块字典
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _md(doc_id: str, title: str, related: list[str] | None = None) -> str:
    rel = related or []
    lines = ["---", f"id: {doc_id}", "created: 2026-09-14", "tags: [测试]", "related:"]
    lines += [f"  - {r}" for r in rel]
    lines += ["---", "", f"# {title}", "", "正文内容，保持不变。"]
    return "\n".join(lines) + "\n"


def _build_user(root: Path) -> Path:
    """搭一个迷你 me/：2 篇活跃 note- md + 1 篇冷备份 + 1 个资产 + calendar.ics。"""
    user = root / "me"
    notes = user / "notes"
    backups = notes / ".backup"
    assets = notes / "assets"
    backups.mkdir(parents=True)
    assets.mkdir(parents=True)
    (notes / "2026-09-14-甲.md").write_text(
        _md("20260914-note-甲", "甲", ["uid:x@workbench.local"]), encoding="utf-8"
    )
    (notes / "2026-09-15-乙.md").write_text(_md("20260915-note-乙", "乙"), encoding="utf-8")
    (backups / "2026-09-01-冷备份-20260914T000000-abc123.md").write_text(
        _md("20260901-note-cold", "冷备份"), encoding="utf-8"
    )
    (assets / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n-binary-")
    (user / "calendar.ics").write_bytes(b"BEGIN:VCALENDAR\nEND:VCALENDAR\n")
    return user


def _all_files(user: Path) -> set[Path]:
    return {p.relative_to(user) for p in user.rglob("*") if p.is_file()}


def test_migrate_success_full_path(mod, tmp_path: Path) -> None:
    user = _build_user(tmp_path)
    backup_dir = tmp_path / "backups-outside"
    before = _all_files(user)
    before_active = {p: (user / p).read_bytes() for p in before if p.parent == Path("notes")}

    report = mod.migrate_user_dir(user, backup_dir)

    # --- 备份：仓库外 zip，含 me/ 全量文件 ---
    assert report.backup_zip.is_file()
    with zipfile.ZipFile(report.backup_zip) as zf:
        names = set(zf.namelist())
    assert "me/calendar.ics" in names
    assert "me/notes/2026-09-14-甲.md" in names
    assert "me/notes/.backup/2026-09-01-冷备份-20260914T000000-abc123.md" in names
    assert "me/notes/assets/pic.png" in names
    assert len(names) == len(before)

    # --- 目录改名 ---
    assert not (user / "notes").exists()
    assert (user / "memos").is_dir()

    # --- 活跃 md：id 改 memo-，frontmatter 可重解析，正文一字不动 ---
    post = frontmatter.load(user / "memos" / "2026-09-14-甲.md")
    assert post["id"] == "20260914-memo-甲"
    assert post["related"] == ["uid:x@workbench.local"]
    assert "正文内容，保持不变。" in post.content
    assert frontmatter.load(user / "memos" / "2026-09-15-乙.md")["id"] == "20260915-memo-乙"
    for rel, old_bytes in before_active.items():
        # frontmatter 重写会经 PyYAML 规范化 YAML 排版（列表缩进等），
        # 正确的不变量是语义：id 仅前缀变化、其余 metadata 与正文完全一致
        old_post = frontmatter.loads(old_bytes.decode("utf-8"))
        new_post = frontmatter.load(user / "memos" / rel.name)
        assert new_post["id"] == old_post["id"].replace("-note-", "-memo-", 1)
        assert new_post.content == old_post.content
        old_meta = {k: v for k, v in old_post.metadata.items() if k != "id"}
        new_meta = {k: v for k, v in new_post.metadata.items() if k != "id"}
        assert new_meta == old_meta

    # --- 冷备份：原样不动（仍 note-，字节与备份 zip 内一致）---
    cold = user / "memos" / ".backup" / "2026-09-01-冷备份-20260914T000000-abc123.md"
    assert frontmatter.load(cold)["id"] == "20260901-note-cold"
    with zipfile.ZipFile(report.backup_zip) as zf:
        assert cold.read_bytes() == zf.read("me/notes/.backup/" + cold.name)

    # --- 资产与 calendar.ics 字节不变 ---
    assert (user / "memos" / "assets" / "pic.png").read_bytes() == b"\x89PNG\r\n\x1a\n-binary-"
    assert (user / "calendar.ics").read_bytes() == b"BEGIN:VCALENDAR\nEND:VCALENDAR\n"

    # --- 文件总数一致 + 报告字段 ---
    after = _all_files(user)
    assert len(after) == len(before)
    assert report.active_total == 2 and len(report.rewritten) == 2
    assert report.skipped == []
    assert report.cold_backups_checked == 1 and report.cold_backup_warnings == []
    assert report.residue_count == 0


def test_preflight_no_notes_dir_raises(mod, tmp_path: Path) -> None:
    user = tmp_path / "me"
    user.mkdir()
    with pytest.raises(mod.MigrationError, match="notes"):
        mod.migrate_user_dir(user, tmp_path / "bak")
    assert not (tmp_path / "bak").exists(), "预检失败不得产生备份或任何写入"


def test_preflight_memos_already_exists_raises(mod, tmp_path: Path) -> None:
    user = _build_user(tmp_path)
    (user / "memos").mkdir()
    with pytest.raises(mod.MigrationError, match="memos"):
        mod.migrate_user_dir(user, tmp_path / "bak")
    assert (user / "notes").exists(), "预检失败不得动原目录"


def test_verify_failure_rolls_back_from_zip(mod, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    user = _build_user(tmp_path)
    original = (user / "notes" / "2026-09-14-甲.md").read_bytes()

    def boom(*_a, **_kw):
        raise RuntimeError("模拟校验失败")

    monkeypatch.setattr(mod, "_verify_post_migration", boom)
    with pytest.raises(mod.MigrationError, match="回滚"):
        mod.migrate_user_dir(user, tmp_path / "bak")

    # 已回滚：notes/ 原样恢复、memos/ 消失、原 id 仍是 note-
    assert not (user / "memos").exists()
    assert (user / "notes" / "2026-09-14-甲.md").read_bytes() == original
    assert frontmatter.load(user / "notes" / "2026-09-14-甲.md")["id"] == "20260914-note-甲"
    # 备份 zip 保留供人工排查
    assert list((tmp_path / "bak").glob("*.zip"))


def test_second_run_is_guarded(mod, tmp_path: Path) -> None:
    """迁移一次性：对已迁移目录再跑必须拒绝（memos 已在、notes 已无）。"""
    user = _build_user(tmp_path)
    mod.migrate_user_dir(user, tmp_path / "bak")
    with pytest.raises(mod.MigrationError):
        mod.migrate_user_dir(user, tmp_path / "bak2")
    assert not (tmp_path / "bak2").exists()


def test_external_note_ref_recorded_as_warning(mod, tmp_path: Path) -> None:
    """related/正文里对 note- id 的外部引用不自动改写，只进审计警告（真实数据预期为 0）。"""
    user = _build_user(tmp_path)
    (user / "notes" / "2026-09-16-引用.md").write_text(
        _md("20260916-note-ref", "引用", ["20260901-note-cold"]), encoding="utf-8"
    )
    report = mod.migrate_user_dir(user, tmp_path / "bak")
    assert report.active_total == 3
    assert any("20260901-note-cold" in ref for ref in report.external_note_refs)
    # 自身 id 仍正常重写
    assert frontmatter.load(user / "memos" / "2026-09-16-引用.md")["id"] == "20260916-memo-ref"


def test_non_note_prefixed_id_skipped(mod, tmp_path: Path) -> None:
    user = _build_user(tmp_path)
    (user / "notes" / "2026-09-17-已是memo.md").write_text(
        _md("20260917-memo-already", "已是memo"), encoding="utf-8"
    )
    report = mod.migrate_user_dir(user, tmp_path / "bak")
    assert "20260917-memo-already" in report.skipped
    assert frontmatter.load(user / "memos" / "2026-09-17-已是memo.md")["id"] == "20260917-memo-already"


def test_backup_failure_leaves_data_untouched(mod, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    user = _build_user(tmp_path)
    original = (user / "notes" / "2026-09-14-甲.md").read_bytes()

    def boom_zip(*_a, **_kw):
        raise OSError("模拟磁盘不可写")

    monkeypatch.setattr(mod.zipfile, "ZipFile", boom_zip)
    with pytest.raises(mod.MigrationError, match="备份失败"):
        mod.migrate_user_dir(user, tmp_path / "bak")

    # 数据零改动：notes/ 原样、无 memos/、无半截备份
    assert (user / "notes" / "2026-09-14-甲.md").read_bytes() == original
    assert not (user / "memos").exists()
    assert not (tmp_path / "bak").exists() or not list((tmp_path / "bak").iterdir())


def test_rewrite_failure_midway_rolls_back(mod, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    user = _build_user(tmp_path)
    original = {p.relative_to(user): p.read_bytes() for p in (user / "notes").rglob("*") if p.is_file()}
    # 第二次写活跃 md 时抛错（重写中途失败）
    calls = {"n": 0}
    real_write_text = mod.Path.write_text

    def flaky_write_text(self, *_a, **_kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("模拟写盘失败")
        return real_write_text(self, *_a, **_kw)

    monkeypatch.setattr(mod.Path, "write_text", flaky_write_text)
    with pytest.raises(mod.MigrationError, match="回滚"):
        mod.migrate_user_dir(user, tmp_path / "bak")

    # 自动回滚：notes/ 字节级还原、memos/ 消失、zip 保留供排查
    assert not (user / "memos").exists()
    for rel, data in original.items():
        assert (user / rel).read_bytes() == data
    assert list((tmp_path / "bak").glob("*.zip"))


def test_cli_main_rollback_exit_1(mod, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                  capsys: pytest.CaptureFixture[str]) -> None:
    """CLI 出口的回滚路径：校验失败 → main 返回 1、stderr 中文提示、数据已还原。"""
    user = _build_user(tmp_path)
    monkeypatch.setattr(mod, "_verify_post_migration", lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("boom")))
    rc = mod.main(["--user-dir", str(user), "--backup-dir", str(tmp_path / "bak")])
    captured = capsys.readouterr()
    assert rc == 1 and "迁移失败" in captured.err
    assert (user / "notes").is_dir() and not (user / "memos").exists()


def test_any_note_prefixed_id_is_residue_and_rolls_back(mod, tmp_path: Path) -> None:
    """非契约形态的 note- id（如 note-x）不被静默跳过：残留校验抓住 → 回滚。"""
    user = _build_user(tmp_path)
    (user / "notes" / "2026-09-18-异形.md").write_text(_md("note-weird", "异形"), encoding="utf-8")
    with pytest.raises(mod.MigrationError, match="回滚"):
        mod.migrate_user_dir(user, tmp_path / "bak")
    assert not (user / "memos").exists()
    assert (user / "notes" / "2026-09-18-异形.md").exists()


def test_cold_backup_parse_checked_but_never_blocks(mod, tmp_path: Path) -> None:
    """冷备份纳入可解析性统计；损坏冷备份只警告不阻断（保持原样、不参与应用读取）。"""
    user = _build_user(tmp_path)
    (user / "notes" / ".backup" / "broken.md").write_text("---\nid: [unclosed\n---\n坏", encoding="utf-8")
    report = mod.migrate_user_dir(user, tmp_path / "bak")
    assert report.cold_backups_checked == 2
    assert any("broken.md" in w for w in report.cold_backup_warnings)
    # 损坏冷备份原样保留在 memos/.backup/
    assert (user / "memos" / ".backup" / "broken.md").is_file()


def test_backup_zip_name_collision_gets_suffix(mod, tmp_path: Path) -> None:
    user = _build_user(tmp_path)
    r1 = mod.make_backup(user, tmp_path / "bak", mod.datetime(2026, 11, 8, 10, 0, 0))
    r2 = mod.make_backup(user, tmp_path / "bak", mod.datetime(2026, 11, 8, 10, 0, 0))
    assert r1 != r2 and r1.is_file() and r2.is_file()


def test_cli_main_success_and_failure(mod, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    user = _build_user(tmp_path)
    bak = tmp_path / "bak"
    rc = mod.main(["--user-dir", str(user), "--backup-dir", str(bak)])
    out = capsys.readouterr().out
    assert rc == 0
    for keyword in ("zip", "文件数", "frontmatter", "notes", "note-"):
        assert keyword in out
    assert (user / "memos").is_dir()

    # 失败路径：指向没有 notes/ 的目录，退出码 1，错误信息中文
    empty = tmp_path / "ghost"
    empty.mkdir()
    rc_fail = mod.main(["--user-dir", str(empty), "--backup-dir", str(bak)])
    captured = capsys.readouterr()
    assert rc_fail == 1
    assert "迁移失败" in captured.err or "迁移失败" in captured.out
