"""datastore.ics_store 测试：解析 + 写回往返 + M2 安全写闸门。

关键校验（CLAUDE.md 质量要求 + SPEC-M2 §3）：
- 写出的 .ics 必须能被 icalendar 库重新解析；
- 中文 SUMMARY/DESCRIPTION 往返后字段等值；
- 时间三阶段、四象限标签、父子任务解析正确；
- M2：头部保真（METHOD:PUBLISH）、往返 diff（改一条其余无损）、
  回读失败恢复（旧文件字节不变）、写前备份滚动。
"""

import copy
from pathlib import Path

import pytest
from icalendar import Calendar

from app.datastore import ics_store
from app.datastore.atomic import AtomicWriteError

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


# ---------------------------------------------------------------- M2：安全写闸门


def test_write_calendar_header_fidelity(me_snapshot_dir: Path) -> None:
    """头部保真：真实 me 文件（含 METHOD:PUBLISH）写回后头部属性不丢。"""
    data = ics_store.read_calendar(me_snapshot_dir)
    ics_store.write_calendar(me_snapshot_dir, data)
    raw = (me_snapshot_dir / ics_store.ICS_FILENAME).read_text(encoding="utf-8")
    for prop in (
        "METHOD:PUBLISH",
        "PRODID:-//Personal Workbench//Open Data Layer//CN",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
    ):
        assert prop in raw, f"头部属性丢失: {prop}"


def test_write_calendar_default_header_for_new_file(tmp_path: Path) -> None:
    """首写（无旧文件）：默认头与 data-samples 一致（含 METHOD:PUBLISH）。"""
    path = ics_store.write_calendar(tmp_path, {"todos": [], "events": []})
    raw = path.read_text(encoding="utf-8")
    assert "VERSION:2.0" in raw and "METHOD:PUBLISH" in raw
    assert "PRODID:-//Personal Workbench//Open Data Layer//CN" in raw


def test_write_calendar_roundtrip_diff_untouched(me_snapshot_dir: Path) -> None:
    """往返 diff（SPEC-M2 §3）：只改一条，其余组件逐字段无损。

    fixture = me 的 M1 快照（5 条真实待办，1 父 2 子）。
    """
    before = ics_store.read_calendar(me_snapshot_dir)
    data = copy.deepcopy(before)
    target = data["todos"][1]  # 第 2 条（学习Claude Code）
    target["summary"] = "改过的摘要"
    target["due"] = "2026-10-01T09:00:00+08:00"
    ics_store.write_calendar(me_snapshot_dir, data)
    after = ics_store.read_calendar(me_snapshot_dir)

    # uid 集合不变
    assert {t["uid"] for t in after["todos"]} == {t["uid"] for t in before["todos"]}
    # 被改条：summary/due 更新，其余 14 个字段不变
    changed = next(t for t in after["todos"] if t["uid"] == target["uid"])
    assert changed["summary"] == "改过的摘要"
    assert changed["due"] == "2026-10-01T09:00:00+08:00"
    for k, v in before["todos"][1].items():
        if k in ("summary", "due"):
            continue
        assert changed[k] == v, f"字段 {k} 意外变化: {changed[k]!r} != {v!r}"
    # 其余 4 条逐条 dict 全等
    for b in before["todos"]:
        if b["uid"] == target["uid"]:
            continue
        a = next(t for t in after["todos"] if t["uid"] == b["uid"])
        assert a == b, f"未修改组件字段丢失: {b['uid']}"
    assert after["events"] == before["events"]
    # 父子关系保真：RELATED-TO;RELTYPE=CHILD 原文仍在
    raw = (me_snapshot_dir / ics_store.ICS_FILENAME).read_text(encoding="utf-8")
    assert raw.count("RELTYPE=CHILD") == 2


def test_write_calendar_creates_rolling_backup(me_snapshot_dir: Path) -> None:
    data = ics_store.read_calendar(me_snapshot_dir)
    bak = me_snapshot_dir / ".backup"
    assert not bak.exists(), "首写前无备份目录"
    ics_store.write_calendar(me_snapshot_dir, data)
    assert len(list(bak.glob("calendar-*.ics"))) == 1
    ics_store.write_calendar(me_snapshot_dir, data)
    assert len(list(bak.glob("calendar-*.ics"))) == 2


def test_write_calendar_verify_failure_recovers(
    me_snapshot_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回读闸门：序列化损坏 → AtomicWriteError，旧文件字节不变、备份保留。"""
    original = (me_snapshot_dir / ics_store.ICS_FILENAME).read_bytes()
    data = ics_store.read_calendar(me_snapshot_dir)
    # 注入点：模块级 _serialize_calendar 产出非法字节
    monkeypatch.setattr(ics_store, "_serialize_calendar", lambda *a, **kw: b"BROKEN NOT-ICS")
    with pytest.raises(AtomicWriteError):
        ics_store.write_calendar(me_snapshot_dir, data)
    assert (me_snapshot_dir / ics_store.ICS_FILENAME).read_bytes() == original
    assert len(list((me_snapshot_dir / ".backup").glob("calendar-*.ics"))) == 1


def test_write_calendar_no_tmp_leftover(me_snapshot_dir: Path) -> None:
    ics_store.write_calendar(me_snapshot_dir, ics_store.read_calendar(me_snapshot_dir))
    assert list(me_snapshot_dir.glob("*.tmp")) == []
