"""日历路由（M1 只读聚合）。

GET /api/events?month=YYYY-MM
聚合：VEVENT + 待办执行块（DTSTART+DURATION）+ 截止（DUE）；
无时间待办不上日历。跨月条目裁剪到本月（days_in_month）。
"""

from fastapi import APIRouter, Query

from app.core.config import data_root
from app.datastore import ics_store
from app.service import calendar_service

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("")
def list_events(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="格式 YYYY-MM"),
    user: str | None = None,
) -> dict:
    year, mon = (int(x) for x in month.split("-"))
    cal = ics_store.read_calendar(data_root(user))
    items = calendar_service.month_items(cal["events"], cal["todos"], year, mon)
    return {"month": month, "items": items}
