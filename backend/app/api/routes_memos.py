"""备忘路由（M2：读 + 写；T1 改名 notes → memos）。

- GET    /api/memos          列表（按日期倒序）
- GET    /api/memos/{id}     单篇（含正文；id 优先 frontmatter，其次文件名）
- POST   /api/memos          新建（id/文件名服务端生成，SPEC-M2 §2.3）
- PUT    /api/memos/{id}     全文更新（标题变更时重命名文件，旧 id 不变）
- DELETE /api/memos/{id}     物理删除（删除前备份到 memos/.backup/）

写响应信封 {"ok":true,"data":<完整 memo 含 content>}；
错误 = 4xx/5xx + {"detail":"中文"}（main.py 统一 handler）。
/notes 命名空间自 T3（#4，ADR-0001）起归「笔记」模块，见 routes_notes.py。
"""

from fastapi import APIRouter, HTTPException

from app.api.schemas import MemoCreate, MemoUpdate
from app.core.config import data_root
from app.datastore import md_store
from app.datastore.md_store import MEMOS
from app.service import memo_write

router = APIRouter(prefix="/api/memos", tags=["memos"])


@router.get("")
def list_memos(user: str | None = None) -> dict:
    items = md_store.list_markdown(data_root(user), MEMOS)
    return {"count": len(items), "items": items}


@router.get("/{memo_id}")
def get_memo(memo_id: str, user: str | None = None) -> dict:
    memo = md_store.get_markdown(data_root(user), MEMOS, memo_id)
    if memo is None:
        raise HTTPException(status_code=404, detail=f"备忘不存在: {memo_id}")
    return memo


@router.post("")
def create_memo(payload: MemoCreate, user: str | None = None) -> dict:
    return {"ok": True, "data": memo_write.create_memo(data_root(user), payload.model_dump())}


@router.put("/{memo_id}")
def update_memo(memo_id: str, payload: MemoUpdate, user: str | None = None) -> dict:
    return {"ok": True, "data": memo_write.update_memo(data_root(user), memo_id, payload.model_dump())}


@router.delete("/{memo_id}")
def delete_memo(memo_id: str, user: str | None = None) -> dict:
    return {"ok": True, "data": memo_write.delete_memo(data_root(user), memo_id)}
