"""备忘图片资产路由（T1 改名 notes → memos）。

- POST /api/memos/assets?user=   multipart 上传一张图片（表单字段 file）
- GET  /api/memos/assets/{name}?user=   按服务端生成的名字取图

落盘在 data/users/{user}/memos/assets/，正文以 ![](assets/<name>) 引用。
写响应沿用信封 {"ok":true,"data":{name,path,size,content_type}}。
安全闸门在 app.api/uploads，与笔记资产路由共用同一份实现。
"""

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse

from app.api.uploads import read_validated_image
from app.core.config import data_root
from app.datastore import asset_store
from app.datastore.md_store import MEMOS

router = APIRouter(prefix="/api/memos/assets", tags=["memos-assets"])


@router.post("")
async def upload_asset(user: str | None = None, file: UploadFile = File(...)) -> dict:
    data, ext = await read_validated_image(file)
    return {"ok": True, "data": asset_store.save_asset(data_root(user), MEMOS, data, ext)}


@router.get("/{name}")
def get_asset(name: str, user: str | None = None) -> FileResponse:
    path, media_type = asset_store.resolve_asset(data_root(user), MEMOS, name)
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
        },
    )
