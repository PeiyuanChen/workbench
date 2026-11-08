"""笔记写接口 HTTP 测试（#4 验收；TestClient + 临时数据根 seam）。

覆盖：笔记 CRUD、标题三源一致、文件夹真实子目录 CRUD、移动与正文资产链接
改写、列表扁平形状、保留名/穿越 422、备份前缀、用户隔离、信封契约。
数据底座 data-samples/notes（根层 1 篇 + k8s/ 下 1 篇）。
"""

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

ID_RE = re.compile(r"^\d{8}-note-\S+$")
SH = ZoneInfo("Asia/Shanghai")


def _today_sh() -> str:
    return datetime.now(SH).strftime("%Y-%m-%d")


def _post(client: TestClient, payload: dict):
    return client.post("/api/notes", params={"user": "tester"}, json=payload)


def _put(client: TestClient, note_id: str, payload: dict):
    return client.put(f"/api/notes/{quote(note_id, safe='')}", params={"user": "tester"}, json=payload)


def _get_one(client: TestClient, note_id: str):
    return client.get(f"/api/notes/{quote(note_id, safe='')}", params={"user": "tester"})


def _delete(client: TestClient, note_id: str):
    return client.delete(f"/api/notes/{quote(note_id, safe='')}", params={"user": "tester"})


def _list(client: TestClient) -> dict:
    return client.get("/api/notes", params={"user": "tester"}).json()


def _notes_dir(tester_dir: Path) -> Path:
    return tester_dir / "notes"


def _backups(tester_dir: Path) -> list[Path]:
    d = _notes_dir(tester_dir) / ".backup"
    return sorted(d.glob("*.md")) if d.exists() else []


# ---------------------------------------------------------------- 列表形状


def test_list_shape_folders_and_items(client: TestClient) -> None:
    body = _list(client)
    assert set(body) == {"count", "folders", "items"}
    assert body["count"] == 2  # data-samples/notes：根层 1 + k8s 1
    assert body["folders"] == [{"path": "k8s", "name": "k8s"}]
    by_id = {i["id"]: i for i in body["items"]}
    root = next(i for i in body["items"] if i["folder"] == "")
    assert root["id"] == "20260903-note-k8s-intro"
    deep = by_id["20261103-note-k8s-network"]
    assert deep["folder"] == "k8s" and "content" not in deep, "列表不含全文"


def test_list_excludes_backup_and_assets(client: TestClient, tester_dir: Path) -> None:
    assets = _notes_dir(tester_dir) / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "evil.md").write_text(
        "---\nid: should-not-appear\ntags: []\nrelated: []\n---\n\nx\n", encoding="utf-8"
    )
    backup = _notes_dir(tester_dir) / ".backup"
    backup.mkdir(parents=True, exist_ok=True)
    (backup / "cold.md").write_text(
        "---\nid: cold\ntags: []\nrelated: []\n---\n\nx\n", encoding="utf-8"
    )
    assert _list(client)["count"] == 2


def test_ghost_user_empty_shape(client: TestClient) -> None:
    body = client.get("/api/notes", params={"user": "ghost"}).json()
    assert body == {"count": 0, "folders": [], "items": []}


# ---------------------------------------------------------------- POST


def test_post_note_minimal_at_root(client: TestClient, tester_dir: Path) -> None:
    r = _post(client, {"title": "测试笔记", "content": "第一段", "tags": ["验收"]})
    assert r.status_code == 200 and r.json()["ok"] is True
    n = r.json()["data"]
    assert ID_RE.match(n["id"]) and "测试笔记" in n["id"]
    assert n["id"].startswith(datetime.now(SH).strftime("%Y%m%d"))
    assert n["filename"] == f"{_today_sh()}-测试笔记.md"
    assert n["folder"] == "" and n["created"] == _today_sh()
    assert n["tags"] == ["验收"] and n["related"] == []
    assert n["content"].startswith("# 测试笔记") and "第一段" in n["content"]
    assert (_notes_dir(tester_dir) / n["filename"]).exists()
    # 落盘 frontmatter：四键固定键序、无 folder/updated、中文不转义
    raw = (_notes_dir(tester_dir) / n["filename"]).read_text(encoding="utf-8")
    assert "验收" in raw and "\\u" not in raw
    assert "folder:" not in raw and "updated:" not in raw


def test_post_note_into_folder_is_real_subdir(client: TestClient, tester_dir: Path) -> None:
    client.post("/api/notes/folders", params={"user": "tester"}, json={"path": "Kubernetes/网络"})
    r = _post(client, {"title": "深层", "folder": "Kubernetes/网络"})
    assert r.status_code == 200, r.text
    n = r.json()["data"]
    assert n["folder"] == "Kubernetes/网络"
    on_disk = _notes_dir(tester_dir) / "Kubernetes" / "网络" / n["filename"]
    assert on_disk.is_file()
    assert _get_one(client, n["id"]).json()["folder"] == "Kubernetes/网络"


