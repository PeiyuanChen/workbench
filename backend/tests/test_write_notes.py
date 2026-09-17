"""备忘写接口测试（SPEC-M2 §2.3 + 决策 D）。

数据底座 = data-samples/notes（1 篇：20260903-note-workbench-arch，
文件 2026-09-03-工作台设计决策.md）。中文 id 在 URL 路径中 percent-encode
（与前端 encodeURIComponent 行为一致）。
"""

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

SAMPLE_NOTE = "20260903-note-workbench-arch"
SAMPLE_FILE = "2026-09-03-工作台设计决策.md"
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


# ---------------------------------------------------------------- POST


def test_post_note_minimal(client: TestClient, tester_dir: Path) -> None:
    r = _post(client, {"title": "测试笔记", "content": "第一段正文", "tags": ["验收"]})
    assert r.status_code == 200 and r.json()["ok"] is True
    n = r.json()["data"]
    # 决策 D：id = YYYYMMDD-note-<标题清洗>（保留中文）
    assert ID_RE.match(n["id"]) and "测试笔记" in n["id"]
    assert n["id"].startswith(datetime.now(SH).strftime("%Y%m%d"))
    assert n["filename"] == f"{_today_sh()}-测试笔记.md"
    assert n["title"] == "测试笔记"
    assert n["tags"] == ["验收"] and n["related"] == []
    assert n["created"] == _today_sh()
    # 标题三源一致：正文以 H1 开头
    assert n["content"].startswith("# 测试笔记") and "第一段正文" in n["content"]
    assert (_notes_dir(tester_dir) / n["filename"]).exists()
    assert _list(client)["count"] == 2  # 样例 1 篇 + 新建 1 篇
    # 落盘 frontmatter 中文字面不转义
    raw = (_notes_dir(tester_dir) / n["filename"]).read_text(encoding="utf-8")
    assert "验收" in raw and "\\u" not in raw


def test_post_note_filename_sanitize(client: TestClient) -> None:
    title = 'a/b:c*d?"报告"'
    n = _post(client, {"title": title}).json()["data"]
    assert not (set(n["filename"]) & set('<>:"/\\|?*')), n["filename"]
    assert "报告" in n["filename"] and "报告" in n["id"]
    assert n["title"] == title, "H1/frontmatter 承载原标题，文件名只承载清洗版"


def test_post_note_validation_422(client: TestClient) -> None:
    assert _post(client, {"title": "   "}).status_code == 422
    assert "title" in _post(client, {"title": " "}).json()["detail"]
    assert _post(client, {}).status_code == 422  # pydantic missing
    assert _post(client, {"title": "x", "slug": "y"}).status_code == 422  # extra=forbid


def test_post_note_same_title_conflict(client: TestClient) -> None:
    n1 = _post(client, {"title": "开会"}).json()["data"]
    n2 = _post(client, {"title": "开会"}).json()["data"]
    assert n1["id"] != n2["id"] and n1["filename"] != n2["filename"]
    assert _get_one(client, n1["id"]).status_code == 200
    assert _get_one(client, n2["id"]).status_code == 200


# ---------------------------------------------------------------- PUT


def test_put_content_roundtrip(client: TestClient) -> None:
    n = _post(client, {"title": "草稿", "content": "v1", "tags": ["a"]}).json()["data"]
    r = _put(client, n["id"], {
        "title": "草稿", "content": "v2-已修改",
        "tags": ["a", "b"], "related": ["uid:x@workbench.local"],
    })
    d = r.json()["data"]
    assert d["id"] == n["id"] and d["filename"] == n["filename"], "同名 → 原地覆盖不改名"
    assert "v2-已修改" in d["content"]
    assert d["tags"] == ["a", "b"] and d["related"] == ["uid:x@workbench.local"]
    assert _get_one(client, n["id"]).json()["content"] == d["content"]
    # GET→PUT 幂等：content（含 H1）原样回传不产生双 H1
    d2 = _put(client, n["id"], {
        "title": "草稿", "content": d["content"], "tags": ["a", "b"], "related": [],
    }).json()["data"]
    assert d2["content"].count("# 草稿") == 1


def test_put_full_update_resets_missing_fields(client: TestClient) -> None:
    n = _post(client, {"title": "全量", "content": "x", "tags": ["旧标签"]}).json()["data"]
    d = _put(client, n["id"], {"title": "全量", "content": "x"}).json()["data"]
    assert d["tags"] == [] and d["related"] == [], "PUT 全文更新：未传字段重置"


def test_put_rename_sample_keeps_id_and_date_prefix(client: TestClient, tester_dir: Path) -> None:
    """决策 D：改标题 → 重命名保留原创建日期前缀；id/created 不变；旧文件进备份。"""
    r = _put(client, SAMPLE_NOTE, {
        "title": "工作台设计决策V2", "content": "更新正文", "tags": ["数据主权"], "related": [],
    })
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["id"] == SAMPLE_NOTE, "旧 id 不变"
    assert d["filename"] == "2026-09-03-工作台设计决策V2.md", "保留原创建日期前缀"
    assert d["created"] == "2026-09-03" and d["date"] == "2026-09-03"
    assert not (_notes_dir(tester_dir) / SAMPLE_FILE).exists(), "旧文件重命名后不得残留"
    assert len(_backups(tester_dir)) == 1, "旧文件应进 notes/.backup"
    assert d["content"].count("# 工作台设计决策V2") == 1, "无双 H1"
    assert "更新正文" in d["content"]
    # 旧 id 仍可读（id 不随文件名变化）
    assert _get_one(client, SAMPLE_NOTE).json()["title"] == "工作台设计决策V2"


def test_put_rename_replaces_old_h1(client: TestClient) -> None:
    n = _post(client, {"title": "旧题", "content": "# 旧题\n\n正文保留"}).json()["data"]
    d = _put(client, n["id"], {"title": "新题", "content": n["content"], "tags": [], "related": []}).json()["data"]
    assert d["content"].startswith("# 新题")
    assert "# 旧题" not in d["content"] and d["content"].count("# 新题") == 1
    assert "正文保留" in d["content"]
    assert d["id"] == n["id"] and d["filename"].endswith("-新题.md")


def test_put_404(client: TestClient) -> None:
    r = _put(client, "不存在的id", {"title": "x"})
    assert r.status_code == 404 and "不存在" in r.json()["detail"]


# ---------------------------------------------------------------- DELETE


def test_delete_note(client: TestClient, tester_dir: Path) -> None:
    n = _post(client, {"title": "待删", "content": "正文"}).json()["data"]
    r = _delete(client, n["id"])
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.json()["data"]["id"] == n["id"]
    assert _get_one(client, n["id"]).status_code == 404
    assert not any(x["id"] == n["id"] for x in _list(client)["items"])
    assert not (_notes_dir(tester_dir) / n["filename"]).exists()
    assert any("待删" in b.read_text(encoding="utf-8") for b in _backups(tester_dir)), "删除前有备份"
    assert _delete(client, n["id"]).status_code == 404


def test_delete_404(client: TestClient) -> None:
    r = _delete(client, "不存在的id")
    assert r.status_code == 404 and "不存在" in r.json()["detail"]


# ---------------------------------------------------------------- 备份滚动


def test_note_backup_rolling_10(client: TestClient, tester_dir: Path) -> None:
    n = _post(client, {"title": "滚动", "content": "v0"}).json()["data"]
    for i in range(12):
        assert _put(client, n["id"], {"title": "滚动", "content": f"v{i}"}).status_code == 200
    assert len(_backups(tester_dir)) == 10, "notes/.backup 滚动保留 10 份"
