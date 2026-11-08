"""笔记（notes）文件夹感知内核测试（datastore 接缝）。

覆盖 ADR-0002：文件夹即 notes/ 下真实子目录，无 sidecar；
保留名 .backup/assets 拒绝、路径穿越拒绝、非空文件夹拒绝删除。
HTTP 外部行为见 test_write_notes.py，本文件只测内核纯逻辑与文件系统效果。
"""

import re
from pathlib import Path

import frontmatter
import pytest

from app.core.errors import NotFound, ValidationFailed
from app.datastore import md_store
from app.datastore.md_store import NOTES


def _notes_dir(tmp_path: Path) -> Path:
    return tmp_path / NOTES.dir_name


def base64_png() -> bytes:
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
        "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )


# ------------------------------------------------- 文件夹路径归一化与校验


def test_normalize_folder_root_variants() -> None:
    assert md_store.normalize_folder_path("") == ""
    assert md_store.normalize_folder_path("/") == ""
    assert md_store.normalize_folder_path("  ") == ""


def test_normalize_folder_strips_outer_slashes_keeps_chinese() -> None:
    assert md_store.normalize_folder_path("/Kubernetes/网络/") == "Kubernetes/网络"
    assert md_store.normalize_folder_path("///") == ""


def test_normalize_folder_rejects_surrounding_whitespace() -> None:
    with pytest.raises(ValidationFailed, match="首尾不能有空白"):
        md_store.normalize_folder_path(" k8s")
    with pytest.raises(ValidationFailed, match="首尾不能有空白"):
        md_store.normalize_folder_path("k8s ")


@pytest.mark.parametrize("bad", [
    ".backup",
    "assets",
    "k8s/.backup",
    "k8s/assets",
    "..",
    "../k8s",
    "k8s/../secret",
    "k8s/./x",
    "k8s//x",
    "a:b",
    "a?b",
    "a|b",
    "a<b",
    "a>b",
    'a"b',
    "a*b",
    "trailing.",
    "trailing ",
    "k8s/ 网络",
])
def test_normalize_folder_rejects_illegal(bad: str) -> None:
    with pytest.raises(ValidationFailed):
        md_store.normalize_folder_path(bad)


def test_normalize_folder_rejects_blank_segment_and_too_long() -> None:
    with pytest.raises(ValidationFailed):
        md_store.normalize_folder_path("k8s/   ")
    with pytest.raises(ValidationFailed):
        md_store.normalize_folder_path("长" * 201)


# ------------------------------------------------- 文件夹 CRUD


def test_create_folder_is_real_directory(tmp_path: Path) -> None:
    got = md_store.create_folder(tmp_path, NOTES, "Kubernetes/网络")
    assert got == {"path": "Kubernetes/网络", "name": "网络"}
    assert (_notes_dir(tmp_path) / "Kubernetes" / "网络").is_dir()


def test_create_folder_twice_conflicts_422(tmp_path: Path) -> None:
    md_store.create_folder(tmp_path, NOTES, "k8s")
    with pytest.raises(ValidationFailed, match="已存在"):
        md_store.create_folder(tmp_path, NOTES, "k8s")


def test_list_folders_excludes_reserved_and_sorted(tmp_path: Path) -> None:
    md_store.create_folder(tmp_path, NOTES, "zebra")
    md_store.create_folder(tmp_path, NOTES, "Kubernetes/网络")
    md_store.create_folder(tmp_path, NOTES, "alpha")
    # 保留目录即使物理存在也不进列表
    (_notes_dir(tmp_path) / ".backup").mkdir(parents=True)
    (_notes_dir(tmp_path) / "assets").mkdir(parents=True)
    folders = md_store.list_folders(tmp_path, NOTES)
    # 嵌套创建的中间层也是真实文件夹，扁平返回全部、前端组树
    assert folders == [
        {"path": "Kubernetes", "name": "Kubernetes"},
        {"path": "Kubernetes/网络", "name": "网络"},
        {"path": "alpha", "name": "alpha"},
        {"path": "zebra", "name": "zebra"},
    ]


