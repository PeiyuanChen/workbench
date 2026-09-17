"""事件写接口测试（SPEC-M2 §2.2）。

数据底座 = data-samples：1 条 VEVENT（20260910-interview-arch，含 VALARM -PT30M）
+ 14 条 VTODO。重点锁定：全天事件 dtend 排他语义 ↔ 月聚合含首尾呈现的往返。
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from icalendar import Calendar

from app.datastore import ics_store

UID_RE = re.compile(r"^\d{8}T\d{6}-[0-9a-f]{4}@workbench\.local$")
SAMPLE_EVENT = "20260910-interview-arch@workbench.local"


def _post(client: TestClient, payload: dict):
    return client.post("/api/events", params={"user": "tester"}, json=payload)


def _patch(client: TestClient, uid: str, payload: dict):
    return client.patch(f"/api/events/{uid}", params={"user": "tester"}, json=payload)


def _read(tester_dir: Path) -> dict:
    return ics_store.read_calendar(tester_dir)


def _raw(tester_dir: Path) -> str:
    return (tester_dir / "calendar.ics").read_text(encoding="utf-8")


def _reparseable(tester_dir: Path) -> None:
    Calendar.from_ical((tester_dir / "calendar.ics").read_bytes())


def _month(client: TestClient, month: str = "2026-09") -> dict:
    return client.get("/api/events", params={"month": month, "user": "tester"}).json()


def _item_of(body: dict, uid: str):
    return next((i for i in body["items"] if i["uid"] == uid), None)


# ---------------------------------------------------------------- POST


def test_post_event_default_30min(client: TestClient, tester_dir: Path) -> None:
    r = _post(client, {"summary": "站会", "dtstart": "2026-09-15T09:30"})
    assert r.status_code == 200
    e = r.json()["data"]
    assert UID_RE.match(e["uid"]), e["uid"]
    assert e["all_day"] is False
    assert e["dtstart"] == "2026-09-15T09:30:00+08:00"
    assert e["dtend"] == "2026-09-15T10:00:00+08:00", "都缺省 → dtstart+30 分钟"
    _reparseable(tester_dir)


def test_post_event_explicit_dtend_and_location(client: TestClient, tester_dir: Path) -> None:
    r = _post(client, {
        "summary": "评审会", "dtstart": "2026-09-16T14:00", "dtend": "2026-09-16T15:30",
        "location": "三楼会议室", "description": "带议程", "categories": ["工作"],
    })
    e = r.json()["data"]
    assert e["dtend"] == "2026-09-16T15:30:00+08:00"
    assert e["location"] == "三楼会议室" and e["description"] == "带议程"
    assert e["categories"] == ["工作"]
    raw = _raw(tester_dir)
    assert "TZID=Asia/Shanghai:20260916T140000" in raw
    _reparseable(tester_dir)


def test_post_event_explicit_duration_stored_as_dtend(client: TestClient) -> None:
    """duration 换算为 dtend 存储（与 _build_event 只写 DTEND 的现状一致）。"""
    r = _post(client, {"summary": "专注块", "dtstart": "2026-09-17T20:00", "duration_minutes": 90})
    e = r.json()["data"]
    assert e["dtend"] == "2026-09-17T21:30:00+08:00"


def test_post_event_dtend_and_duration_both_422(client: TestClient) -> None:
    r = _post(client, {
        "summary": "x", "dtstart": "2026-09-17T20:00",
        "dtend": "2026-09-17T21:00", "duration_minutes": 60,
    })
    assert r.status_code == 422 and "二选一" in r.json()["detail"]


@pytest.mark.parametrize("payload", [
    {"summary": "x", "dtstart": "2026-09-17T20:00", "dtend": "2026-09-17T20:00"},  # 相等
    {"summary": "x", "dtstart": "2026-09-17T20:00", "dtend": "2026-09-17T19:00"},  # 更早
    {"summary": "x", "dtstart": "2026-09-20", "dtend": "2026-09-20", "all_day": True},  # 全天同日=零长
])
def test_post_event_dtend_le_dtstart_422(client: TestClient, payload: dict) -> None:
    r = _post(client, payload)
    assert r.status_code == 422 and "dtend" in r.json()["detail"]


def test_post_event_missing_dtstart_422(client: TestClient) -> None:
    r = _post(client, {"dtstart": "2026-09-17T20:00"})  # summary 缺失 → pydantic 422
    assert r.status_code == 422
    r2 = client.post("/api/events", params={"user": "tester"}, json={"summary": "x"})
    assert r2.status_code == 422 and "dtstart" in r2.json()["detail"]


def test_post_event_unknown_field_422(client: TestClient) -> None:
    r = _post(client, {"summary": "x", "dtstart": "2026-09-17T20:00", "rrule": "FREQ=DAILY"})
    assert r.status_code == 422 and "不接受的字段" in r.json()["detail"]


# ---------------------------------------------------------------- 全天排他语义


def test_post_event_all_day_exclusive_dtend(client: TestClient, tester_dir: Path) -> None:
    """核心契约：排他存储 ↔ 含首尾呈现，一次锁死（SPEC-M2 §2.2）。"""
    r = _post(client, {"summary": "出差", "dtstart": "2026-09-20", "dtend": "2026-09-21", "all_day": True})
    e = r.json()["data"]
    assert e["all_day"] is True
    assert e["dtstart"] == "2026-09-20" and e["dtend"] == "2026-09-21", "API 恒为排他语义"
    raw = _raw(tester_dir)
    assert "DTSTART;VALUE=DATE:20260920" in raw
    assert "DTEND;VALUE=DATE:20260921" in raw
    item = _item_of(_month(client), e["uid"])
    assert item is not None and item["all_day"] is True
    assert item["start_date"] == item["end_date"] == "2026-09-20", "呈现含首尾：单日全天"
    assert item["days_in_month"] == ["2026-09-20"]


def test_post_event_all_day_multiday(client: TestClient) -> None:
    """跨多天全天：9/20 → 9/23（排他）= 呈现 3 天（20/21/22，▣ 横跨）。"""
    r = _post(client, {"summary": "假期", "dtstart": "2026-09-20", "dtend": "2026-09-23", "all_day": True})
    item = _item_of(_month(client), r.json()["data"]["uid"])
    assert item["days_in_month"] == ["2026-09-20", "2026-09-21", "2026-09-22"]
    assert item["start_date"] == "2026-09-20" and item["end_date"] == "2026-09-22"


def test_post_event_all_day_default_dtend_next_day(client: TestClient) -> None:
    r = _post(client, {"summary": "纪念日", "dtstart": "2026-09-25", "all_day": True})
    e = r.json()["data"]
    assert e["dtstart"] == "2026-09-25" and e["dtend"] == "2026-09-26", "全天缺省 → 次日排他"


def test_post_event_all_day_truncates_datetime(client: TestClient, tester_dir: Path) -> None:
    r = _post(client, {"summary": "全天截断", "dtstart": "2026-09-26T08:30", "all_day": True})
    assert r.json()["data"]["dtstart"] == "2026-09-26"
    assert "DTSTART;VALUE=DATE:20260926" in _raw(tester_dir)


# ---------------------------------------------------------------- GET 单条


def test_get_event_detail_and_404(client: TestClient) -> None:
    e = client.get(f"/api/events/{SAMPLE_EVENT}", params={"user": "tester"}).json()
    assert e["uid"] == SAMPLE_EVENT
    assert e["summary"].startswith("系统架构师岗终面")
    assert e["dtstart"] == "2026-09-10T14:00:00+08:00"
    assert e["dtend"] == "2026-09-10T15:30:00+08:00"
    assert len(e["alarms"]) == 1 and e["alarms"][0]["trigger"] == "-PT30M"
    r = client.get("/api/events/no-such@x", params={"user": "tester"})
    assert r.status_code == 404 and "不存在" in r.json()["detail"]


# ---------------------------------------------------------------- PATCH


def test_patch_event_summary_keeps_times_and_alarms(client: TestClient, tester_dir: Path) -> None:
    r = _patch(client, SAMPLE_EVENT, {"summary": "终面(改期确认)"})
    e = r.json()["data"]
    assert e["summary"] == "终面(改期确认)"
    assert e["dtstart"] == "2026-09-10T14:00:00+08:00", "未传字段不动"
    assert len(e["alarms"]) == 1, "VALARM 原样保留（M2 不做提醒编辑）"
    _reparseable(tester_dir)


def test_patch_event_moves_month_bucket(client: TestClient) -> None:
    """改期跨月：9 月聚合消失、10 月聚合出现。"""
    r = _patch(client, SAMPLE_EVENT, {"dtstart": "2026-10-10T14:00", "dtend": "2026-10-10T15:30"})
    assert r.json()["data"]["dtstart"] == "2026-10-10T14:00:00+08:00"
    assert _item_of(_month(client, "2026-09"), SAMPLE_EVENT) is None
    item = _item_of(_month(client, "2026-10"), SAMPLE_EVENT)
    assert item is not None and item["type"] == "event"


def test_patch_event_duration_recomputes_dtend(client: TestClient) -> None:
    r = _patch(client, SAMPLE_EVENT, {"duration_minutes": 120})
    e = r.json()["data"]
    assert e["dtstart"] == "2026-09-10T14:00:00+08:00"
    assert e["dtend"] == "2026-09-10T16:00:00+08:00", "duration 优先，按旧 dtstart 重算"


def test_patch_event_dtend_null_recomputes_default(client: TestClient) -> None:
    r = _patch(client, SAMPLE_EVENT, {"dtend": None})
    assert r.json()["data"]["dtend"] == "2026-09-10T14:30:00+08:00", "清除后按缺省 30 分钟重算"


def test_patch_event_to_all_day_and_back(client: TestClient, tester_dir: Path) -> None:
    e = _patch(client, SAMPLE_EVENT, {"all_day": True}).json()["data"]
    assert e["all_day"] is True and e["dtstart"] == "2026-09-10" and e["dtend"] == "2026-09-11"
    assert "VALUE=DATE:20260910" in _raw(tester_dir)
    e2 = _patch(client, SAMPLE_EVENT, {"all_day": False}).json()["data"]
    assert e2["all_day"] is False
    assert e2["dtstart"] == "2026-09-10T00:00:00+08:00", "全天→定时：提升为上海 00:00"
    assert e2["dtend"] == "2026-09-11T00:00:00+08:00"


def test_patch_event_invalid_dtend_422(client: TestClient) -> None:
    r = _patch(client, SAMPLE_EVENT, {"dtend": "2026-09-10T13:00"})  # 早于 dtstart 14:00
    assert r.status_code == 422 and "dtend" in r.json()["detail"]


def test_patch_event_404(client: TestClient) -> None:
    assert _patch(client, "no-such@x", {"summary": "x"}).status_code == 404


# ---------------------------------------------------------------- DELETE


def test_delete_event_and_todos_intact(client: TestClient, tester_dir: Path) -> None:
    before = _read(tester_dir)
    r = client.delete(f"/api/events/{SAMPLE_EVENT}", params={"user": "tester"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "data": {"deleted": [SAMPLE_EVENT]}}
    after = _read(tester_dir)
    assert after["events"] == []
    assert after["todos"] == before["todos"], "删事件不得扰动待办组件（往返 diff）"
    assert _item_of(_month(client), SAMPLE_EVENT) is None
    _reparseable(tester_dir)
    r2 = client.delete(f"/api/events/{SAMPLE_EVENT}", params={"user": "tester"})
    assert r2.status_code == 404


def test_post_event_roundtrip_diff_todos_intact(client: TestClient, tester_dir: Path) -> None:
    """新增事件后：14 条待办与样例事件逐条字段无损。"""
    before = _read(tester_dir)
    _post(client, {"summary": "新事件", "dtstart": "2026-09-18T10:00", "dtend": "2026-09-18T11:00"})
    after = _read(tester_dir)
    assert after["todos"] == before["todos"]
    sample_before = next(e for e in before["events"] if e["uid"] == SAMPLE_EVENT)
    sample_after = next(e for e in after["events"] if e["uid"] == SAMPLE_EVENT)
    assert sample_after == sample_before
    assert len(after["events"]) == 2
    _reparseable(tester_dir)
