"""笔记路由（#4：读 + 写 + 文件夹；ADR-0001/0002）。

- GET    /api/notes              递归列表（扁平 {count, folders, items}，保留目录排除）
- POST   /api/notes/folders      新建文件夹（真实子目录，支持嵌套）
- PUT    /api/notes/folders      同父目录重命名
- DELETE /api/notes/folders      删除空文件夹（非空 422）
- GET    /api/notes/{id}         单篇（含正文与 folder）
- POST   /api/notes              新建（id/文件名服务端生成，folder 可选）
- PUT    /api/notes/{id}         全文更新；载荷含 folder 时移动并按深度改写资产链接
- DELETE /api/notes/{id}         物理删除（删除前备份到 notes/.backup/）

写响应信封 {"ok":true,"data":...}；错误 = 4xx/5xx + {"detail":"中文"}。
文件夹路径含斜杠与中文，统一走请求体/query，不进 URL path（规避 %2F 歧义）。
"""

from fastapi import APIRouter, HTTPException

from app.api.schemas import FolderCreate, FolderRename, NoteCreate, NoteUpdate
from app.core.config import data_root
from app.datastore import md_store
from app.datastore.md_store import NOTES
from app.service import note_write

router = APIRouter(prefix="/api/notes", tags=["notes"])


# 文件夹端点须注册在 /{note_id} 之前，避免静态路径被路径参数吞掉


@router.post("/folders")
def create_folder(payload: FolderCreate, user: str | None = None) -> dict:
    return {"ok": True, "data": note_write.create_folder(data_root(user), payload.path)}


@router.put("/folders")
def rename_folder(payload: FolderRename, user: str | None = None) -> dict:
    return {
        "ok": True,
        "data": note_write.rename_folder(data_root(user), payload.path, payload.new_path),
    }


@router.delete("/folders")
def delete_folder(path: str, user: str | None = None) -> dict:
    note_write.delete_folder(data_root(user), path)
    return {"ok": True, "data": {"path": path}}


@router.get("")
def list_notes(user: str | None = None) -> dict:
    base = data_root(user)
    items = md_store.list_notes(base, NOTES)
    return {
        "count": len(items),
        "folders": md_store.list_folders(base, NOTES),
        "items": items,
    }


@router.get("/{note_id}")
def get_note(note_id: str, user: str | None = None) -> dict:
    note = md_store.get_note(data_root(user), NOTES, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail=f"笔记不存在: {note_id}")
    return note


@router.post("")
def create_note(payload: NoteCreate, user: str | None = None) -> dict:
    return {"ok": True, "data": note_write.create_note(data_root(user), payload.model_dump())}


@router.put("/{note_id}")
def update_note(note_id: str, payload: NoteUpdate, user: str | None = None) -> dict:
    # model_fields_set 区分「没传 folder」（留在原目录）与「显式传空串」（移回根层）
    folder_given = "folder" in payload.model_fields_set
    return {
        "ok": True,
        "data": note_write.update_note(
            data_root(user), note_id, payload.model_dump(), folder_given
        ),
    }


@router.delete("/{note_id}")
def delete_note(note_id: str, user: str | None = None) -> dict:
    return {"ok": True, "data": note_write.delete_note(data_root(user), note_id)}
