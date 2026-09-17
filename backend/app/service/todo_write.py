"""待办写操作：read-modify-write 事务（SPEC-M2 §2.1 / §3）。

纪律：
- 读 → 内存改 → 写 全程在 mutate_calendar 单事务内完成，不缓存模块全局；
- 校验失败抛 ValidationFailed（422 中文 detail），在写盘之前拦截（文件原样）；
- 写响应 data = 受影响的顶层树节点（对子任务操作返回父节点，进度服务端权威），
  与 GET /api/todos/{uid} 同构；DELETE 例外，返回 {"deleted": [uid...]}。
- 状态变更唯一入口 complete/reopen/abandon（决策 B：PATCH 不接受 status）；
  幂等：已处目标态直接返回当前视图，不落盘不产生备份。
"""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from app.core.contract import (
    DEFAULT_STATUS,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_NEEDS_ACTION,
    TIMEZONE,
)
from app.core.errors import ApiError, NotFound, ValidationFailed
from app.core.uids import new_uid, utc_now
from app.datastore import ics_store
from app.service import todo_service

SH_TZ = ZoneInfo(TIMEZONE)
SUMMARY_MAX = 200

# PATCH 可改字段白名单（status 不在其中——决策 B，schema 层 extra=forbid 双保险）
EDITABLE_FIELDS = (
    "summary",
    "description",
    "important",
    "urgent",
    "due",
    "dtstart",
    "duration_minutes",
    "all_day",
    "categories",
    "parent_uid",
)


# ---------------------------------------------------------------- 时间解析


def parse_user_dt(s: str | None, field: str):
    """用户时间输入 → date（10 位纯日期）或 aware datetime（决策 #4）。

    - ISO 8601：YYYY-MM-DD 或 datetime（可带时区偏移/Z）；
    - 无时区按 Asia/Shanghai 解释，带时区折算到 Asia/Shanghai；
    - 解析失败 → 422 中文 detail。
    严禁复用 todo_service._parse_dt（它把 naive 当 UTC，仅 overdue 视图专用）。
    """
    if s is None:
        return None
    text = str(s).strip()
    if not text:
        return None
    try:
        if len(text) == 10:
            return date.fromisoformat(text)
        value = datetime.fromisoformat(text)
    except ValueError as e:
        raise ValidationFailed(f"{field} 时间格式非法（需 ISO 8601）：{text}") from e
    if value.tzinfo is None:
        return value.replace(tzinfo=SH_TZ)
    return value.astimezone(SH_TZ)


def as_time_value(v):
    """领域 dict 时间值（ISO str）或已解析 date/datetime → date/datetime/None。"""
    if v is None or isinstance(v, (date, datetime)):
        return v
    return parse_user_dt(str(v), "时间")


def _iso(v) -> str | None:
    """date/datetime → ISO 字符串（领域 dict 内的统一形态）；None 原样。"""
    return v.isoformat() if v is not None else None


def _validate_time_combo(dtstart, due, duration) -> None:
    """时间组合校验（SPEC-M2 §2.1）：duration 与 dtstart 成对；due >= dtstart。

    入参为已解析的 date/datetime/None（date 按当天 00:00 Asia/Shanghai 参与比较）。
    """
    if duration is not None:
        if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
            raise ValidationFailed("duration_minutes 必须是正整数")
        if dtstart is None:
            raise ValidationFailed("duration_minutes 必须与 dtstart 成对（只有时长没有开始时间不行）")
    if dtstart is not None and due is not None:
        s = dtstart if isinstance(dtstart, datetime) else datetime.combine(dtstart, time.min, tzinfo=SH_TZ)
        d = due if isinstance(due, datetime) else datetime.combine(due, time.min, tzinfo=SH_TZ)
        if d < s:
            raise ValidationFailed("due 不能早于 dtstart")


def clean_summary(value) -> str:
    """summary 去空白后非空且 ≤200（SPEC-M2 §2.1 校验规则）。"""
    s = str(value or "").strip()
    if not s:
        raise ValidationFailed("summary 不能为空")
    if len(s) > SUMMARY_MAX:
        raise ValidationFailed(f"summary 过长（≤{SUMMARY_MAX} 字）：当前 {len(s)} 字")
    return s


