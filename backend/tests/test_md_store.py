"""datastore.md_store 测试：参数化 Markdown 集合内核（备忘 memos / 未来笔记 notes 共用）。

覆盖：列表/详情、时间线读取、M2 写路径（备份/回读闸门/重命名/滚动）、
双集合同内核并存隔离（T1 验收：不存在两套复制实现）。
"""

import re
from pathlib import Path

import frontmatter
import pytest

from app.datastore import md_store
from app.datastore.atomic import AtomicWriteError
from app.datastore.md_store import MEMOS, MarkdownCollection

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = REPO_ROOT / "data-samples"

# 第二集合：模拟未来「笔记」模块（ADR 0001：notes 命名预留给笔记）
NOTES_LIKE = MarkdownCollection(dir_name="notes", id_prefix="note")


def _write_doc(coll_dir: Path, name: str, doc_id: str, body: str) -> None:
    coll_dir.mkdir(parents=True, exist_ok=True)
    (coll_dir / name).write_text(
        f"---\nid: {doc_id}\ntags: [测试]\nrelated: []\n---\n\n{body}\n",
        encoding="utf-8",
    )


def test_list_markdown_sorted_by_date_desc(tmp_path: Path) -> None:
    memos_dir = tmp_path / MEMOS.dir_name
    _write_doc(memos_dir, "2026-09-01-旧备忘.md", "m-old", "# 旧备忘\n\n早先内容。")
    _write_doc(memos_dir, "2026-09-03-新备忘.md", "m-new", "# 新备忘\n\n最新内容。")
    docs = md_store.list_markdown(tmp_path, MEMOS)
    assert [d["id"] for d in docs] == ["m-new", "m-old"]
    assert docs[0]["date"] == "2026-09-03"


def test_title_and_excerpt(tmp_path: Path) -> None:
    _write_doc(tmp_path / MEMOS.dir_name, "2026-09-03-文件名标题.md", "m-1",
               "# 正文一级标题\n\n> 引言行跳过。\n第一段正文,作摘要。")
    doc = md_store.list_markdown(tmp_path, MEMOS)[0]
    assert doc["title"] == "正文一级标题"  # 一级标题优先于文件名
    assert doc["excerpt"] == "第一段正文,作摘要。"


def test_excerpt_skips_image_and_table_lines(tmp_path: Path) -> None:
    body = (
        "# 图文备忘\n\n"
        "![](assets/20261030-101010-abcd1234.png)\n\n"
        "图片下面的正文，应当成为摘要。\n"
    )
    _write_doc(tmp_path / MEMOS.dir_name, "2026-10-30-图文.md", "m-img", body)

    table = (
        "# 表格备忘\n\n"
        "| 列1 | 列2 |\n"
        "| --- | --- |\n"
        "| 1 | 2 |\n"
    )
    _write_doc(tmp_path / MEMOS.dir_name, "2026-10-30-表格.md", "m-tbl", table)
    docs = {d["id"]: d for d in md_store.list_markdown(tmp_path, MEMOS)}
    # 分隔行被跳过，表头行竖线转空格成为摘要
    assert docs["m-img"]["excerpt"] == "图片下面的正文，应当成为摘要。"
    assert docs["m-tbl"]["excerpt"] == "列1 列2"


def test_excerpt_link_text_kept(tmp_path: Path) -> None:
    body = "# 链接备忘\n\n[点击这里](https://example.com/page) 后面的字"
    _write_doc(tmp_path / MEMOS.dir_name, "2026-10-30-链接.md", "m-link", body)
    doc = md_store.list_markdown(tmp_path, MEMOS)[0]
    assert doc["excerpt"] == "点击这里 后面的字"


def test_get_markdown_by_id_and_content(tmp_path: Path) -> None:
    _write_doc(tmp_path / MEMOS.dir_name, "2026-09-03-某篇.md", "m-1", "# 某篇\n\n正文内容。")
    doc = md_store.get_markdown(tmp_path, MEMOS, "m-1")
    assert doc is not None and "正文内容。" in doc["content"]
    # 文件名（去扩展名）也可作 id 兜底
    assert md_store.get_markdown(tmp_path, MEMOS, "2026-09-03-某篇") is not None
    assert md_store.get_markdown(tmp_path, MEMOS, "不存在") is None