def test_rename_folder_same_parent_keeps_contents(tmp_path: Path) -> None:
    md_store.create_folder(tmp_path, NOTES, "k8s/old")
    note = _notes_dir(tmp_path) / "k8s" / "old" / "2026-11-03-笔记.md"
    note.write_text("---\nid: n1\ntags: []\nrelated: []\n---\n\n# 笔记\n", encoding="utf-8")
    got = md_store.rename_folder(tmp_path, NOTES, "k8s/old", "k8s/new")
    assert got == {"path": "k8s/new", "name": "new"}
    assert not note.exists()
    kept = _notes_dir(tmp_path) / "k8s" / "new" / "2026-11-03-笔记.md"
    assert kept.exists() and "id: n1" in kept.read_text(encoding="utf-8")


def test_rename_folder_rejects_cross_parent_and_reserved(tmp_path: Path) -> None:
    md_store.create_folder(tmp_path, NOTES, "k8s/old")
    md_store.create_folder(tmp_path, NOTES, "other")
    with pytest.raises(ValidationFailed, match="同父目录"):
        md_store.rename_folder(tmp_path, NOTES, "k8s/old", "other/old")
    with pytest.raises(ValidationFailed):
        md_store.rename_folder(tmp_path, NOTES, "k8s/old", "k8s/assets")
    with pytest.raises(NotFound):
        md_store.rename_folder(tmp_path, NOTES, "ghost", "k8s/ghost2")


# ------------------------------------------------- 递归列举 / 查找 / 单篇


def _write_note(tmp_path: Path, rel_path: str, doc_id: str, title: str) -> Path:
    path = _notes_dir(tmp_path) / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nid: {doc_id}\ncreated: 2026-11-03\ntags: []\nrelated: []\n---\n\n# {title}\n\n正文。\n",
        encoding="utf-8",
    )
    return path


def test_list_notes_recursive_with_folder_field(tmp_path: Path) -> None:
    _write_note(tmp_path, "2026-09-01-根层笔记.md", "n-root", "根层笔记")
    _write_note(tmp_path, "k8s/2026-10-01-目录笔记.md", "n-k8s", "目录笔记")
    _write_note(tmp_path, "k8s/网络/2026-11-01-深层笔记.md", "n-deep", "深层笔记")
    docs = md_store.list_notes(tmp_path, NOTES)
    by_id = {d["id"]: d for d in docs}
    assert set(by_id) == {"n-root", "n-k8s", "n-deep"}
    assert by_id["n-root"]["folder"] == ""
    assert by_id["n-k8s"]["folder"] == "k8s"
    assert by_id["n-deep"]["folder"] == "k8s/网络"
    # 沿用备忘排序：日期倒序（新在前）
    assert [d["id"] for d in docs] == ["n-deep", "n-k8s", "n-root"]
    # 列表是摘要形状：不含正文 content
    assert all("content" not in d for d in docs)


def test_list_notes_excludes_reserved_subtrees(tmp_path: Path) -> None:
    _write_note(tmp_path, "2026-11-01-正规笔记.md", "n-ok", "正规笔记")
    backup = _notes_dir(tmp_path) / ".backup"
    assets = _notes_dir(tmp_path) / "assets"
    backup.mkdir(parents=True)
    assets.mkdir(parents=True)
    (backup / "2026-01-01-冷快照.md").write_text(
        "---\nid: n-backup\ntags: []\nrelated: []\n---\n\nx\n", encoding="utf-8"
    )
    (assets / "evil.md").write_text(
        "---\nid: n-asset\ntags: []\nrelated: []\n---\n\nx\n", encoding="utf-8"
    )
    # 嵌套保留目录同样排除
    nested_reserved = _notes_dir(tmp_path) / "k8s" / "assets"
    nested_reserved.mkdir(parents=True)
    (nested_reserved / "x.md").write_text("---\nid: n-x\ntags: []\nrelated: []\n---\n", encoding="utf-8")
    assert [d["id"] for d in md_store.list_notes(tmp_path, NOTES)] == ["n-ok"]


