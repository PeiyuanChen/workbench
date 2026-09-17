"""备忘路由（M2：读 + 写）。

- GET    /api/notes          列表（按日期倒序）
- GET    /api/notes/{id}     单篇（含正文；id 优先 frontmatter，其次文件名）
- POST   /api/notes          新建（id/文件名服务端生成，SPEC-M2 §2.3）
- PUT    /api/notes/{id}     全文更新（标题变更时重命名文件，旧 id 不变）
- DELETE /api/notes/{id}     物理删除（删除前备份到 notes/.backup/）

写响应信封 {"ok":true,"data":<完整 note 含 content>}；
错误 = 4xx/5xx + {"detail":"中文"}（main.py 统一 handler）。
"""

from fastapi import APIRouter, HTTPException

from app.api.schemas import NoteCreate, NoteUpdate
from app.core.config import data_root
from app.datastore import md_store
from app.service import note_write

router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.get("")
def list_notes(user: str | None = None) -> dict:
    items = md_store.list_notes(data_root(user))
    return {"count": len(items), "items": items}


@router.get("/{note_id}")
def get_note(note_id: str, user: str | None = None) -> dict:
    note = md_store.get_note(data_root(user), note_id)
    if note is None:
        raise HTTPException(status_code=404, detail=f"备忘不存在: {note_id}")
    return note


@router.post("")
def create_note(payload: NoteCreate, user: str | None = None) -> dict:
    return {"ok": True, "data": note_write.create_note(data_root(user), payload.model_dump())}


@router.put("/{note_id}")
def update_note(note_id: str, payload: NoteUpdate, user: str | None = None) -> dict:
    return {"ok": True, "data": note_write.update_note(data_root(user), note_id, payload.model_dump())}


@router.delete("/{note_id}")
def delete_note(note_id: str, user: str | None = None) -> dict:
    return {"ok": True, "data": note_write.delete_note(data_root(user), note_id)}
