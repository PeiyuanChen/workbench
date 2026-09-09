"""待办路由（M1 只读）。

- GET /api/todos        列表（树形：子任务挂父节点，含象限/三阶段/进度/逾期）
- GET /api/todos/{uid}  单条
查询参数：
- view=quadrant|list    仅语义区分（分组由前端完成）
- unscheduled=1         只看未排期（界面对应"未排期·最近要做"分区）
- status=NEEDS-ACTION|COMPLETED|...
- user=                 数据目录用户（默认 me，示例数据用 example）
"""

from fastapi import APIRouter, HTTPException, Query

from app.core.config import data_root
from app.datastore import ics_store
from app.service import todo_service

router = APIRouter(prefix="/api/todos", tags=["todos"])


def _tree(user: str | None) -> list[dict]:
    cal = ics_store.read_calendar(data_root(user))
    return todo_service.build_tree(cal["todos"])


@router.get("")
def list_todos(
    view: str | None = Query(None, pattern="^(quadrant|list)$"),
    unscheduled: int | None = None,
    status: str | None = None,
    user: str | None = None,
) -> dict:
    items = todo_service.filter_todos(_tree(user), view, bool(unscheduled), status)
    return {"count": len(items), "items": items}


@router.get("/{uid}")
def get_todo(uid: str, user: str | None = None) -> dict:
    for node in _tree(user):
        if node["uid"] == uid:
            return node
        for child in node.get("children", []):
            if child["uid"] == uid:
                return child
    raise HTTPException(status_code=404, detail=f"待办不存在: {uid}")