def test_find_and_get_note_across_folders(tmp_path: Path) -> None:
    p = _write_note(tmp_path, "k8s/网络/2026-11-01-深层笔记.md", "n-deep", "深层笔记")
    found = md_store.find_note_path(tmp_path, NOTES, "n-deep")
    assert found == p
    # 文件名（去扩展名）兜底匹配
    assert md_store.find_note_path(tmp_path, NOTES, "2026-11-01-深层笔记") == p
    assert md_store.find_note_path(tmp_path, NOTES, "不存在") is None
    doc = md_store.get_note(tmp_path, NOTES, "n-deep")
    assert doc is not None
    assert doc["folder"] == "k8s/网络" and doc["filename"] == "2026-11-01-深层笔记.md"
    assert "正文。" in doc["content"]
    assert md_store.get_note(tmp_path, NOTES, "幽灵") is None


def test_notes_and_memos_listings_are_isolated(tmp_path: Path) -> None:
    _write_note(tmp_path, "2026-11-01-笔记.md", "20261101-note-甲", "笔记")
    md_store.write_markdown(
        tmp_path, md_store.MEMOS, "2026-11-01-备忘.md",
        {"id": "20261101-memo-甲", "tags": [], "related": []}, "# 备忘\n",
    )
    assert [d["id"] for d in md_store.list_notes(tmp_path, NOTES)] == ["20261101-note-甲"]
    assert [d["id"] for d in md_store.list_markdown(tmp_path, md_store.MEMOS)] == ["20261101-memo-甲"]


# ------------------------------------------------- 写入 / 删除 / 备份前缀


def test_folder_flat_prefix() -> None:
    assert md_store.folder_flat_prefix("") == ""
    assert md_store.folder_flat_prefix("k8s") == "k8s__"
    assert md_store.folder_flat_prefix("k8s/网络") == "k8s__网络__"


def test_write_note_into_nested_folder_roundtrip(tmp_path: Path) -> None:
    meta = {"id": "20261103-note-深", "created": "2026-11-03", "tags": ["k8s"], "related": []}
    path = md_store.write_note(
        tmp_path, NOTES, "k8s/网络", "2026-11-03-深层笔记.md", meta, "# 深层笔记\n\n正文",
    )
    assert path == _notes_dir(tmp_path) / "k8s" / "网络" / "2026-11-03-深层笔记.md"
    doc = md_store.get_note(tmp_path, NOTES, "20261103-note-深")
    assert doc is not None and doc["folder"] == "k8s/网络" and doc["tags"] == ["k8s"]
    # frontmatter 落盘键序固定且无 folder/updated 字段（回读解析，兼容块序列）
    post = frontmatter.load(path)
    assert list(post.metadata.keys()) == ["id", "created", "tags", "related"]
    assert "folder" not in post.metadata and "updated" not in post.metadata


def test_write_note_backup_flat_with_folder_prefix(tmp_path: Path) -> None:
    meta = {"id": "n1", "created": "2026-11-03", "tags": [], "related": []}
    md_store.write_note(tmp_path, NOTES, "k8s/网络", "2026-11-03-笔记.md", meta, "v1")
    md_store.write_note(tmp_path, NOTES, "k8s/网络", "2026-11-03-笔记.md", meta, "v2")
    backups = sorted((_notes_dir(tmp_path) / ".backup").glob("*.md"))
    assert len(backups) == 1
    # 平铺在 notes/.backup，文件名带文件夹前缀防跨目录同名冲突
    assert backups[0].name.startswith("k8s__网络__2026-11-03-笔记-")
    assert "v1" in backups[0].read_text(encoding="utf-8")


