"""API 集成测试：TestClient + 临时数据目录（不碰真实 data/）。"""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = REPO_ROOT / "data-samples"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """把 data-samples 的三类数据拷进 {tmp}/users/tester，环境变量指向它。"""
    monkeypatch.setenv("WORKBENCH_DATA", str(tmp_path))
    user_dir = tmp_path / "users" / "tester"
    (user_dir / "notes").mkdir(parents=True)
    shutil.copy(SAMPLES / "calendar.ics", user_dir / "calendar.ics")
    for md in (SAMPLES / "notes").glob("*.md"):
        shutil.copy(md, user_dir / "notes" / md.name)
    shutil.copytree(SAMPLES / "timeline", user_dir / "timeline")
    return TestClient(app)


def _get(client: TestClient, path: str, **params):
    """统一带上 user 参数；其余查询参数走 params（勿拼进 URL，避免被覆盖）。"""
    return client.get(path, params={"user": "tester", **params})


def test_health(client: TestClient) -> None:
    assert client.get("/api/health").json()["status"] == "ok"


def test_todos_tree_and_fields(client: TestClient) -> None:
    body = _get(client, "/api/todos").json()
    assert body["count"] == 11  # 14 条 - 3 子任务
    node = body["items"][0]
    for key in ("uid", "summary", "quadrant", "has_time", "overdue", "children", "progress"):
        assert key in node
    parent = next(i for i in body["items"] if "q3-review-parent" in i["uid"])
    assert parent["children_total"] == 3 and parent["children_done"] == 2
    assert parent["quadrant"] == "q1"


def test_todos_filter_unscheduled(client: TestClient) -> None:
    body = _get(client, "/api/todos").json()
    full = {i["uid"] for i in body["items"]}
    unsched = _get(client, "/api/todos", unscheduled=1).json()
    assert unsched["count"] == 6  # 7 条未排期 - 1 条子任务（挂在父下）
    assert set(i["uid"] for i in unsched["items"]) < full


def test_todos_filter_status(client: TestClient) -> None:
    body = _get(client, "/api/todos", status="COMPLETED").json()
    # 两条已完成都是子任务（顶层过滤后为空属预期：子任务不独立出现在顶层）
    assert body["count"] == 0


def test_todo_detail_and_404(client: TestClient) -> None:
    listing = _get(client, "/api/todos").json()
    uid = next(i["uid"] for i in listing["items"] if "q3-review-parent" in i["uid"])
    detail = _get(client, f"/api/todos/{uid}").json()
    assert detail["uid"] == uid and len(detail["children"]) == 3
    assert _get(client, "/api/todos/no-such-uid").status_code == 404


def test_events_september(client: TestClient) -> None:
    body = _get(client, "/api/events", month="2026-09").json()
    assert body["month"] == "2026-09"
    types = [i["type"] for i in body["items"]]
    assert types.count("event") == 1
    assert types.count("block") == 2
    assert types.count("due") == 6
    for item in body["items"]:
        assert item["days_in_month"], "每个条目必须给出月内覆盖日"
        assert all(d.startswith("2026-09-") for d in item["days_in_month"])


def test_events_bad_month(client: TestClient) -> None:
    assert client.get("/api/events", params={"month": "2026-13", "user": "tester"}).status_code == 422
    assert client.get("/api/events", params={"user": "tester"}).status_code == 422


def test_notes(client: TestClient) -> None:
    body = _get(client, "/api/notes").json()
    assert body["count"] == 1
    note_id = body["items"][0]["id"]
    detail = _get(client, f"/api/notes/{note_id}").json()
    assert "content" in detail and "软件只是一层皮" in detail["content"]
    assert _get(client, "/api/notes/no-such-note").status_code == 404


def test_timeline(client: TestClient) -> None:
    got = _get(client, "/api/timeline/2026/3").json()
    assert got["exists"] is True and "川剧智能问答" in got["body"]
    missing = _get(client, "/api/timeline/2026/4").json()
    assert missing["exists"] is False and "message" in missing
    assert client.get("/api/timeline/2026/13", params={"user": "tester"}).status_code == 422


def test_empty_user_dir_returns_empty_not_500(client: TestClient) -> None:
    """me/幽灵用户目录为空：各端点返回空数据而非报错（数据主权容错）。"""
    assert client.get("/api/todos", params={"user": "ghost"}).json() == {"count": 0, "items": []}
    assert client.get("/api/events", params={"month": "2026-09", "user": "ghost"}).json()["items"] == []
    assert client.get("/api/notes", params={"user": "ghost"}).json()["count"] == 0
    assert client.get("/api/timeline/2026/3", params={"user": "ghost"}).json()["exists"] is False
