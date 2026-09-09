"""备忘路由（M1 只读）。

GET /api/notes          列表（按日期倒序）
GET /api/notes/{id}     单篇（含正文；id 优先 frontmatter，其次文件名）
"""

from fastapi import APIRouter, HTTPException

from app.core.config import data_root
from app.datastore import md_store

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
