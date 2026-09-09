"""datastore.ics_store 测试：解析 + 写回往返。

关键校验（CLAUDE.md 质量要求）：
- 写出的 .ics 必须能被 icalendar 库重新解析；
- 中文 SUMMARY/DESCRIPTION 往返后字段等值；
- 时间三阶段、四象限标签、父子任务解析正确。
"""

from pathlib import Path

from icalendar import Calendar

from app.datastore import ics_store

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = REPO_ROOT / "data-samples"


def _read_samples() -> dict:
    return ics_store.read_calendar(SAMPLES)


def _todo_by_uid(data: dict, uid_part: str) -> dict:
    hits = [t for t in data["todos"] if uid_part in t["uid"]]
    assert len(hits) == 1, f"按 {uid_part} 未找到唯一待办"
    return hits[0]


# ---------------------------------------------------------------- 解析


def test_read_samples_counts() -> None:
    data = _read_samples()
    assert len(data["todos"]) == 14
    assert len(data["events"]) == 1


def test_quadrant_flags() -> None:
    data = _read_samples()
    resume = _todo_by_uid(data, "task-resume-v2")
    assert resume["important"] is True and resume["urgent"] is True
    book = _todo_by_uid(data, "task-read-book")
    assert book["important"] is False and book["urgent"] is False
    assert book["priority"] == 9
    assert "个人成长" in book["categories"]


def test_time_stages() -> None:
    data = _read_samples()
    # 仅 DUE
    insurance = _todo_by_uid(data, "task-pay-insurance")
    assert insurance["due"] and insurance["dtstart"] is None
    # 执行块 + DUE 并存
    review = _todo_by_uid(data, "task-arch-review")
    assert review["dtstart"] and review["due"] and review["duration_minutes"] == 3 * 1440
    # 全天执行块（VALUE=DATE）
    move = _todo_by_uid(data, "task-move-pack")
    assert move["all_day"] is True
    assert move["dtstart"] == "2026-09-20"
    assert move["duration_minutes"] == 2 * 1440
    # 未排期（无时间）
    backfill = _todo_by_uid(data, "task-timeline-backfill")
    assert backfill["dtstart"] is None and backfill["due"] is None


def test_timezone_convention() -> None:
    data = _read_samples()
    review = _todo_by_uid(data, "task-arch-review")
    assert review["dtstart"].endswith("+08:00"), "本地时间必须带 Asia/Shanghai 偏移"
    assert review["dtstamp"].endswith("+00:00"), "DTSTAMP 应为 UTC"


def test_parent_child() -> None:
    data = _read_samples()
    parent = _todo_by_uid(data, "q3-review-parent")
    children = [t for t in data["todos"] if t["parent_uid"] == parent["uid"]]
    assert len(children) == 3
    done = [c for c in children if c["status"] == "COMPLETED"]
    assert len(done) == 2  # 父任务进度 2/3 的数据基础


def test_event_parsed() -> None:
    data = _read_samples()
    ev = data["events"][0]
    assert ev["summary"].startswith("系统架构师岗终面")
    assert ev["dtstart"] == "2026-09-10T14:00:00+08:00"
    assert ev["dtend"] == "2026-09-10T15:30:00+08:00"
    assert ev["all_day"] is False
    assert len(ev["alarms"]) == 1 and ev["alarms"][0]["trigger"] == "-PT30M"


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    assert ics_store.read_calendar(tmp_path) == {"todos": [], "events": []}


def test_empty_file_returns_empty(tmp_path: Path) -> None:
    # 空文件（如误操作清空）视为无数据，不得 500
    (tmp_path / ics_store.ICS_FILENAME).write_text("", encoding="utf-8")
    assert ics_store.read_calendar(tmp_path) == {"todos": [], "events": []}
    (tmp_path / ics_store.ICS_FILENAME).write_text("   \n  ", encoding="utf-8")
    assert ics_store.read_calendar(tmp_path) == {"todos": [], "events": []}


# ---------------------------------------------------------------- 往返


def test_written_ics_reparseable(tmp_path: Path) -> None:
    """核心要求：写出的 .ics 必须能被 icalendar 重新解析。"""
    data = _read_samples()
    path = ics_store.write_calendar(tmp_path, data)
    cal = Calendar.from_ical(path.read_text(encoding="utf-8"))
    assert len(list(cal.walk("VTODO"))) == 14
    assert len(list(cal.walk("VEVENT"))) == 1
    # 关键约定写回了：RELATED-TO;RELTYPE=CHILD、TZID、X- 标签
    raw = path.read_text(encoding="utf-8")
    assert "RELTYPE=CHILD" in raw
    assert "TZID=Asia/Shanghai" in raw
    assert "X-IMPORTANT:TRUE" in raw


def test_roundtrip_no_field_loss(tmp_path: Path) -> None:
    data = _read_samples()
    ics_store.write_calendar(tmp_path, data)
    reread = ics_store.read_calendar(tmp_path)
    assert reread["todos"] == data["todos"]
    assert reread["events"] == data["events"]


def test_chinese_roundtrip(tmp_path: Path) -> None:
    """中文含逗号/冒号的字段写回后不得丢字。"""
    todo = {
        "uid": "test-cn-1@workbench.local",
        "dtstamp": "2026-09-04T01:00:00+00:00",
        "summary": "中文标题:含冒号,逗号、括号(验证转义)",
        "description": "描述里的逗号,要转义;分号也要注意。参照 工作经验梳理.md",
        "status": "NEEDS-ACTION",
        "priority": 1,
        "categories": ["工作", "重要紧急"],
        "important": True,
        "urgent": False,
        "dtstart": "2026-09-05T09:00:00+08:00",
        "all_day": False,
        "due": "2026-09-06T18:00:00+08:00",
        "duration_minutes": 120,
        "completed": None,
        "created": None,
        "parent_uid": None,
    }
    ics_store.write_calendar(tmp_path, {"todos": [todo], "events": []})
    reread = ics_store.read_calendar(tmp_path)
    assert reread["todos"][0] == todo
