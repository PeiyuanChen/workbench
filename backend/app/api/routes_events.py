"""日历路由（M2：聚合读 + 事件写）。

- GET    /api/events?month=YYYY-MM  月聚合（VEVENT + 待办执行块 ▸ + 截止 ⚑）
- GET    /api/events/{uid}          单条事件（编辑表单数据源：含 dtend/description/alarms）
- POST   /api/events                新建
- PATCH  /api/events/{uid}          局部更新
- DELETE /api/events/{uid}          物理删除

写响应信封 {"ok":true,"data":<事件>}；dtend 恒为 RFC 排他语义（前端选择器
呈现含首尾、提交时 +1 天，SPEC-M2 §2.2）。事件表单入口在日历页（决策 #8）。
"""

from fastapi import APIRouter, Query

from app.api.schemas import EventCreate, EventPatch
from app.core.config import data_root
from app.datastore import ics_store
from app.service import calendar_service, event_write

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


@router.get("/{uid}")
def get_event(uid: str, user: str | None = None) -> dict:
    return event_write.get_event(data_root(user), uid)


@router.post("")
def create_event(payload: EventCreate, user: str | None = None) -> dict:
    event = event_write.create_event(data_root(user), payload.model_dump())
    return {"ok": True, "data": event}


@router.patch("/{uid}")
def patch_event(uid: str, payload: EventPatch, user: str | None = None) -> dict:
    event = event_write.update_event(data_root(user), uid, payload.model_dump(exclude_unset=True))
    return {"ok": True, "data": event}


@router.delete("/{uid}")
def delete_event(uid: str, user: str | None = None) -> dict:
    return {"ok": True, "data": event_write.delete_event(data_root(user), uid)}