def test_make_note_filename_conflict_scoped_to_folder(tmp_path: Path) -> None:
    md_store.write_note(
        tmp_path, NOTES, "k8s", "2026-11-03-开会.md",
        {"id": "a", "created": "2026-11-03", "tags": [], "related": []}, "x",
    )
    # 另一文件夹同名不冲突
    assert md_store.make_note_filename(tmp_path, NOTES, "other", "2026-11-03", "开会") == "2026-11-03-开会.md"
    # 同文件夹冲突追加短后缀
    name = md_store.make_note_filename(tmp_path, NOTES, "k8s", "2026-11-03", "开会")
    assert re.fullmatch(r"2026-11-03-开会-[0-9a-f]{4}\.md", name), name


def test_write_note_move_old_path_backed_up_with_own_prefix(tmp_path: Path) -> None:
    meta = {"id": "n1", "created": "2026-11-03", "tags": [], "related": []}
    old = md_store.write_note(tmp_path, NOTES, "old", "2026-11-03-搬家.md", meta, "旧目录正文")
    new = md_store.write_note(
        tmp_path, NOTES, "new", "2026-11-03-搬家.md", meta, "新目录正文", old_path=old,
    )
    assert new.exists() and not old.exists()
    backups = sorted((_notes_dir(tmp_path) / ".backup").glob("*.md"))
    assert any(b.name.startswith("old__2026-11-03-搬家-") for b in backups), [b.name for b in backups]
    assert md_store.find_note_path(tmp_path, NOTES, "n1") == new


def test_delete_note_backs_up_with_prefix(tmp_path: Path) -> None:
    md_store.write_note(
        tmp_path, NOTES, "k8s", "2026-11-03-待删.md",
        {"id": "n-del", "created": "2026-11-03", "tags": [], "related": []}, "正文",
    )
    deleted = md_store.delete_note(tmp_path, NOTES, "n-del")
    assert not deleted.exists()
    backups = list((_notes_dir(tmp_path) / ".backup").glob("*.md"))
    assert len(backups) == 1 and backups[0].name.startswith("k8s__2026-11-03-待删-")
    with pytest.raises(FileNotFoundError):
        md_store.delete_note(tmp_path, NOTES, "n-del")


def test_note_backup_rolling_10_shared_flat_dir(tmp_path: Path) -> None:
    meta = {"id": "roll", "created": "2026-11-03", "tags": [], "related": []}
    for i in range(12):
        md_store.write_note(tmp_path, NOTES, "k8s", "2026-11-03-滚动.md", meta, f"v{i}")
    backups = list((_notes_dir(tmp_path) / ".backup").glob("*.md"))
    assert len(backups) == 10, "notes/.backup 平铺滚动保留 10 份（与文件夹前缀无关）"


# ------------------------------------------------- 正文资产链接改写


def test_rewrite_asset_links_by_depth() -> None:
    body = (
        "![封面](assets/20261103-101010-abcd1234.png)\n\n"
        "[另一张](assets/20261103-101010-eeee5678.jpg)\n"
    )
    out = md_store.rewrite_asset_links(body, new_depth=2)
    assert "![封面](../../assets/20261103-101010-abcd1234.png)" in out
    assert "[另一张](../../assets/20261103-101010-eeee5678.jpg)" in out
    # 根层 depth=0：维持 assets/ 裸相对路径（与备忘写法一致）
    assert md_store.rewrite_asset_links(body, new_depth=0) == body


def test_rewrite_asset_links_normalizes_old_depth() -> None:
    # 从深度 2 搬到深度 1：旧的 ../../ 归一为 ../
    body = "![]( ../../assets/x.png)".replace(" ", "")
    assert md_store.rewrite_asset_links(body, new_depth=1) == "![](../assets/x.png)"
    # 从深度 2 搬回根层
    assert md_store.rewrite_asset_links(body, new_depth=0) == "![](assets/x.png)"


