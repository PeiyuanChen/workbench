"""待办路由（M2：读 + 写）。

GET：
- GET /api/todos        列表（树形：子任务挂父节点，含象限/三阶段/进度/逾期）
- GET /api/todos/{uid}  单条
写（SPEC-M2 §2.1，响应信封 {"ok":true,"data":<受影响的顶层树节点>}）：
- POST   /api/todos                新建
- PATCH  /api/todos/{uid}          局部更新（不接受 status——决策 B）
- POST   /api/todos/{uid}/complete 勾选完成（幂等）
- POST   /api/todos/{uid}/reopen   取消完成 / 恢复放弃
- POST   /api/todos/{uid}/abandon  放弃（STATUS:CANCELLED）
- DELETE /api/todos/{uid}          物理删除（决策 C：级联删子任务）

查询参数：
- view=quadrant|list    仅语义区分（分组由前端完成）
- unscheduled=1         只看未排期（界面对应"未排期·最近要做"分区）
- status=NEEDS-ACTION|COMPLETED|...
- scope=active|archived|all  归档范围（决策 A；默认 active=顶层隐藏完成/放弃项）
- user=                 数据目录用户（默认 me，示例数据用 example）
"""

from fastapi import APIRouter, HTTPException, Query

from app.api.schemas import TodoCreate, TodoPatch
from app.core.config import data_root
from app.datastore import ics_store
from app.service import todo_service, todo_write

router = APIRouter(prefix="/api/todos", tags=["todos"])


def _tree(user: str | None) -> list[dict]:
    cal = ics_store.read_calendar(data_root(user))
    return todo_service.build_tree(cal["todos"])


@router.get("")
def list_todos(
    view: str | None = Query(None, pattern="^(quadrant|list)$"),
    unscheduled: int | None = None,
    status: str | None = None,
    scope: str = Query("active", pattern="^(active|archived|all)$"),
    user: str | None = None,
) -> dict:
    items = todo_service.filter_todos(_tree(user), view, bool(unscheduled), status)
    items = todo_service.filter_scope(items, scope)
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


@router.post("")
def create_todo(payload: TodoCreate, user: str | None = None) -> dict:
    node = todo_write.create_todo(data_root(user), payload.model_dump())
    return {"ok": True, "data": node}


@router.patch("/{uid}")
def patch_todo(uid: str, payload: TodoPatch, user: str | None = None) -> dict:
    # exclude_unset：没传的字段不动；显式 null = 清除（status 被 extra=forbid 拦截）
    node = todo_write.update_todo(data_root(user), uid, payload.model_dump(exclude_unset=True))
    return {"ok": True, "data": node}


@router.post("/{uid}/complete")
def complete_todo(uid: str, user: str | None = None) -> dict:
    return {"ok": True, "data": todo_write.change_status(data_root(user), uid, "complete")}


@router.post("/{uid}/reopen")
def reopen_todo(uid: str, user: str | None = None) -> dict:
    return {"ok": True, "data": todo_write.change_status(data_root(user), uid, "reopen")}


@router.post("/{uid}/abandon")
def abandon_todo(uid: str, user: str | None = None) -> dict:
    return {"ok": True, "data": todo_write.change_status(data_root(user), uid, "abandon")}


@router.delete("/{uid}")
def delete_todo(uid: str, user: str | None = None) -> dict:
    return {"ok": True, "data": todo_write.delete_todo(data_root(user), uid)}