def test_post_note_folder_must_exist(client: TestClient) -> None:
    r = _post(client, {"title": "孤儿", "folder": "ghost"})
    assert r.status_code == 422 and "文件夹不存在" in r.json()["detail"]


def test_post_note_validation(client: TestClient) -> None:
    assert _post(client, {"title": "  "}).status_code == 422
    assert _post(client, {}).status_code == 422
    assert _post(client, {"title": "x", "slug": "y"}).status_code == 422  # extra=forbid
    assert _post(client, {"title": "x", "folder": "../escape"}).status_code == 422


def test_post_same_title_conflict_scoped_by_folder(client: TestClient) -> None:
    client.post("/api/notes/folders", params={"user": "tester"}, json={"path": "f2"})
    a = _post(client, {"title": "同题"}).json()["data"]
    b = _post(client, {"title": "同题"}).json()["data"]
    c = _post(client, {"title": "同题", "folder": "f2"}).json()["data"]
    assert a["id"] != b["id"] and a["filename"] != b["filename"], "同目录冲突加后缀"
    assert c["filename"] == a["filename"], "不同文件夹允许同名文件"
    assert all(_get_one(client, nid).status_code == 200 for nid in (a["id"], b["id"], c["id"]))


# ---------------------------------------------------------------- PUT


def test_put_full_update_and_idempotent(client: TestClient) -> None:
    n = _post(client, {"title": "草稿", "content": "v1", "tags": ["a"]}).json()["data"]
    d = _put(client, n["id"], {"title": "草稿", "content": "v2", "tags": ["a", "b"]}).json()["data"]
    assert d["id"] == n["id"] and d["filename"] == n["filename"]
    assert d["tags"] == ["a", "b"] and d["related"] == [], "未传 related 重置空"
    d2 = _put(client, n["id"], {"title": "草稿", "content": "v2"}).json()["data"]
    assert d2["tags"] == [] and d2["related"] == [], "PUT 全文更新：未传即重置"
    g = _get_one(client, n["id"]).json()
    d3 = _put(client, n["id"], {"title": "草稿", "content": g["content"], "tags": g["tags"],
                                "related": g["related"]}).json()["data"]
    assert d3["content"].count("# 草稿") == 1, "GET→PUT 幂等无双 H1"


def test_put_rename_keeps_id_created_date_prefix(client: TestClient, tester_dir: Path) -> None:
    n = _post(client, {"title": "旧题"}).json()["data"]
    d = _put(client, n["id"], {"title": "新题", "content": "正文"}).json()["data"]
    assert d["id"] == n["id"] and d["created"] == n["created"]
    assert d["filename"] == f"{_today_sh()}-新题.md"
    assert not (_notes_dir(tester_dir) / n["filename"]).exists()
    assert _get_one(client, n["id"]).json()["title"] == "新题"
    assert len(_backups(tester_dir)) >= 1, "旧文件进 notes/.backup"


def test_put_move_rewrites_asset_links_on_depth_change(client: TestClient, tester_dir: Path) -> None:
    client.post("/api/notes/folders", params={"user": "tester"}, json={"path": "k8s/网络"})
    n = _post(client, {
        "title": "图文",
        "content": "# 图文\n\n![](assets/20261103-101010-abcd1234.png)\n",
    }).json()["data"]
    # 根层 → 深度 2：链接加 ../../
    d = _put(client, n["id"], {"title": "图文", "content": n_disk_content(client, n["id"]),
                               "folder": "k8s/网络"}).json()["data"]
    assert d["folder"] == "k8s/网络" and d["filename"] == n["filename"], "移动只换目录"
    on_disk = _notes_dir(tester_dir) / "k8s" / "网络" / n["filename"]
    assert on_disk.is_file() and not (_notes_dir(tester_dir) / n["filename"]).exists()
    assert "![](../../assets/20261103-101010-abcd1234.png)" in on_disk.read_text(encoding="utf-8")
    # 深度 2 → 深度 1：归一为 ../
    client.post("/api/notes/folders", params={"user": "tester"}, json={"path": "shallow"})
    d2 = _put(client, n["id"], {"title": "图文", "content": d["content"], "folder": "shallow"}).json()["data"]
    moved = _notes_dir(tester_dir) / "shallow" / n["filename"]
    assert "](../assets/20261103-101010-abcd1234.png)" in moved.read_text(encoding="utf-8")
    # 搬回根层：裸 assets/
    d3 = _put(client, n["id"], {"title": "图文", "content": d2["content"], "folder": ""}).json()["data"]
    assert "](assets/20261103-101010-abcd1234.png)" in (_notes_dir(tester_dir) / n["filename"]).read_text(
        encoding="utf-8"
    )
    assert d3["id"] == n["id"]


