"""datastore.md_store 测试：备忘列表/详情、时间线读取、M2 写路径。"""

import re
from pathlib import Path

import frontmatter
import pytest

from app.datastore import md_store
from app.datastore.atomic import AtomicWriteError

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = REPO_ROOT / "data-samples"


def _write_note(notes_dir: Path, name: str, note_id: str, body: str) -> None:
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / name).write_text(
        f"---\nid: {note_id}\ntags: [测试]\nrelated: []\n---\n\n{body}\n",
        encoding="utf-8",
    )


def test_list_notes_sorted_by_date_desc(tmp_path: Path) -> None:
    _write_note(tmp_path / "notes", "2026-09-01-旧笔记.md", "n-old", "# 旧笔记\n\n早先内容。")
    _write_note(tmp_path / "notes", "2026-09-03-新笔记.md", "n-new", "# 新笔记\n\n最新内容。")
    notes = md_store.list_notes(tmp_path)
    assert [n["id"] for n in notes] == ["n-new", "n-old"]
    assert notes[0]["date"] == "2026-09-03"


def test_title_and_excerpt(tmp_path: Path) -> None:
    _write_note(tmp_path / "notes", "2026-09-03-文件名标题.md", "n-1", "# 正文一级标题\n\n> 引言行跳过。\n第一段正文,作摘要。")
    note = md_store.list_notes(tmp_path)[0]
    assert note["title"] == "正文一级标题"  # 一级标题优先于文件名
    assert note["excerpt"] == "第一段正文,作摘要。"


def test_get_note_by_id_and_content(tmp_path: Path) -> None:
    _write_note(tmp_path / "notes", "2026-09-03-某篇.md", "n-1", "# 某篇\n\n正文内容。")
    note = md_store.get_note(tmp_path, "n-1")
    assert note is not None and "正文内容。" in note["content"]
    # 文件名（去扩展名）也可作 id 兜底
    assert md_store.get_note(tmp_path, "2026-09-03-某篇") is not None
    assert md_store.get_note(tmp_path, "不存在") is None


def test_empty_dir_returns_empty(tmp_path: Path) -> None:
    assert md_store.list_notes(tmp_path) == []
    assert md_store.get_note(tmp_path, "x") is None
    assert md_store.read_timeline(tmp_path, 2026, 9) is None


def test_read_timeline(tmp_path: Path) -> None:
    tl = tmp_path / "timeline" / "2026"
    tl.mkdir(parents=True)
    (tl / "03.md").write_text("---\nid: t-1\ntags: [时间线]\nrelated: []\n---\n\n# 三月主线", encoding="utf-8")
    got = md_store.read_timeline(tmp_path, 2026, 3)
    assert got is not None
    assert got["frontmatter"]["id"] == "t-1"
    assert "三月主线" in got["body"]
    assert md_store.read_timeline(tmp_path, 2026, 4) is None


# ---------------------------------------------------------------- 样例集成


def test_samples_note() -> None:
    notes = md_store.list_notes(SAMPLES)
    assert len(notes) == 1
    assert notes[0]["id"] == "20260903-note-workbench-arch"
    assert notes[0]["date"] == "2026-09-03"
    assert "数据主权" in notes[0]["tags"]


def test_samples_timeline() -> None:
    got = md_store.read_timeline(SAMPLES, 2026, 3)
    assert got is not None
    assert got["frontmatter"].get("id") == "timeline-2026-03"
    assert "川剧智能问答" in got["body"]


# ---------------------------------------------------------------- M2：写路径


def test_slugify_keeps_chinese_removes_illegal() -> None:
    """决策 D：保留中文，只去文件系统非法字符与控制字符。"""
    s = md_store.slugify_title('社保/报告:草稿*a?"x<y>z|w\\q')
    assert "社保" in s and "报告" in s
    assert not (set(s) & set('<>:"/\\|?*'))


def test_slugify_whitespace_and_edges() -> None:
    assert md_store.slugify_title("  失业 登记   保险  ") == "失业-登记-保险"
    assert md_store.slugify_title("") == "未命名"
    assert md_store.slugify_title("...") == "未命名"
    assert md_store.slugify_title("?:*<>") == "未命名"  # 全非法字符 → 空 → 回退
    assert md_store.slugify_title("?!*") == "!"  # '!' 是合法文件名字符，保留
    assert len(md_store.slugify_title("很长" * 100)) <= md_store.TITLE_MAX


def test_make_note_filename_and_conflict_suffix(tmp_path: Path) -> None:
    notes = tmp_path / "notes"
    notes.mkdir(parents=True)
    # 无冲突：原名直出
    assert md_store.make_note_filename(tmp_path, "2026-09-15", "开会") == "2026-09-15-开会.md"
    # 同名冲突：追加 -<4hex> 短后缀
    (notes / "2026-09-14-开会.md").write_text("x", encoding="utf-8")
    name = md_store.make_note_filename(tmp_path, "2026-09-14", "开会")
    assert re.fullmatch(r"2026-09-14-开会-[0-9a-f]{4}\.md", name), name


def test_find_note_path(tmp_path: Path) -> None:
    md_store.write_note(
        tmp_path, "2026-09-14-甲.md",
        {"id": "20260914-note-甲", "tags": [], "related": []}, "正文",
    )
    p = md_store.find_note_path(tmp_path, "20260914-note-甲")
    assert p is not None and p.name == "2026-09-14-甲.md"
    # 文件名（去扩展名）兜底匹配
    assert md_store.find_note_path(tmp_path, "2026-09-14-甲") is not None
    assert md_store.find_note_path(tmp_path, "不存在") is None