def test_empty_dir_returns_empty(tmp_path: Path) -> None:
    assert md_store.list_markdown(tmp_path, MEMOS) == []
    assert md_store.get_markdown(tmp_path, MEMOS, "x") is None
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


def test_samples_memo() -> None:
    """data-samples 已随 T1 改名：memos/ 目录 + memo- id 前缀。"""
    docs = md_store.list_markdown(SAMPLES, MEMOS)
    assert len(docs) == 1
    assert docs[0]["id"] == "20260903-memo-workbench-arch"
    assert docs[0]["date"] == "2026-09-03"
    assert "数据主权" in docs[0]["tags"]


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
    assert md_store.slugify_title(" 失业 登记   保险  ") == "失业-登记-保险"
    assert md_store.slugify_title("") == "未命名"
    assert md_store.slugify_title("...") == "未命名"
    assert md_store.slugify_title("?:*<>") == "未命名"  # 全非法字符 → 空 → 回退
    assert md_store.slugify_title("?!*") == "!"  # '!' 是合法文件名字符，保留
    assert len(md_store.slugify_title("很长" * 100)) <= md_store.TITLE_MAX


def test_make_markdown_filename_and_conflict_suffix(tmp_path: Path) -> None:
    memos = tmp_path / "memos"
    memos.mkdir(parents=True)
    # 无冲突：原名直出
    assert md_store.make_markdown_filename(tmp_path, MEMOS, "2026-09-15", "开会") == "2026-09-15-开会.md"
    # 同名冲突：追加 -<4hex> 短后缀
    (memos / "2026-09-14-开会.md").write_text("x", encoding="utf-8")
    name = md_store.make_markdown_filename(tmp_path, MEMOS, "2026-09-14", "开会")
    assert re.fullmatch(r"2026-09-14-开会-[0-9a-f]{4}\.md", name), name


def test_find_markdown_path(tmp_path: Path) -> None:
    md_store.write_markdown(
        tmp_path, MEMOS, "2026-09-14-甲.md",
        {"id": "20260914-memo-甲", "tags": [], "related": []}, "正文",
    )
    p = md_store.find_markdown_path(tmp_path, MEMOS, "20260914-memo-甲")
    assert p is not None and p.name == "2026-09-14-甲.md"
    # 文件名（去扩展名）兜底匹配
    assert md_store.find_markdown_path(tmp_path, MEMOS, "2026-09-14-甲") is not None
    assert md_store.find_markdown_path(tmp_path, MEMOS, "不存在") is None


def test_write_markdown_roundtrip(tmp_path: Path) -> None:
    """写读往返：frontmatter 全字段一致，中文字面不被 \\uXXXX 转义。"""
    meta = {
        "id": "20260914-memo-测试",
        "created": "2026-09-14",
        "tags": ["验收", "事务"],
        "related": ["uid:x@workbench.local"],
    }
    path = md_store.write_markdown(tmp_path, MEMOS, "2026-09-14-测试.md", meta, "# 测试\n\n中文正文。")
    raw = path.read_text(encoding="utf-8")
    assert "验收" in raw and "\\u" not in raw
    doc = md_store.get_markdown(tmp_path, MEMOS, "20260914-memo-测试")
    assert doc is not None
    assert doc["title"] == "测试"  # H1 优先
    assert doc["tags"] == ["验收", "事务"]
    assert doc["related"] == ["uid:x@workbench.local"]
    assert doc["created"] == "2026-09-14"
    assert "中文正文。" in doc["content"]


