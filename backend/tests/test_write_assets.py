"""备忘图片资产接口测试（T1 改名后走 /api/memos/assets）：上传/取图/安全闸门/用户隔离/富文本正文往返。"""

import base64
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.datastore import asset_store

# 1×1 PNG（合法完整文件）
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
# 仅需通过 magic 嗅探的最小头（路由不做完整解码）
JPEG_HEAD = b"\xff\xd8\xff\xe0" + b"0" * 20
GIF_HEAD = b"GIF89a" + b"0" * 20
WEBP_HEAD = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBPVP8 " + b"0" * 12

NAME_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{8}\.(png|jpg|jpeg|gif|webp)$")


def _upload(client: TestClient, filename: str, data: bytes, ctype: str = "image/png", user: str = "tester"):
    return client.post(
        "/api/memos/assets",
        params={"user": user},
        files={"file": (filename, data, ctype)},
    )


# ------------------------------------------------------------------ 上传/回读


def test_upload_then_get_roundtrip(client: TestClient, tester_dir: Path) -> None:
    r = _upload(client, "tiny.png", PNG_1X1)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert NAME_RE.match(d["name"]), d["name"]
    assert d["path"] == f"assets/{d['name']}"
    assert d["size"] == len(PNG_1X1)
    assert d["content_type"] == "image/png"

    on_disk = tester_dir / "memos" / "assets" / d["name"]
    assert on_disk.read_bytes() == PNG_1X1  # 字节级原样落盘

    g = client.get(f"/api/memos/assets/{d['name']}", params={"user": "tester"})
    assert g.status_code == 200
    assert g.content == PNG_1X1
    assert g.headers["content-type"] == "image/png"
    assert g.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "filename,data",
    [("shot.jpg", JPEG_HEAD), ("shot.jpeg", JPEG_HEAD),
     ("a.gif", GIF_HEAD), ("a.webp", WEBP_HEAD)],
)
def test_upload_other_kinds_ok(client: TestClient, filename: str, data: bytes) -> None:
    r = _upload(client, filename, data, "application/octet-stream")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["name"].endswith(Path(filename).suffix)


# ------------------------------------------------------------------ 安全闸门


@pytest.mark.parametrize("filename", ["evil.svg", "evil.exe", "evil.html", "noext"])
def test_reject_bad_extension(client: TestClient, tester_dir: Path, filename: str) -> None:
    r = _upload(client, filename, PNG_1X1)
    assert r.status_code == 422
    assert not (tester_dir / "memos" / "assets").exists() or not list(
        (tester_dir / "memos" / "assets").iterdir()
    )


def test_reject_extension_content_mismatch(client: TestClient, tester_dir: Path) -> None:
    r = _upload(client, "fake.png", b"not an image")
    assert r.status_code == 422
    assert "扩展名不符" in r.json()["detail"]
    assert not (tester_dir / "memos" / "assets").exists()


def test_reject_oversize_before_write(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tester_dir: Path
) -> None:
    monkeypatch.setattr(asset_store, "MAX_ASSET_BYTES", 64)
    r = _upload(client, "big.png", b"0" * 1024)
    assert r.status_code == 422
    assert "过大" in r.json()["detail"]
    assets = tester_dir / "memos" / "assets"
    assert not assets.exists() or not list(assets.iterdir())  # 无目标、无 .tmp 残留


# 注：裸 ".."/"." 会被 HTTP 客户端在发送前路径归一化（/api/memos/assets/..
# → /api/memos），到不了处理器；故这里用百分号编码点段测服务端真实入口
@pytest.mark.parametrize("name", [
    "%2e%2e", "%2e", "%2e%2e%2fx.png", "a/b.png", "..%2f..%2fcalendar.ics",
    "foo.TMP", "-leading.png", "has space.png",
])
def test_get_illegal_name_blocked(client: TestClient, name: str) -> None:
    r = client.get(f"/api/memos/assets/{name}", params={"user": "tester"})
    assert r.status_code >= 400
    assert b"---" not in r.content  # 绝不返回任何 markdown/frontmatter 字节


def test_get_missing_is_404(client: TestClient) -> None:
    r = client.get("/api/memos/assets/20200101-000000-abcd1234.png", params={"user": "tester"})
    assert r.status_code == 404


def test_assets_dir_excluded_from_memo_list(client: TestClient, tester_dir: Path) -> None:
    before = client.get("/api/memos", params={"user": "tester"}).json()["count"]
    assets = tester_dir / "memos" / "assets"
    assets.mkdir(parents=True)
    (assets / "evil.md").write_text("---\nid: should-not-appear\ntags: []\nrelated: []\n---\n\nx\n",
                                    encoding="utf-8")
    (assets / "pic.png").write_bytes(PNG_1X1)
    after = client.get("/api/memos", params={"user": "tester"}).json()["count"]
    assert after == before


def test_user_isolation(client: TestClient) -> None:
    name = _upload(client, "tiny.png", PNG_1X1).json()["data"]["name"]
    other = client.get(f"/api/memos/assets/{name}", params={"user": "example"})
    assert other.status_code == 404


# ------------------------------------------------------ 富文本正文原样往返


def test_rich_markdown_body_roundtrip_and_h1_idempotent(client: TestClient) -> None:
    rich = (
        "# 富文本验收\n\n"
        "**粗** *斜*\n\n"
        "## 小节\n\n"
        "### 中标题\n\n"
        "#### 小标题\n\n"
        "- 无序一\n"
        "- 无序二\n\n"
        "1. 有序一\n"
        "2. 有序二\n\n"
        "| 列1 | 列2 |\n"
        "| --- | --- |\n"
        "| 1 | 2 |\n\n"
        "![](assets/20261030-101010-deadbeef.png)\n"
    )
    r = client.post("/api/memos", params={"user": "tester"}, json={
        "title": "富文本验收", "content": rich, "tags": ["验收"],
    })
    assert r.status_code == 200, r.text
    memo = r.json()["data"]
    assert memo["content"].strip() == rich.strip()  # 表格/图片/列表语法逐字保留

    # GET→PUT 幂等：原样回传不产生双 H1
    mid = memo["id"]
    g = client.get(f"/api/memos/{mid}", params={"user": "tester"}).json()
    r2 = client.put(f"/api/memos/{mid}", params={"user": "tester"}, json={
        "title": "富文本验收", "content": g["content"],
        "tags": g["tags"], "related": g["related"],
    })
    assert r2.status_code == 200
    assert r2.json()["data"]["content"].count("# 富文本验收") == 1