def _validate_parent(todos: list[dict], parent_uid: str | None, self_uid: str | None) -> str | None:
    """父任务校验（SPEC-M2 §2.1）：存在、非自己、默认两级（防环由两级约束覆盖）。

    两级 = 父必须顶层（自己无父）且自己名下无子任务：
    - 把 X 挂到"已是子任务的 P"下 → P 有父 → 422（孙辈禁止）；
    - 把"有子任务的 X"挂到别人下 → 422；
    - 把 X 挂到 X 的子任务下 → 子任务有父 → 422（环被拦截）。
    """
    if not parent_uid:
        return None
    if self_uid is not None and parent_uid == self_uid:
        raise ValidationFailed("parent_uid 不能是自己")
    by_uid = {t.get("uid"): t for t in todos}
    parent = by_uid.get(parent_uid)
    if parent is None:
        raise ValidationFailed(f"父任务不存在: {parent_uid}")
    if parent.get("parent_uid"):
        raise ValidationFailed("父任务本身已是子任务：默认两级，不能再挂孙任务")
    if self_uid is not None and any(t.get("parent_uid") == self_uid for t in todos):
        raise ValidationFailed("该待办名下已有子任务：默认两级，不能再挂为别人的子任务")
    return parent_uid


# ---------------------------------------------------------------- 查询辅助


def _find_todo(todos: list[dict], uid: str) -> dict:
    for t in todos:
        if t.get("uid") == uid:
            return t
    raise NotFound(f"待办不存在: {uid}")


def _affected_top_node(todos: list[dict], uid: str) -> dict:
    """写响应视图：受影响的顶层树节点（子任务 → 其父节点），与 GET 单条同构。"""
    for node in todo_service.build_tree(todos):
        if node["uid"] == uid:
            return node
        for child in node.get("children", []):
            if child["uid"] == uid:
                return node
    raise NotFound(f"待办不存在: {uid}")


# ---------------------------------------------------------------- 写事务


def create_todo(base_dir: Path, payload: dict) -> dict:
    """新建待办（POST /api/todos）→ 受影响的顶层树节点。

    服务端生成 uid/dtstamp/created（SPEC-M2 §2.1）；uid 冲突（理论不该发生）
    → 500 且旧文件保留（校验在写盘前拦截）。
    """
    summary = clean_summary(payload.get("summary"))
    all_day = bool(payload.get("all_day"))
    dtstart = parse_user_dt(payload.get("dtstart"), "dtstart")
    due = parse_user_dt(payload.get("due"), "due")
    duration = payload.get("duration_minutes")
    if all_day:
        # 全天：datetime 截断为 date（落盘 VALUE=DATE，决策 #4）
        dtstart = dtstart.date() if isinstance(dtstart, datetime) else dtstart
        due = due.date() if isinstance(due, datetime) else due
    _validate_time_combo(dtstart, due, duration)

    now_iso = utc_now().isoformat()
    todo = {
        "uid": new_uid(),
        "dtstamp": now_iso,
        "summary": summary,
        "description": payload.get("description") or "",
        "status": DEFAULT_STATUS,
        "priority": None,
        "categories": [str(c) for c in (payload.get("categories") or [])],
        "important": bool(payload.get("important")),
        "urgent": bool(payload.get("urgent")),
        "dtstart": _iso(dtstart),
        "all_day": all_day,
        "due": _iso(due),
        "duration_minutes": int(duration) if duration is not None else None,
        "completed": None,
        "created": now_iso,
        "parent_uid": payload.get("parent_uid") or None,
    }

    def _mut(todos: list[dict], events: list[dict]) -> None:
        todo["parent_uid"] = _validate_parent(todos, todo["parent_uid"], None)
        if any(t.get("uid") == todo["uid"] for t in todos):
            raise ApiError(f"UID 冲突（理论不该发生）：{todo['uid']}，旧文件已保留", 500)
        todos.append(todo)

    data = ics_store.mutate_calendar(base_dir, _mut)
    return _affected_top_node(data["todos"], todo["uid"])