def test_rewrite_asset_links_handles_title_angle_and_dot_slash() -> None:
    # 手工/Obsidian 常见写法也必须能改写，否则移动后裂图
    body = (
        '![](assets/a.png "封面标题")\n'
        "![](<assets/b.png>)\n"
        "![](./assets/c.png)\n"
        "[图](<../../assets/d.webp>)\n"
    )
    out = md_store.rewrite_asset_links(body, new_depth=1)
    assert '![](../assets/a.png "封面标题")' in out
    assert "![](<../assets/b.png>)" in out
    assert "![](../assets/c.png)" in out
    assert "[](<../assets/d.webp>)".replace("[]", "[图]") in out
    # 定深幂等：再跑一次结果不变
    assert md_store.rewrite_asset_links(out, new_depth=1) == out


def test_rewrite_asset_links_leaves_non_asset_links() -> None:
    body = (
        "[外链](https://example.com/page)\n"
        "[相邻文档](./other.md)\n"
        "[上级文档](../readme.md)\n"
        "正文 ![](assets/p.png) 收尾\n"
    )
    out = md_store.rewrite_asset_links(body, new_depth=1)
    assert "[外链](https://example.com/page)" in out
    assert "[相邻文档](./other.md)" in out
    assert "[上级文档](../readme.md)" in out
    assert "![]( ../assets/p.png)".replace(" ", "") in out


# ------------------------------------------------- 笔记图片资产（内核）


def test_save_note_asset_folder_prefixed_name_and_depth_path(tmp_path: Path) -> None:
    from app.datastore import asset_store

    png = base64_png()
    d = asset_store.save_asset(tmp_path, NOTES, png, ".png", folder="k8s/网络")
    # 平铺在 notes/assets，文件名带文件夹前缀（多层段间 __，保留中文归属可辨）
    assert d["name"].startswith("k8s__网络__")
    assert re.fullmatch(r"k8s__网络__\d{8}-\d{6}-[0-9a-f]{8}\.png", d["name"])
    assert d["path"] == f"../../assets/{d['name']}", "深度 2 → ../../ 相对链接"
    on_disk = _notes_dir(tmp_path) / "assets" / d["name"]
    assert on_disk.read_bytes() == png
    # 可按名取回，中文前缀不影响边界校验
    path, media = asset_store.resolve_asset(tmp_path, NOTES, d["name"])
    assert path == on_disk and media == "image/png"


def test_save_note_asset_root_has_no_prefix(tmp_path: Path) -> None:
    from app.datastore import asset_store

    d = asset_store.save_asset(tmp_path, NOTES, base64_png(), ".png", folder="")
    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{8}\.png", d["name"])
    assert d["path"] == f"assets/{d['name']}", "根层与备忘写法一致"


def test_memo_asset_behavior_unchanged_after_prefix_param(tmp_path: Path) -> None:
    from app.datastore import asset_store

    d = asset_store.save_asset(tmp_path, md_store.MEMOS, base64_png(), ".png")
    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{8}\.png", d["name"])
    assert d["path"] == f"assets/{d['name']}"


def test_resolve_asset_still_blocks_illegal_names(tmp_path: Path) -> None:
    from app.datastore import asset_store
    from app.core.errors import ApiError

    for bad in ["..", ".", "../x.png", "a/b.png", "-leading.png", "has space.png", "x" * 151 + ".png"]:
        with pytest.raises(ApiError):
            asset_store.resolve_asset(tmp_path, NOTES, bad)


def test_delete_folder_empty_only(tmp_path: Path) -> None:
    md_store.create_folder(tmp_path, NOTES, "empty")
    md_store.create_folder(tmp_path, NOTES, "full")
    (_notes_dir(tmp_path) / "full" / "2026-11-03-笔记.md").write_text("x", encoding="utf-8")
    md_store.delete_folder(tmp_path, NOTES, "empty")
    assert not (_notes_dir(tmp_path) / "empty").exists()
    with pytest.raises(ValidationFailed, match="非空"):
        md_store.delete_folder(tmp_path, NOTES, "full")
    with pytest.raises(NotFound):
        md_store.delete_folder(tmp_path, NOTES, "ghost")
    with pytest.raises(ValidationFailed):
        md_store.delete_folder(tmp_path, NOTES, ".backup")