def test_write_markdown_frontmatter_key_order(tmp_path: Path) -> None:
    """契约键序即落盘序（dumps sort_keys=False）：id/created/tags/related。"""
    meta = {"id": "x-1", "created": "2026-09-14", "tags": [], "related": []}
    path = md_store.write_markdown(tmp_path, MEMOS, "2026-09-14-x.md", meta, "正文")
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "---"
    fm_lines = lines[1: lines.index("---", 1)]
    keys = [ln.split(":")[0] for ln in fm_lines]
    assert keys == ["id", "created", "tags", "related"]


def test_write_markdown_overwrite_backs_up_old_content(tmp_path: Path) -> None:
    md_store.write_markdown(tmp_path, MEMOS, "2026-09-14-a.md",
                            {"id": "a", "tags": [], "related": []}, "v1")
    md_store.write_markdown(tmp_path, MEMOS, "2026-09-14-a.md",
                            {"id": "a", "tags": [], "related": []}, "v2")
    assert md_store.get_markdown(tmp_path, MEMOS, "a") is not None
    assert "v2" in md_store.get_markdown(tmp_path, MEMOS, "a")["content"]
    backups = list((tmp_path / "memos" / ".backup").glob("*.md"))
    assert len(backups) == 1
    assert "v1" in backups[0].read_text(encoding="utf-8"), "备份应是旧内容"


def test_write_markdown_verify_failure_restores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回读闸门：frontmatter 损坏 → 恢复旧文件（字节级不变）。"""
    md_store.write_markdown(tmp_path, MEMOS, "2026-09-14-a.md",
                            {"id": "a", "tags": [], "related": []}, "原版")
    target = tmp_path / "memos" / "2026-09-14-a.md"
    original = target.read_bytes()
    monkeypatch.setattr(frontmatter, "dumps", lambda *a, **kw: "---\nbad: [unclosed\n---\n新版")
    with pytest.raises(AtomicWriteError):
        md_store.write_markdown(tmp_path, MEMOS, "2026-09-14-a.md",
                                {"id": "a", "tags": [], "related": []}, "新版")
    assert target.read_bytes() == original


def test_write_markdown_verify_missing_keys_first_write_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回读闸门抓契约缺键（YAML 合法但缺 id/tags/related）；首写失败不留坏数据。"""
    monkeypatch.setattr(frontmatter, "dumps", lambda *a, **kw: "---\nfoo: 1\n---\n\nbody")
    with pytest.raises(AtomicWriteError):
        md_store.write_markdown(tmp_path, MEMOS, "2026-09-14-x.md",
                                {"id": "x", "tags": [], "related": []}, "body")
    assert not (tmp_path / "memos" / "2026-09-14-x.md").exists()


def test_write_markdown_rename_removes_old(tmp_path: Path) -> None:
    """改标题重命名：旧文件备份后删除，id 不变、不出现新旧两份。"""
    md_store.write_markdown(
        tmp_path, MEMOS, "2026-09-14-旧题.md",
        {"id": "m1", "tags": [], "related": []}, "# 旧题\n\n正文",
    )
    old = tmp_path / "memos" / "2026-09-14-旧题.md"
    new = md_store.write_markdown(
        tmp_path, MEMOS, "2026-09-14-新题.md",
        {"id": "m1", "tags": [], "related": []}, "# 新题\n\n正文",
        old_path=old,
    )
    assert new.exists() and not old.exists()
    assert len(list((tmp_path / "memos" / ".backup").glob("*.md"))) == 1
    doc = md_store.get_markdown(tmp_path, MEMOS, "m1")
    assert doc is not None and doc["title"] == "新题" and doc["filename"] == "2026-09-14-新题.md"


