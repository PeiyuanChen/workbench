"""日历月聚合：把事件 + 待办（执行块/截止）归一成月内条目。

只读聚合（视图 ≠ 数据）：
- VEVENT → type=event（●）
- 待办执行块（DTSTART+DURATION）→ type=block（▸ 色块，跨多天 ▣ 横跨）
- 待办截止（DUE）→ type=due（⚑ 小旗，不占时长）
- 无时间待办不上日历。

日期区间一律"闭区间"（end_date = 覆盖的最后一天）；跨月条目裁剪到目标月，
days_in_month 供前端按日期分桶，start/end_date 保留完整跨度供横跨渲染。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta


def _from_iso(s: str | None):
    """ISO 字符串 → date（10 位，全天）或 aware datetime；None 原样。"""
    if not s:
        return None
    if len(s) == 10:
        return date.fromisoformat(s)
    return datetime.fromisoformat(s)


def _day_of(v) -> date:
    return v if (isinstance(v, date) and not isinstance(v, datetime)) else v.date()


def _span_days(start, end_excl) -> tuple[date, date]:
    """(起始, 排他终点) → (首日, 末日) 闭区间。

    - 全天（date 类型）：终点日期本身即排他（RFC 语义），末日 = 终点-1天。
    - 带时间：终点恰为 00:00 时同样不含当天。
    - 零/负时长兜底：末日不早于首日。
    """
    first = _day_of(start)
    last = _day_of(end_excl)
    if isinstance(start, datetime) and isinstance(end_excl, datetime):
        if end_excl.time() == time(0, 0):
            last -= timedelta(days=1)
    elif not isinstance(start, datetime):
        last -= timedelta(days=1)
    if last < first:
        last = first
    return first, last


def _hm(v) -> str | None:
    if isinstance(v, datetime):
        return f"{v.hour:02d}:{v.minute:02d}"
    return None


def _make_item(
    type_: str,
    uid: str,
    summary: str,
    categories: list[str],
    location: str,
    first: date,
    last: date,
    all_day: bool,
    start_moment,
    end_moment,
    year: int,
    month: int,
) -> dict | None:
    days: list[str] = []
    d = first
    while d <= last:
        if d.year == year and d.month == month:
            days.append(d.isoformat())
        d += timedelta(days=1)
    if not days:  # 整段在目标月之外
        return None
    multi_day = first != last
    return {
        "type": type_,
        "uid": uid,
        "summary": summary,
        "categories": categories or [],
        "location": location or "",
        "start_date": first.isoformat(),
        "end_date": last.isoformat(),
        "start_time": None if all_day else _hm(start_moment),
        # 跨天条目的结束时刻语义模糊，交给前端按横跨渲染
        "end_time": None if (all_day or multi_day) else _hm(end_moment),
        "all_day": all_day,
        "days_in_month": days,
    }


def month_items(events: list[dict], todos: list[dict], year: int, month: int) -> list[dict]:
    """聚合某月日历条目（事件 + 执行块 + 截止），按开始日期排序。"""
    items: list[dict] = []

    for ev in events:
        start = _from_iso(ev.get("dtstart"))
        if start is None:
            continue
        end = _from_iso(ev.get("dtend")) or start
        first, last = _span_days(start, end)
        all_day = bool(ev.get("all_day")) or not isinstance(start, datetime)
        item = _make_item(
            "event", ev.get("uid", ""), ev.get("summary", ""),
            ev.get("categories", []), ev.get("location", ""),
            first, last, all_day, start, end, year, month,
        )
        if item:
            items.append(item)

    for t in todos:
        start = _from_iso(t.get("dtstart"))
        duration = t.get("duration_minutes")
        # 执行块：DTSTART + DURATION（缺一不可）
        if start is not None and duration is not None:
            end = start + timedelta(minutes=int(duration))
            first, last = _span_days(start, end)
            all_day = bool(t.get("all_day")) or not isinstance(start, datetime)
            item = _make_item(
                "block", t.get("uid", ""), t.get("summary", ""),
                t.get("categories", []), "", first, last, all_day,
                start, end, year, month,
            )
            if item:
                items.append(item)
        # 截止：DUE（时点，不占时长）
        due = _from_iso(t.get("due"))
        if due is not None:
            day = _day_of(due)
            if day.year == year and day.month == month:
                items.append({
                    "type": "due",
                    "uid": t.get("uid", ""),
                    "summary": t.get("summary", ""),
                    "categories": t.get("categories", []) or [],
                    "location": "",
                    "start_date": day.isoformat(),
                    "end_date": day.isoformat(),
                    "start_time": _hm(due),
                    "end_time": None,
                    "all_day": not isinstance(due, datetime),
                    "days_in_month": [day.isoformat()],
                })

    items.sort(key=lambda i: (i["start_date"], 0 if i["all_day"] else 1, i["type"]))
    return items
