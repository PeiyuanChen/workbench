"""datastore.md_store 测试：备忘列表/详情、时间线读取。"""

from pathlib import Path

from app.datastore import md_store

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
