"""待办业务逻辑：四象限归位、时间三阶段、父子任务树、过滤、逾期判断。

全部为纯函数（dict in / dict out），不碰文件系统，便于单测。
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.contract import (
    Q1,
    Q2,
    Q3,
    Q4,
    STAGE_BLOCK,
    STAGE_BOTH,
    STAGE_DUE,
    STAGE_UNSCHEDULED,
    STATUS_COMPLETED,
)


def classify(todo: dict) -> str:
    """四象限 = important × urgent 现算（与有无时间正交）。"""
    imp = bool(todo.get("important"))
    urg = bool(todo.get("urgent"))
    if imp and urg:
        return Q1
    if imp:
        return Q2
    if urg:
        return Q3
    return Q4


def time_stage(todo: dict) -> str:
    """时间三阶段：执行块 = DTSTART+DURATION（缺一不可），DUE 可并存。"""
    has_block = bool(todo.get("dtstart")) and todo.get("duration_minutes") is not None
    has_due = bool(todo.get("due"))
    if has_block and has_due:
        return STAGE_BOTH
    if has_block:
        return STAGE_BLOCK
    if has_due:
        return STAGE_DUE
    return STAGE_UNSCHEDULED


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def is_overdue(todo: dict, now: datetime | None = None) -> bool:
    """已逾期 = 未完成且有 DUE 且 DUE 早于当前时间。"""
    if todo.get("status") == STATUS_COMPLETED:
        return False
    due = _parse_dt(todo.get("due"))
    if due is None:
        return False
    now = now or datetime.now(timezone.utc)
    return due < now


def enrich(todo: dict, now: datetime | None = None) -> dict:
    """补充派生字段：quadrant / has_time / overdue（不修改原 dict）。"""
    out = dict(todo)
    out["quadrant"] = classify(todo)
    out["has_time"] = time_stage(todo)
    out["overdue"] = is_overdue(todo, now)
    return out


def build_tree(todos: list[dict], now: datetime | None = None) -> list[dict]:
    """构建父子树（默认两级）：子任务挂到父的 children[]，父带进度。

    - 父任务进度 = 子任务完成率；无子任务 progress=None。
    - 孤儿（parent_uid 指向不存在的任务）提升为顶层，避免数据丢失。
    - 孙辈（子任务再被引用）不展开，防止超过两级。
    返回顶层任务列表（保持原顺序），每个节点（含 children 内）均已 enrich。
    """
    by_uid = {t["uid"]: t for t in todos if t.get("uid")}
    child_uids = {
        t["uid"]
        for t in todos
        if t.get("parent_uid") and t["parent_uid"] in by_uid and t["parent_uid"] != t.get("uid")
    }
    top: list[dict] = []
    for t in todos:
        if t["uid"] in child_uids:
            continue
        node = enrich(t, now)
        children = [
            enrich(c, now) for c in todos if c.get("parent_uid") == t.get("uid") and c["uid"] in child_uids
        ]
        node["children"] = children
        node["children_total"] = len(children)
        node["children_done"] = sum(1 for c in children if c.get("status") == STATUS_COMPLETED)
        node["progress"] = (node["children_done"] / len(children)) if children else None
        top.append(node)
    return top


def filter_todos(
    todos: list[dict],
    view: str | None = None,
    unscheduled: bool = False,
    status: str | None = None,
) -> list[dict]:
    """按查询参数过滤（view 仅语义区分，分组由前端完成）。

    - unscheduled：只保留未排期（无 DTSTART+DURATION 且无 DUE）。
    - status：按 VTODO STATUS 精确过滤。
    """
    out = todos
    if unscheduled:
        out = [t for t in out if time_stage(t) == STAGE_UNSCHEDULED]
    if status:
        wanted = status.upper()
        out = [t for t in out if (t.get("status") or "").upper() == wanted]
    return out