def test_delete_markdown_backs_up_then_removes(tmp_path: Path) -> None:
    md_store.write_markdown(
        tmp_path, MEMOS, "2026-09-14-a.md",
        {"id": "a-del", "tags": [], "related": []}, "# a\n\n正文",
    )
    deleted = md_store.delete_markdown(tmp_path, MEMOS, "a-del")
    assert not deleted.exists()
    assert md_store.get_markdown(tmp_path, MEMOS, "a-del") is None
    backups = list((tmp_path / "memos" / ".backup").glob("*.md"))
    assert len(backups) == 1 and "正文" in backups[0].read_text(encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        md_store.delete_markdown(tmp_path, MEMOS, "a-del")


def test_markdown_backup_rolling_10(tmp_path: Path) -> None:
    for i in range(12):
        md_store.write_markdown(
            tmp_path, MEMOS, "2026-09-14-a.md",
            {"id": "a", "tags": [], "related": []}, f"v{i}",
        )
    backups = list((tmp_path / "memos" / ".backup").glob("*.md"))
    assert len(backups) == 10, "滚动保留最近 10 份"


def test_list_markdown_ignores_backup_dir(tmp_path: Path) -> None:
    """.backup/ 子目录不进集合列表（glob 非递归），也不得被当成文档。"""
    md_store.write_markdown(tmp_path, MEMOS, "2026-09-14-a.md",
                            {"id": "a", "tags": [], "related": []}, "a1")
    md_store.write_markdown(tmp_path, MEMOS, "2026-09-14-a.md",
                            {"id": "a", "tags": [], "related": []}, "a2")
    assert (tmp_path / "memos" / ".backup").exists()
    docs = md_store.list_markdown(tmp_path, MEMOS)
    assert len(docs) == 1 and docs[0]["id"] == "a"


# ----------------------------------------------- T1：参数化内核——双集合并存隔离


def test_two_collections_share_one_kernel_isolated(tmp_path: Path) -> None:
    """同一内核、两份配置：memos/ 与 notes/ 物理隔离、id 前缀独立、互不可见。"""
    md_store.write_markdown(
        tmp_path, MEMOS, "2026-09-14-备忘甲.md",
        {"id": "20260914-memo-甲", "tags": [], "related": []}, "# 备忘甲\n\n备忘正文",
    )
    md_store.write_markdown(
        tmp_path, NOTES_LIKE, "2026-09-14-笔记甲.md",
        {"id": "20260914-note-甲", "tags": [], "related": []}, "# 笔记甲\n\n笔记正文",
    )
    # 物理目录分离
    assert (tmp_path / "memos" / "2026-09-14-备忘甲.md").exists()
    assert (tmp_path / "notes" / "2026-09-14-笔记甲.md").exists()
    # 列表互不可见
    assert [d["id"] for d in md_store.list_markdown(tmp_path, MEMOS)] == ["20260914-memo-甲"]
    assert [d["id"] for d in md_store.list_markdown(tmp_path, NOTES_LIKE)] == ["20260914-note-甲"]
    # 跨集合按 id 查找不到
    assert md_store.find_markdown_path(tmp_path, MEMOS, "20260914-note-甲") is None
    assert md_store.find_markdown_path(tmp_path, NOTES_LIKE, "20260914-memo-甲") is None
    # 备份目录各自独立
    md_store.delete_markdown(tmp_path, MEMOS, "20260914-memo-甲")
    assert (tmp_path / "memos" / ".backup").exists()
    assert not (tmp_path / "notes" / ".backup").exists()
    assert md_store.list_markdown(tmp_path, NOTES_LIKE)[0]["id"] == "20260914-note-甲"


def test_two_collections_asset_dirs_isolated(tmp_path: Path) -> None:
    """资产存储同样按集合配置落盘：memos/assets 与 notes/assets 分离。"""
    from app.datastore import asset_store

    png = base64_png()
    d1 = asset_store.save_asset(tmp_path, MEMOS, png, ".png")
    d2 = asset_store.save_asset(tmp_path, NOTES_LIKE, png, ".png")
    assert (tmp_path / "memos" / "assets" / d1["name"]).is_file()
    assert (tmp_path / "notes" / "assets" / d2["name"]).is_file()
    # 跨集合取图：notes 集合里找不到 memos 的图
    with pytest.raises(Exception):
        asset_store.resolve_asset(tmp_path, NOTES_LIKE, d1["name"])
    path, media = asset_store.resolve_asset(tmp_path, MEMOS, d1["name"])
    assert path.read_bytes() == png and media == "image/png"


def base64_png() -> bytes:
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