def test_write_note_roundtrip(tmp_path: Path) -> None:
    """写读往返：frontmatter 全字段一致，中文字面不被 \\uXXXX 转义。"""
    meta = {
        "id": "20260914-note-测试",
        "created": "2026-09-14",
        "tags": ["验收", "事务"],
        "related": ["uid:x@workbench.local"],
    }
    path = md_store.write_note(tmp_path, "2026-09-14-测试.md", meta, "# 测试\n\n中文正文。")
    raw = path.read_text(encoding="utf-8")
    assert "验收" in raw and "\\u" not in raw
    note = md_store.get_note(tmp_path, "20260914-note-测试")
    assert note is not None
    assert note["title"] == "测试"  # H1 优先
    assert note["tags"] == ["验收", "事务"]
    assert note["related"] == ["uid:x@workbench.local"]
    assert note["created"] == "2026-09-14"
    assert "中文正文。" in note["content"]


def test_write_note_frontmatter_key_order(tmp_path: Path) -> None:
    """契约键序即落盘序（dumps sort_keys=False）：id/created/tags/related。"""
    meta = {"id": "x-1", "created": "2026-09-14", "tags": [], "related": []}
    path = md_store.write_note(tmp_path, "2026-09-14-x.md", meta, "正文")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---"
    fm_lines = lines[1: lines.index("---", 1)]
    keys = [ln.split(":")[0] for ln in fm_lines]
    assert keys == ["id", "created", "tags", "related"]


def test_write_note_overwrite_backs_up_old_content(tmp_path: Path) -> None:
    md_store.write_note(tmp_path, "2026-09-14-a.md", {"id": "a", "tags": [], "related": []}, "v1")
    md_store.write_note(tmp_path, "2026-09-14-a.md", {"id": "a", "tags": [], "related": []}, "v2")
    assert md_store.get_note(tmp_path, "a") is not None
    assert "v2" in md_store.get_note(tmp_path, "a")["content"]
    backups = list((tmp_path / "notes" / ".backup").glob("*.md"))
    assert len(backups) == 1
    assert "v1" in backups[0].read_text(encoding="utf-8"), "备份应是旧内容"


def test_write_note_verify_failure_restores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """回读闸门：frontmatter 损坏 → 恢复旧文件（字节级不变）。"""
    md_store.write_note(tmp_path, "2026-09-14-a.md", {"id": "a", "tags": [], "related": []}, "原版")
    target = tmp_path / "notes" / "2026-09-14-a.md"
    original = target.read_bytes()
    monkeypatch.setattr(frontmatter, "dumps", lambda *a, **kw: "---\nbad: [unclosed\n---\n新版")
    with pytest.raises(AtomicWriteError):
        md_store.write_note(tmp_path, "2026-09-14-a.md", {"id": "a", "tags": [], "related": []}, "新版")
    assert target.read_bytes() == original


def test_write_note_verify_missing_keys_first_write_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回读闸门抓契约缺键（YAML 合法但缺 id/tags/related）；首写失败不留坏数据。"""
    monkeypatch.setattr(frontmatter, "dumps", lambda *a, **kw: "---\nfoo: 1\n---\n\nbody")
    with pytest.raises(AtomicWriteError):
        md_store.write_note(tmp_path, "2026-09-14-x.md", {"id": "x", "tags": [], "related": []}, "body")
    assert not (tmp_path / "notes" / "2026-09-14-x.md").exists()


def test_write_note_rename_removes_old(tmp_path: Path) -> None:
    """改标题重命名：旧文件备份后删除，id 不变、不出现新旧两份。"""
    md_store.write_note(
        tmp_path, "2026-09-14-旧题.md",
        {"id": "n1", "tags": [], "related": []}, "# 旧题\n\n正文",
    )
    old = tmp_path / "notes" / "2026-09-14-旧题.md"
    new = md_store.write_note(
        tmp_path, "2026-09-14-新题.md",
        {"id": "n1", "tags": [], "related": []}, "# 新题\n\n正文",
        old_path=old,
    )
    assert new.exists() and not old.exists()
    assert len(list((tmp_path / "notes" / ".backup").glob("*.md"))) == 1
    note = md_store.get_note(tmp_path, "n1")
    assert note is not None and note["title"] == "新题" and note["filename"] == "2026-09-14-新题.md"


def test_delete_note_backs_up_then_removes(tmp_path: Path) -> None:
    md_store.write_note(
        tmp_path, "2026-09-14-a.md",
        {"id": "a-del", "tags": [], "related": []}, "# a\n\n正文",
    )
    deleted = md_store.delete_note(tmp_path, "a-del")
    assert not deleted.exists()
    assert md_store.get_note(tmp_path, "a-del") is None
    backups = list((tmp_path / "notes" / ".backup").glob("*.md"))
    assert len(backups) == 1 and "正文" in backups[0].read_text(encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        md_store.delete_note(tmp_path, "a-del")


def test_note_backup_rolling_10(tmp_path: Path) -> None:
    for i in range(12):
        md_store.write_note(
            tmp_path, "2026-09-14-a.md",
            {"id": "a", "tags": [], "related": []}, f"v{i}",
        )
    backups = list((tmp_path / "notes" / ".backup").glob("*.md"))
    assert len(backups) == 10, "滚动保留最近 10 份"


def test_list_notes_ignores_backup_dir(tmp_path: Path) -> None:
    """.backup/ 子目录不进备忘列表（glob 非递归），也不得被当成笔记。"""
    md_store.write_note(tmp_path, "2026-09-14-a.md", {"id": "a", "tags": [], "related": []}, "a1")
    md_store.write_note(tmp_path, "2026-09-14-a.md", {"id": "a", "tags": [], "related": []}, "a2")
    assert (tmp_path / "notes" / ".backup").exists()
    notes = md_store.list_notes(tmp_path)
    assert len(notes) == 1 and notes[0]["id"] == "a"
