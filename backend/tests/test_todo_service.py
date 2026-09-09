"""service.todo_service 测试：象限归位、三阶段、父子树与进度、过滤、逾期。"""

from datetime import datetime, timezone
from pathlib import Path

from app.datastore import ics_store
from app.service import todo_service

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = REPO_ROOT / "data-samples"
NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def _samples() -> list[dict]:
    return ics_store.read_calendar(SAMPLES)["todos"]


def _todo(todos: list[dict], uid_part: str) -> dict:
    hits = [t for t in todos if uid_part in t["uid"]]
    assert len(hits) == 1
    return hits[0]


def test_classify_four_quadrants() -> None:
    assert todo_service.classify({"important": True, "urgent": True}) == "q1"
    assert todo_service.classify({"important": True, "urgent": False}) == "q2"
    assert todo_service.classify({"important": False, "urgent": True}) == "q3"
    assert todo_service.classify({"important": False, "urgent": False}) == "q4"
    # 缺失标签容错 → q4
    assert todo_service.classify({}) == "q4"


def test_time_stage() -> None:
    todos = _samples()
    assert todo_service.time_stage(_todo(todos, "timeline-backfill")) == "unscheduled"
    assert todo_service.time_stage(_todo(todos, "pay-insurance")) == "due"
    assert todo_service.time_stage(_todo(todos, "move-pack")) == "block"
    assert todo_service.time_stage(_todo(todos, "arch-review")) == "both"
    # DTSTART 无 DURATION 不算执行块（有 DUE → due）
    assert todo_service.time_stage(_todo(todos, "resume-v2")) == "due"


def test_build_tree_progress() -> None:
    tree = todo_service.build_tree(_samples(), NOW)
    # 14 条 - 3 子 = 11 个顶层
    assert len(tree) == 11
    parent = next(n for n in tree if "q3-review-parent" in n["uid"])
    assert parent["children_total"] == 3
    assert parent["children_done"] == 2
    assert abs(parent["progress"] - 2 / 3) < 1e-9
    # 派生字段就位
    assert parent["quadrant"] == "q1"
    child = parent["children"][0]
    assert "quadrant" in child and "overdue" in child


def test_orphan_child_promoted_to_top() -> None:
    todos = _samples() + [{
        "uid": "orphan@workbench.local", "summary": "孤儿", "parent_uid": "not-exist",
        "status": "NEEDS-ACTION", "important": False, "urgent": False,
    }]
    tree = todo_service.build_tree(todos, NOW)
    assert any(n["uid"] == "orphan@workbench.local" for n in tree)


def test_self_reference_not_child_of_itself() -> None:
    todos = [{"uid": "a", "summary": "自引用", "parent_uid": "a", "status": "NEEDS-ACTION"}]
    tree = todo_service.build_tree(todos)
    assert len(tree) == 1 and tree[0]["children"] == []


def test_filter_unscheduled_and_status() -> None:
    todos = _samples()
    unscheduled = todo_service.filter_todos(todos, unscheduled=True)
    assert len(unscheduled) == 7  # 与 validate.py 覆盖统计一致
    completed = todo_service.filter_todos(todos, status="completed")
    assert len(completed) == 2
    assert todo_service.filter_todos(todos, status="needs-action")
    assert len(todo_service.filter_todos([], unscheduled=True)) == 0


def test_overdue() -> None:
    todos = _samples()
    # DUE 9/1 已过（NOW=9/4）→ 逾期
    assert todo_service.is_overdue(_todo(todos, "car-inspection"), NOW) is True
    # DUE 9/15 未到
    assert todo_service.is_overdue(_todo(todos, "pay-insurance"), NOW) is False
    # 已完成不算逾期
    assert todo_service.is_overdue(_todo(todos, "q3-review-child1"), NOW) is False
    # 无 DUE 不算
    assert todo_service.is_overdue(_todo(todos, "timeline-backfill"), NOW) is False


def test_enrich_fields() -> None:
    e = todo_service.enrich(_todo(_samples(), "arch-review"), NOW)
    assert e["quadrant"] == "q2"  # 重要不紧急
    assert e["has_time"] == "both"
    assert e["overdue"] is False
