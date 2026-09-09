"""service.calendar_service 测试：月聚合、跨月裁剪、午夜终点、全天排他语义。"""

from pathlib import Path

from app.datastore import ics_store
from app.service import calendar_service

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = REPO_ROOT / "data-samples"


def _samples_data() -> dict:
    return ics_store.read_calendar(SAMPLES)


def test_september_aggregate() -> None:
    data = _samples_data()
    items = calendar_service.month_items(data["events"], data["todos"], 2026, 9)
    types = [i["type"] for i in items]
    assert types.count("event") == 1   # 面试
    assert types.count("block") == 2   # 架构评审块 + 搬家全天块
    assert types.count("due") == 6     # 简历/社保/年检/评审截止/子2/子3
    # 无时间待办（含父任务与子任务1）不上日历
    uids = " ".join(i["uid"] for i in items)
    assert "timeline-backfill" not in uids
    assert "q3-review-parent" not in uids


def test_block_days_and_times() -> None:
    data = _samples_data()
    items = calendar_service.month_items(data["events"], data["todos"], 2026, 9)
    block = next(i for i in items if i["type"] == "block" and "arch-review" in i["uid"])
    # 9/8 09:00 + P3D → 9/11 09:00 结束：触及 8/9/10/11 四天（含部分日的渲染语义）
    assert block["days_in_month"] == [
        "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11",
    ]
    assert block["end_date"] == "2026-09-11"
    assert block["start_time"] == "09:00"
    assert block["all_day"] is False


def test_all_day_block() -> None:
    data = _samples_data()
    items = calendar_service.month_items(data["events"], data["todos"], 2026, 9)
    move = next(i for i in items if "move-pack" in i["uid"])
    assert move["all_day"] is True
    assert move["days_in_month"] == ["2026-09-20", "2026-09-21"]


def test_event_times() -> None:
    data = _samples_data()
    items = calendar_service.month_items(data["events"], data["todos"], 2026, 9)
    ev = next(i for i in items if i["type"] == "event")
    assert ev["days_in_month"] == ["2026-09-10"]
    assert ev["start_time"] == "14:00" and ev["end_time"] == "15:30"


def test_cross_month_block_clipped() -> None:
    todos = [{
        "uid": "x", "summary": "跨月块", "dtstart": "2026-08-30T09:00:00+08:00",
        "duration_minutes": 4 * 1440, "all_day": False, "categories": [],
    }]
    items = calendar_service.month_items([], todos, 2026, 9)
    assert len(items) == 1
    item = items[0]
    assert item["start_date"] == "2026-08-30"          # 完整跨度保留
    assert item["end_date"] == "2026-09-03"            # 8/30 09:00 + 4天 → 9/3 09:00 止
    assert item["days_in_month"] == ["2026-09-01", "2026-09-02", "2026-09-03"]  # 裁剪到本月


def test_midnight_end_excluded() -> None:
    events = [{
        "uid": "e", "summary": "午夜终点", "dtstart": "2026-09-10T14:00:00+08:00",
        "dtend": "2026-09-11T00:00:00+08:00", "all_day": False, "categories": [],
    }]
    items = calendar_service.month_items(events, [], 2026, 9)
    assert items[0]["end_date"] == "2026-09-10"
    assert items[0]["days_in_month"] == ["2026-09-10"]


def test_allday_event_end_exclusive() -> None:
    events = [{
        "uid": "e", "summary": "全天多日", "dtstart": "2026-09-05",
        "dtend": "2026-09-08", "all_day": True, "categories": [],
    }]
    items = calendar_service.month_items(events, [], 2026, 9)
    assert items[0]["days_in_month"] == ["2026-09-05", "2026-09-06", "2026-09-07"]


def test_outside_month_and_empty() -> None:
    todos = [{"uid": "x", "summary": "别的月", "due": "2026-10-01T18:00:00+08:00", "categories": []}]
    assert calendar_service.month_items([], todos, 2026, 9) == []
    assert calendar_service.month_items([], [], 2026, 9) == []
