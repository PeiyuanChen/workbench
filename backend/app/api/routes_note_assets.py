"""笔记图片资产路由（#4）：POST/GET /api/notes/assets。

- POST：multipart 表单字段 file（图片）+ folder（可选，资产归属的笔记文件夹，默认根层）。
  落盘平铺在 data/users/{user}/notes/assets/，磁盘名带文件夹扁平前缀
  （多层段间 __，根层无前缀）；返回的 path 已按文件夹深度算好正文相对链接。
- GET：按服务端生成的名字取图，安全规则与备忘完全对等（共用 app.api.uploads）。
"""

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse

from app.api.uploads import read_validated_image
from app.core.config import data_root
from app.datastore import asset_store, md_store
from app.datastore.md_store import NOTES

router = APIRouter(prefix="/api/notes/assets", tags=["notes-assets"])


@router.post("")
async def upload_asset(
    user: str | None = None,
    folder: str = Form(""),
    file: UploadFile = File(...),
) -> dict:
    data, ext = await read_validated_image(file)
    base = data_root(user)
    norm_folder = md_store.ensure_folder_exists(base, NOTES, folder)
    return {
        "ok": True,
        "data": asset_store.save_asset(base, NOTES, data, ext, folder=norm_folder),
    }


@router.get("/{name}")
def get_asset(name: str, user: str | None = None) -> FileResponse:
    path, media_type = asset_store.resolve_asset(data_root(user), NOTES, name)
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
        },
    )
