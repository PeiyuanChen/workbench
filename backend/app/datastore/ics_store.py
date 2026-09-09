"""iCalendar（.ics）读写：VTODO / VEVENT 与文件系统之间的唯一通道。

读：read_calendar(base_dir) → {"todos": [...], "events": [...]}（领域 dict）。
写：write_calendar(base_dir, data) 整份重建文件（M1 仅用于往返测试；
    M2 在此基础上扩展增删改）。

原则：
- 不手拼文本，序列化全部交给 icalendar 库（折行/转义合规，写出的文件
  必须能被 icalendar 重新解析——这是数据主权的底线）。
- 时间统一收口 Asia/Shanghai；全天（VALUE=DATE）保持 date 类型。
- 文件/目录不存在 → 返回空结构，不抛错（me 目录初始为空）。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from icalendar import Alarm, Calendar, Event, Todo

from app.core.contract import (
    DEFAULT_STATUS,
    RELTYPE_CHILD,
    RELTYPE_PARENT,
    TRUE_VALUES,
    X_IMPORTANT,
    X_URGENT,
)

ICS_FILENAME = "calendar.ics"
SH_TZ = ZoneInfo("Asia/Shanghai")


# ---------------------------------------------------------------- 解析


def _text(comp, name: str) -> str:
    """取文本属性；不存在返回空串。"""
    v = comp.get(name)
    return str(v) if v is not None else ""


def _flag(comp, name: str) -> bool:
    """解析 X-IMPORTANT / X-URGENT 布尔标签；缺失或非法一律 False（容错）。"""
    v = comp.get(name)
    if v is None:
        return False
    return str(v).strip().upper() in TRUE_VALUES


def _normalize_dt(value):
    """时间收口：datetime → aware(Asia/Shanghai)；date（全天）原样返回。"""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=SH_TZ)
        return value.astimezone(SH_TZ)
    return value


def _decode_dt(comp, name: str):
    """解码日期/时间属性 → (值, 是否全天)；不存在返回 (None, False)。"""
    prop = comp.get(name)
    if prop is None:
        return None, False
    value = _normalize_dt(prop.dt if hasattr(prop, "dt") else comp.decoded(name))
    return value, isinstance(value, date) and not isinstance(value, datetime)


def _decode_utc(comp, name: str):
    """解码 UTC 时间戳属性（DTSTAMP/COMPLETED/CREATED，RFC 规定为 UTC）。

    与本地时间不同：这类字段在领域 dict 中保持 UTC（+00:00），写回时仍是 Z。
    """
    prop = comp.get(name)
    if prop is None:
        return None
    value = prop.dt if hasattr(prop, "dt") else comp.decoded(name)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return None


def _iso(value) -> str | None:
    """datetime/date → ISO 字符串（前端直接展示）；None 原样。"""
    if value is None:
        return None
    return value.isoformat()


def _categories(comp) -> list[str]:
    """CATEGORIES 可能是单个 vCategory 或多行；统一拍平成字符串列表。"""
    raw = comp.get("CATEGORIES")
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    out: list[str] = []
    for cat in items:
        cats = getattr(cat, "cats", cat)  # vCategory.cats 为列表
        out.extend(str(c) for c in cats)
    return out


def _parent_uid(comp) -> str | None:
    """从 RELATED-TO 解析父任务 UID。

    项目约定 RELTYPE=CHILD 指向父；同时兼容 RFC 惯例的默认/RELTYPE=PARENT
    指向父。两种写法结果一致：被引用者 = 父任务。
    """
    rel = comp.get("RELATED-TO")
    if rel is None:
        return None
    items = rel if isinstance(rel, list) else [rel]
    for rt in items:
        reltype = str(rt.params.get("RELTYPE", RELTYPE_PARENT)).upper()
        if reltype in (RELTYPE_CHILD, RELTYPE_PARENT):
            return str(rt)
    return None


def _parse_todo(comp) -> dict:
    dtstart, all_day = _decode_dt(comp, "DTSTART")
    due, _ = _decode_dt(comp, "DUE")
    duration = comp.decoded("DURATION") if comp.get("DURATION") else None
    completed = _decode_utc(comp, "COMPLETED")
    created = _decode_utc(comp, "CREATED")
    priority = comp.get("PRIORITY")
    dtstamp = _decode_utc(comp, "DTSTAMP")
    return {
        "uid": _text(comp, "UID"),
        "dtstamp": _iso(dtstamp),
        "summary": _text(comp, "SUMMARY"),
        "description": _text(comp, "DESCRIPTION"),
        "status": _text(comp, "STATUS") or DEFAULT_STATUS,
        "priority": int(priority) if priority is not None else None,
        "categories": _categories(comp),
        "important": _flag(comp, X_IMPORTANT),
        "urgent": _flag(comp, X_URGENT),
        "dtstart": _iso(dtstart),
        "all_day": all_day,
        "due": _iso(due),
        "duration_minutes": int(duration.total_seconds() // 60) if duration else None,
        "completed": _iso(completed),
        "created": _iso(created),
        "parent_uid": _parent_uid(comp),
    }


def _parse_alarm(comp) -> dict:
    trigger = comp.get("TRIGGER")
    # 用 to_ical() 拿标准 ical 文本（如 -PT30M）；str() 会得到 repr，不可回写
    trigger_str = trigger.to_ical().decode() if trigger is not None else ""
    return {
        "trigger": trigger_str,
        "action": _text(comp, "ACTION"),
        "description": _text(comp, "DESCRIPTION"),
    }


def _parse_event(comp) -> dict:
    dtstart, all_day = _decode_dt(comp, "DTSTART")
    dtend, _ = _decode_dt(comp, "DTEND")
    if dtend is None and dtstart is not None and comp.get("DURATION"):
        dtend = dtstart + comp.decoded("DURATION")
    dtstamp = _decode_utc(comp, "DTSTAMP")
    return {
        "uid": _text(comp, "UID"),
        "dtstamp": _iso(dtstamp),
        "summary": _text(comp, "SUMMARY"),
        "description": _text(comp, "DESCRIPTION"),
        "location": _text(comp, "LOCATION"),
        "status": _text(comp, "STATUS"),
        "categories": _categories(comp),
        "dtstart": _iso(dtstart),
        "dtend": _iso(dtend),
        "all_day": all_day,
        "alarms": [_parse_alarm(a) for a in comp.walk("VALARM")],
    }


def read_calendar(base_dir: Path) -> dict:
    """读取 {base_dir}/calendar.ics → {"todos": [...], "events": [...]}。

    文件不存在或为空返回空结构（不抛错）；
    非空但解析失败说明文件损坏，向上抛错（不静默吞掉用户数据）。
    """
    path = Path(base_dir) / ICS_FILENAME
    if not path.exists():
        return {"todos": [], "events": []}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {"todos": [], "events": []}
    cal = Calendar.from_ical(text)
    todos = [_parse_todo(c) for c in cal.walk("VTODO")]
    events = [_parse_event(c) for c in cal.walk("VEVENT")]
    return {"todos": todos, "events": events}


# ---------------------------------------------------------------- 序列化


def _parse_iso(s: str | None):
    """ISO 字符串 → date（10 位）或 aware datetime；None 原样。"""
    if not s:
        return None
    if len(s) == 10:
        return date.fromisoformat(s)
    return datetime.fromisoformat(s)


def _to_local(value):
    """写回前把本地时间统一为 Asia/Shanghai（避免固定偏移写出怪异 TZID）。"""
    if isinstance(value, datetime):
        return value.astimezone(SH_TZ)
    return value


def _to_utc(value):
    """DTSTAMP/COMPLETED/CREATED 按 UTC 写（Z 后缀，RFC 惯例）。"""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    return value


def _build_todo(t: dict) -> Todo:
    comp = Todo()
    comp.add("uid", t["uid"])
    comp.add("dtstamp", _to_utc(_parse_iso(t.get("dtstamp")) or datetime.now(timezone.utc)))
    if t.get("created"):
        comp.add("created", _to_utc(_parse_iso(t["created"])))
    comp.add("summary", t.get("summary", ""))
    if t.get("description"):
        comp.add("description", t["description"])
    comp.add("status", t.get("status", DEFAULT_STATUS))
    if t.get("priority") is not None:
        comp.add("priority", t["priority"])
    if t.get("categories"):
        comp.add("categories", t["categories"])
    comp.add(X_IMPORTANT, "TRUE" if t.get("important") else "FALSE")
    comp.add(X_URGENT, "TRUE" if t.get("urgent") else "FALSE")
    if t.get("dtstart"):
        comp.add("dtstart", _to_local(_parse_iso(t["dtstart"])))
    if t.get("due"):
        comp.add("due", _to_local(_parse_iso(t["due"])))
    if t.get("duration_minutes") is not None:
        comp.add("duration", timedelta(minutes=t["duration_minutes"]))
    if t.get("completed"):
        comp.add("completed", _to_utc(_parse_iso(t["completed"])))
    if t.get("parent_uid"):
        comp.add("related-to", t["parent_uid"])
        comp["related-to"].params["RELTYPE"] = RELTYPE_CHILD
    return comp


def _build_alarm(a: dict) -> Alarm:
    comp = Alarm()
    trigger = a.get("trigger")
    if trigger:
        from icalendar.prop import vDuration

        comp.add("trigger", vDuration.from_ical(trigger))
    if a.get("action"):
        comp.add("action", a["action"])
    if a.get("description"):
        comp.add("description", a["description"])
    return comp


def _build_event(e: dict) -> Event:
    comp = Event()
    comp.add("uid", e["uid"])
    comp.add("dtstamp", _to_utc(_parse_iso(e.get("dtstamp")) or datetime.now(timezone.utc)))
    comp.add("summary", e.get("summary", ""))
    if e.get("dtstart"):
        comp.add("dtstart", _to_local(_parse_iso(e["dtstart"])))
    if e.get("dtend"):
        comp.add("dtend", _to_local(_parse_iso(e["dtend"])))
    if e.get("location"):
        comp.add("location", e["location"])
    if e.get("description"):
        comp.add("description", e["description"])
    if e.get("status"):
        comp.add("status", e["status"])
    if e.get("categories"):
        comp.add("categories", e["categories"])
    for a in e.get("alarms", []):
        comp.add_component(_build_alarm(a))
    return comp


def write_calendar(base_dir: Path, data: dict) -> Path:
    """把领域 dict 写回 {base_dir}/calendar.ics（整份重建）。

    M1 仅往返测试使用；文件头与样例保持一致（PRODID/VERSION/CALSCALE）。
    """
    cal = Calendar()
    cal.add("prodid", "-//Personal Workbench//Open Data Layer//CN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    for e in data.get("events", []):
        cal.add_component(_build_event(e))
    for t in data.get("todos", []):
        cal.add_component(_build_todo(t))
    path = Path(base_dir) / ICS_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(cal.to_ical())
    return path