def test_put_move_same_depth_keeps_links(client: TestClient, tester_dir: Path) -> None:
    client.post("/api/notes/folders", params={"user": "tester"}, json={"path": "a"})
    client.post("/api/notes/folders", params={"user": "tester"}, json={"path": "b"})
    n = _post(client, {"title": "平搬", "folder": "a",
                       "content": "# 平搬\n\n![](assets/x.png)\n"}).json()["data"]
    # 深度 1 → 深度 1，链接形态不变（本来就是 ../assets）
    d = _put(client, n["id"], {"title": "平搬", "content": n_disk_content(client, n["id"]),
                               "folder": "b"}).json()["data"]
    text = (_notes_dir(tester_dir) / "b" / n["filename"]).read_text(encoding="utf-8")
    assert "](../assets/x.png)" in text and d["folder"] == "b"


def test_put_move_target_folder_must_exist(client: TestClient) -> None:
    n = _post(client, {"title": "x"}).json()["data"]
    r = _put(client, n["id"], {"title": "x", "folder": "nope"})
    assert r.status_code == 422 and "文件夹不存在" in r.json()["detail"]


def test_put_404(client: TestClient) -> None:
    r = _put(client, "不存在的id", {"title": "x"})
    assert r.status_code == 404 and "不存在" in r.json()["detail"]


# ---------------------------------------------------------------- DELETE


def test_delete_note_backs_up_with_folder_prefix(client: TestClient, tester_dir: Path) -> None:
    client.post("/api/notes/folders", params={"user": "tester"}, json={"path": "del"})
    n = _post(client, {"title": "待删", "folder": "del"}).json()["data"]
    r = _delete(client, n["id"])
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["data"]["id"] == n["id"]
    assert _get_one(client, n["id"]).status_code == 404
    assert not (_notes_dir(tester_dir) / "del" / n["filename"]).exists()
    assert any(b.name.startswith("del__") for b in _backups(tester_dir))
    assert _delete(client, n["id"]).status_code == 404


# ---------------------------------------------------------------- 文件夹端点


def test_folder_crud_and_non_empty_guard(client: TestClient, tester_dir: Path) -> None:
    r = client.post("/api/notes/folders", params={"user": "tester"}, json={"path": "主题/子题"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.json()["data"] == {"path": "主题/子题", "name": "子题"}
    assert (_notes_dir(tester_dir) / "主题" / "子题").is_dir()
    # 重命名（同父目录），内部笔记内容零改动
    n = _post(client, {"title": "馆内", "folder": "主题/子题"}).json()["data"]
    rn = client.put("/api/notes/folders", params={"user": "tester"},
                    json={"path": "主题/子题", "new_path": "主题/新题"})
    assert rn.status_code == 200
    kept = _notes_dir(tester_dir) / "主题" / "新题" / n["filename"]
    assert kept.is_file() and "馆内" in kept.read_text(encoding="utf-8")
    # 非空拒绝
    rm = client.delete("/api/notes/folders", params={"user": "tester", "path": "主题/新题"})
    assert rm.status_code == 422 and "非空" in rm.json()["detail"]
    _delete(client, n["id"])
    assert client.delete("/api/notes/folders", params={"user": "tester", "path": "主题/新题"}).status_code == 200
    # 不存在 → 404
    assert client.delete("/api/notes/folders", params={"user": "tester", "path": "幽灵"}).status_code == 404


def test_folder_reserved_and_illegal_names_422(client: TestClient) -> None:
    for bad in [".backup", "assets", "k8s/assets", "../escape", "a?b", "k8s//x"]:
        r = client.post("/api/notes/folders", params={"user": "tester"}, json={"path": bad})
        assert r.status_code == 422, (bad, r.text)
    # 路径段与已有文件冲突 → 中文 422 契约，不允许裸 500
    collide = _post(client, {"title": "占位文件"})
    assert collide.status_code == 200
    fname = collide.json()["data"]["filename"]
    r_file = client.post("/api/notes/folders", params={"user": "tester"},
                         json={"path": f"{fname}/sub"})
    assert r_file.status_code == 422 and "冲突" in r_file.json()["detail"]
    # 重命名跨父目录拒绝
    client.post("/api/notes/folders", params={"user": "tester"}, json={"path": "r1"})
    client.post("/api/notes/folders", params={"user": "tester"}, json={"path": "r2"})
    r = client.put("/api/notes/folders", params={"user": "tester"},
                   json={"path": "r1", "new_path": "r2/r1"})
    assert r.status_code == 422 and "同父目录" in r.json()["detail"]


# ---------------------------------------------------------------- 隔离与信封


def test_user_isolation_notes(client: TestClient) -> None:
    n = _post(client, {"title": "我的"}).json()["data"]
    assert _get_one(client, n["id"]).status_code == 200
    other = client.get(f"/api/notes/{quote(n['id'], safe='')}", params={"user": "example"})
    assert other.status_code == 404


def test_error_envelope_is_chinese_detail(client: TestClient) -> None:
    r = _get_one(client, "幽灵id")
    assert r.status_code == 404 and set(r.json()) == {"detail"}
    assert isinstance(r.json()["detail"], str) and r.json()["detail"]


def n_disk_content(client: TestClient, note_id: str) -> str:
    """取服务端正文（含 H1），用于模拟前端 GET→PUT 原样回传。"""
    return _get_one(client, note_id).json()["content"]