def update_todo(base_dir: Path, uid: str, patch: dict) -> dict:
    """局部更新（PATCH /api/todos/{uid}）→ 受影响的顶层树节点。

    patch = model_dump(exclude_unset=True)：没传的字段不动，显式 None = 清除。
    status 不在白名单（决策 B，schema extra=forbid 已在入口拦截）。
    """
    patch = {k: v for k, v in patch.items() if k in EDITABLE_FIELDS}
    if "summary" in patch:
        patch["summary"] = clean_summary(patch["summary"])
    if "duration_minutes" in patch and patch["duration_minutes"] is not None:
        dur = patch["duration_minutes"]
        if not isinstance(dur, int) or isinstance(dur, bool) or dur <= 0:
            raise ValidationFailed("duration_minutes 必须是正整数")
    if "categories" in patch and patch["categories"] is not None:
        patch["categories"] = [str(c) for c in patch["categories"]]
    if not patch:
        # 无有效字段：不落盘，返回当前视图（404 检查仍执行）
        cal = ics_store.read_calendar(base_dir)
        _find_todo(cal["todos"], uid)
        return _affected_top_node(cal["todos"], uid)

    def _mut(todos: list[dict], events: list[dict]) -> None:
        target = _find_todo(todos, uid)
        if "parent_uid" in patch:
            patch["parent_uid"] = _validate_parent(todos, patch["parent_uid"], uid)
        for k, v in patch.items():
            target[k] = v
        # 时间字段归一：all_day=True 截断为 date；统一存 ISO 字符串
        if target.get("all_day"):
            for k in ("dtstart", "due"):
                v = as_time_value(target.get(k))
                if isinstance(v, datetime):
                    target[k] = v.date().isoformat()
        for k in ("dtstart", "due"):
            v = target.get(k)
            if isinstance(v, (date, datetime)):
                target[k] = v.isoformat()
        _validate_time_combo(
            as_time_value(target.get("dtstart")),
            as_time_value(target.get("due")),
            target.get("duration_minutes"),
        )
        target["dtstamp"] = utc_now().isoformat()  # RFC 5545：修改须刷新 DTSTAMP

    data = ics_store.mutate_calendar(base_dir, _mut)
    return _affected_top_node(data["todos"], uid)


def change_status(base_dir: Path, uid: str, action: str) -> dict:
    """完成/放弃/恢复（SPEC-M2 决策 #1 补充语义）→ 受影响的顶层树节点。

    - complete：STATUS:COMPLETED + COMPLETED:<UTC>（幂等：时间戳不重写）；
    - abandon：STATUS:CANCELLED（清 COMPLETED——放弃不是完成）；
    - reopen：翻回 NEEDS-ACTION 并移除 COMPLETED（兼作放弃项的恢复入口）。
    已处目标态 → 幂等短路：不落盘、不产生备份。
    """
    # 幂等短路 + 404 前置检查
    cal = ics_store.read_calendar(base_dir)
    current = (_find_todo(cal["todos"], uid).get("status") or DEFAULT_STATUS).upper()
    if action == "complete" and current == STATUS_COMPLETED:
        return _affected_top_node(cal["todos"], uid)
    if action == "abandon" and current == STATUS_CANCELLED:
        return _affected_top_node(cal["todos"], uid)
    if action == "reopen" and current not in (STATUS_COMPLETED, STATUS_CANCELLED):
        return _affected_top_node(cal["todos"], uid)

    def _mut(todos: list[dict], events: list[dict]) -> None:
        t = _find_todo(todos, uid)
        now_iso = utc_now().isoformat()
        if action == "complete":
            t["status"] = STATUS_COMPLETED
            if not t.get("completed"):
                t["completed"] = now_iso
        elif action == "abandon":
            t["status"] = STATUS_CANCELLED
            t["completed"] = None
        else:  # reopen
            t["status"] = STATUS_NEEDS_ACTION
            t["completed"] = None
        t["dtstamp"] = now_iso

    data = ics_store.mutate_calendar(base_dir, _mut)
    return _affected_top_node(data["todos"], uid)


def delete_todo(base_dir: Path, uid: str) -> dict:
    """物理删除（DELETE /api/todos/{uid}）→ {"deleted": [uid...]}。

    决策 C：级联删除全部子任务（默认两级，子任务即叶子）。
    删除 = 从 ics 移除组件（区别于放弃）；写前备份仍在 .backup/ 可找回。
    """
    deleted: list[str] = []

    def _mut(todos: list[dict], events: list[dict]) -> None:
        _find_todo(todos, uid)  # 404 检查（写盘前）
        deleted.extend([uid] + [t["uid"] for t in todos if t.get("parent_uid") == uid and t.get("uid") != uid])
        for t in list(todos):
            if t.get("uid") in deleted:
                todos.remove(t)

    ics_store.mutate_calendar(base_dir, _mut)
    return {"deleted": deleted}
