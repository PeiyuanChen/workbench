"""事件写操作：read-modify-write 事务（SPEC-M2 §2.2）。

语义约定：
- API 的 dtend 恒为 RFC 5545 排他语义（GET/POST 对称，后端不做 ±1 天）；
  前端选择器呈现含首尾、提交时 +1 天（转换在前端，专项测试覆盖）。
- dtend 与 duration_minutes 二选一：都给 → 422；都缺省 → 定时事件默认
  dtstart+30 分钟、全天事件默认 dtstart+1 天（排他）；duration 换算为
  dtend 存储（与 ics_store._build_event 只写 DTEND 的现状一致）。
- 全天事件两端为纯日期（落盘 VALUE=DATE）；纯日期输入即视为全天。
- VALARM 原样保留（M2 不做提醒编辑，SPEC-M2 §6）。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.core.contract import TIMEZONE
from app.core.errors import ApiError, NotFound, ValidationFailed
from app.core.uids import new_uid, utc_now
from app.datastore import ics_store
from app.service.todo_write import as_time_value, clean_summary, parse_user_dt

SH_TZ = ZoneInfo(TIMEZONE)
# dtend/duration 都缺省时的默认定时事件时长（SPEC-M2 §2.2）
DEFAULT_EVENT_MINUTES = 30

# PATCH 可改字段白名单（alarms/status 不在其中——M2 不做提醒编辑）
EDITABLE_EVENT_FIELDS = (
    "summary",
    "dtstart",
    "dtend",
    "duration_minutes",
    "location",
    "description",
    "categories",
    "all_day",
)


def _find_event(events: list[dict], uid: str) -> dict:
    for e in events:
        if e.get("uid") == uid:
            return e
    raise NotFound(f"事件不存在: {uid}")


def _is_pure_date(v) -> bool:
    return isinstance(v, date) and not isinstance(v, datetime)


def normalize_event_times(dtstart, dtend, duration, all_day: bool):
    """校验并归一事件时间 → (dtstart, dtend)，见模块 docstring 语义约定。

    入参为已解析的 date/datetime（dtstart 非 None）/None。
    """
    if dtend is not None and duration is not None:
        raise ValidationFailed("dtend 与 duration_minutes 二选一，不能同时提供")
    if duration is not None and (
        not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0
    ):
        raise ValidationFailed("duration_minutes 必须是正整数")
    if all_day:
        # 全天：两端截断为纯日期（落盘 VALUE=DATE）
        dtstart = dtstart.date() if isinstance(dtstart, datetime) else dtstart
        dtend = dtend.date() if isinstance(dtend, datetime) else dtend
    if dtend is None:
        if duration is not None:
            dtend = dtstart + timedelta(minutes=duration)
        elif all_day or _is_pure_date(dtstart):
            dtend = dtstart + timedelta(days=1)  # 单日全天事件：排他终点 = 次日
        else:
            dtend = dtstart + timedelta(minutes=DEFAULT_EVENT_MINUTES)
    if dtend <= dtstart:
        raise ValidationFailed("dtend 必须晚于 dtstart（全天事件按排他日语义）")
    return dtstart, dtend


def _to_midnight(v):
    """全天 → 定时：纯日期提升为 Asia/Shanghai 当天 00:00。"""
    return datetime.combine(v, time.min, tzinfo=SH_TZ) if _is_pure_date(v) else v


def get_event(base_dir: Path, uid: str) -> dict:
    """单条事件（编辑表单数据源：含 description/location/alarms/dtend）。"""
    cal = ics_store.read_calendar(base_dir)
    return _find_event(cal["events"], uid)


def create_event(base_dir: Path, payload: dict) -> dict:
    """新建事件（POST /api/events）→ 事件领域 dict（以落盘重读为准）。"""
    summary = clean_summary(payload.get("summary"))
    all_day = bool(payload.get("all_day"))
    dtstart = parse_user_dt(payload.get("dtstart"), "dtstart")
    if dtstart is None:
        raise ValidationFailed("dtstart 不能为空")
    dtend = parse_user_dt(payload.get("dtend"), "dtend")
    dtstart, dtend = normalize_event_times(dtstart, dtend, payload.get("duration_minutes"), all_day)

    now_iso = utc_now().isoformat()
    event = {
        "uid": new_uid(),
        "dtstamp": now_iso,
        "summary": summary,
        "description": payload.get("description") or "",
        "location": payload.get("location") or "",
        "status": None,
        "categories": [str(c) for c in (payload.get("categories") or [])],
        "dtstart": dtstart.isoformat(),
        "dtend": dtend.isoformat(),
        "all_day": all_day or _is_pure_date(dtstart),
        "alarms": [],
    }

    def _mut(todos: list[dict], events: list[dict]) -> None:
        if any(e.get("uid") == event["uid"] for e in events):
            raise ApiError(f"UID 冲突（理论不该发生）：{event['uid']}，旧文件已保留", 500)
        events.append(event)

    data = ics_store.mutate_calendar(base_dir, _mut)
    return _find_event(data["events"], event["uid"])


def update_event(base_dir: Path, uid: str, patch: dict) -> dict:
    """局部更新（PATCH /api/events/{uid}）→ 事件领域 dict。

    patch = model_dump(exclude_unset=True)；显式 None：dtend = 清除后按缺省
    规则重算；alarms/status/created 类字段不可改（白名单外一律忽略）。
    """
    patch = {k: v for k, v in patch.items() if k in EDITABLE_EVENT_FIELDS}
    if "summary" in patch:
        patch["summary"] = clean_summary(patch["summary"])
    if "categories" in patch and patch["categories"] is not None:
        patch["categories"] = [str(c) for c in patch["categories"]]
    if not patch:
        return get_event(base_dir, uid)

    def _mut(todos: list[dict], events: list[dict]) -> None:
        target = _find_event(events, uid)
        for k, v in patch.items():
            if k not in ("dtstart", "dtend", "duration_minutes"):
                target[k] = v
        dtstart = (
            parse_user_dt(patch["dtstart"], "dtstart")
            if "dtstart" in patch
            else as_time_value(target.get("dtstart"))
        )
        if dtstart is None:
            raise ValidationFailed("dtstart 不能为空")
        dtend = (
            parse_user_dt(patch["dtend"], "dtend")
            if "dtend" in patch
            else as_time_value(target.get("dtend"))
        )
        duration = patch.get("duration_minutes")
        if duration is not None:
            dtend = None  # duration 优先：清除旧 dtend 后按其重算
        # 上面的字段应用循环已把 patch 的 all_day 写进 target，这里取到的是新值
        all_day = bool(target.get("all_day"))
        if "all_day" in patch:
            if all_day:
                if "dtend" not in patch and duration is None:
                    # 定时 → 全天：未显式给结束即视为覆盖开始日
                    # （旧 dtend 的时刻部分截断后会变零长，故清空走缺省次日排他）
                    dtend = None
            else:
                # 全天 → 定时：纯日期提升为上海 00:00，避免 VALUE=DATE 残留
                dtstart, dtend = _to_midnight(dtstart), _to_midnight(dtend)
        dtstart, dtend = normalize_event_times(dtstart, dtend, duration, all_day)
        target["dtstart"] = dtstart.isoformat()
        target["dtend"] = dtend.isoformat()
        target["all_day"] = all_day or _is_pure_date(dtstart)
        target["dtstamp"] = utc_now().isoformat()  # RFC 5545：修改须刷新 DTSTAMP

    data = ics_store.mutate_calendar(base_dir, _mut)
    return _find_event(data["events"], uid)


def delete_event(base_dir: Path, uid: str) -> dict:
    """物理删除（DELETE /api/events/{uid}）→ {"deleted": [uid]}；写前备份仍在 .backup/。"""
    deleted: list[str] = []

    def _mut(todos: list[dict], events: list[dict]) -> None:
        _find_event(events, uid)  # 404 检查（写盘前）
        for e in list(events):
            if e.get("uid") == uid:
                events.remove(e)
                deleted.append(uid)

    ics_store.mutate_calendar(base_dir, _mut)
    return {"deleted": deleted}
