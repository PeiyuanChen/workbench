"""笔记图片资产 HTTP 测试（#4）：前缀命名、深度相对链接、安全闸门、用户隔离。

安全水位与备忘对等（5 MiB / 扩展名白名单 / magic byte / 路径穿越 / write-once），
这里锁笔记特有的文件夹前缀与深度行为，并对安全闸门做关键回归。
"""

import base64
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.datastore import asset_store

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
JPEG_HEAD = b"\xff\xd8\xff\xe0" + b"0" * 20


def _upload(client: TestClient, filename: str, data: bytes, folder: str = "", user: str = "tester"):
    return client.post(
        "/api/notes/assets",
        params={"user": user},
        data={"folder": folder},
        files={"file": (filename, data, "image/png")},
    )


def _make_folder(client: TestClient, path: str) -> None:
    r = client.post("/api/notes/folders", params={"user": "tester"}, json={"path": path})
    assert r.status_code == 200, r.text


# ---------------------------------------------------------- 前缀与深度链接


def test_upload_root_asset_no_prefix(client: TestClient, tester_dir: Path) -> None:
    r = _upload(client, "tiny.png", PNG_1X1)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{8}\.png", d["name"])
    assert d["path"] == f"assets/{d['name']}"
    assert (tester_dir / "notes" / "assets" / d["name"]).read_bytes() == PNG_1X1


def test_upload_folder_asset_prefixed_and_depth_relative(client: TestClient, tester_dir: Path) -> None:
    _make_folder(client, "k8s/网络")
    r = _upload(client, "shot.png", PNG_1X1, folder="k8s/网络")
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert re.fullmatch(r"k8s__网络__\d{8}-\d{6}-[0-9a-f]{8}\.png", d["name"])
    # 深度 2 → 正文相对链接 ../../assets/<名>，通用 Markdown 工具可直接打开
    assert d["path"] == f"../../assets/{d['name']}"
    on_disk = tester_dir / "notes" / "assets" / d["name"]  # 资产仍平铺，不进子目录
    assert on_disk.is_file()
    g = client.get(f"/api/notes/assets/{d['name']}", params={"user": "tester"})
    assert g.status_code == 200 and g.content == PNG_1X1
    assert g.headers["x-content-type-options"] == "nosniff"


def test_upload_asset_folder_must_exist(client: TestClient, tester_dir: Path) -> None:
    r = _upload(client, "tiny.png", PNG_1X1, folder="ghost")
    assert r.status_code == 422 and "文件夹不存在" in r.json()["detail"]
    assert not (tester_dir / "notes" / "assets").exists()


def test_upload_asset_rejects_traversal_folder(client: TestClient) -> None:
    r = _upload(client, "tiny.png", PNG_1X1, folder="../escape")
    assert r.status_code == 422


# ---------------------------------------------------------- 安全闸门回归


@pytest.mark.parametrize("filename", ["evil.svg", "evil.exe", "evil.html", "noext"])
def test_reject_bad_extension(client: TestClient, tester_dir: Path, filename: str) -> None:
    r = _upload(client, filename, PNG_1X1)
    assert r.status_code == 422
    assets = tester_dir / "notes" / "assets"
    assert not assets.exists() or not list(assets.iterdir())


def test_reject_content_mismatch_and_oversize(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tester_dir: Path
) -> None:
    assert _upload(client, "fake.png", b"not an image").status_code == 422
    monkeypatch.setattr(asset_store, "MAX_ASSET_BYTES", 64)
    r = _upload(client, "big.png", b"0" * 1024)
    assert r.status_code == 422 and "过大" in r.json()["detail"]
    assets = tester_dir / "notes" / "assets"
    assert not assets.exists() or not list(assets.iterdir())


@pytest.mark.parametrize("name", [
    "%2e%2e", "%2e%2e%2fx.png", "a/b.png", "..%2f..%2fcalendar.ics",
    "foo.TMP", "-leading.png", "has space.png",
])
def test_get_illegal_name_blocked(client: TestClient, name: str) -> None:
    r = client.get(f"/api/notes/assets/{name}", params={"user": "tester"})
    assert r.status_code >= 400
    assert b"---" not in r.content


def test_write_once_name_never_overwrites(client: TestClient, tester_dir: Path) -> None:
    d1 = _upload(client, "a.jpg", JPEG_HEAD).json()["data"]
    d2 = _upload(client, "a.jpg", JPEG_HEAD).json()["data"]
    assert d1["name"] != d2["name"], "随机名 write-once，永不覆盖"
    assert len(list((tester_dir / "notes" / "assets").iterdir())) == 2


def test_asset_user_isolation(client: TestClient) -> None:
    name = _upload(client, "tiny.png", PNG_1X1).json()["data"]["name"]
    assert client.get(f"/api/notes/assets/{name}", params={"user": "example"}).status_code == 404


# ---------------------------------------------------------- 端到端：上传→引用→移动不裂图


def test_upload_then_move_note_links_stay_resolvable(client: TestClient, tester_dir: Path) -> None:
    _make_folder(client, "deep/nest")
    # 在深度 2 的文件夹里上传，拿到正确相对链接并写进笔记正文
    asset = _upload(client, "pic.png", PNG_1X1, folder="deep/nest").json()["data"]
    n = client.post("/api/notes", params={"user": "tester"}, json={
        "title": "图文笔记", "folder": "deep/nest",
        "content": f"# 图文笔记\n\n![]({asset['path']})\n",
    }).json()["data"]
    note_path = tester_dir / "notes" / "deep" / "nest" / n["filename"]
    # 相对链接从笔记所在目录解析，必须命中真实资产文件
    linked = (note_path.parent / asset["path"]).resolve()
    assert linked.is_file() and linked.read_bytes() == PNG_1X1
    # 搬到根层：服务端改写为裸 assets/ 链接，依然可解析
    r = client.put(f"/api/notes/{n['id']}", params={"user": "tester"}, json={
        "title": "图文笔记", "folder": "", "content": n_disk_content(client, n["id"]),
    })
    assert r.status_code == 200
    moved = tester_dir / "notes" / n["filename"]
    assert f"](assets/{asset['name']})" in moved.read_text(encoding="utf-8")
    assert (moved.parent / "assets" / asset["name"]).is_file()


def n_disk_content(client: TestClient, note_id: str) -> str:
    return client.get(f"/api/notes/{note_id}", params={"user": "tester"}).json()["content"]
