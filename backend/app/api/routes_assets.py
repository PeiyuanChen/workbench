"""备忘图片资产路由。

- POST /api/notes/assets?user=   multipart 上传一张图片（表单字段 file）
- GET  /api/notes/assets/{name}?user=   按服务端生成的名字取图

落盘在 data/users/{user}/notes/assets/，正文以 ![](assets/<name>) 引用。
写响应沿用信封 {"ok":true,"data":{name,path,size,content_type}}。
"""

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse

from app.core.config import data_root
from app.core.errors import ValidationFailed
from app.datastore import asset_store

router = APIRouter(prefix="/api/notes/assets", tags=["notes-assets"])

_READ_CHUNK = 64 * 1024


@router.post("")
async def upload_asset(user: str | None = None, file: UploadFile = File(...)) -> dict:
    # 大小闸门：分块累积，超限立即拒绝（此时尚未写盘，无残留）
    buf = bytearray()
    while True:
        chunk = await file.read(_READ_CHUNK)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > asset_store.MAX_ASSET_BYTES:
            raise ValidationFailed(
                f"图片过大，上限 {asset_store.MAX_ASSET_BYTES // 1024 // 1024}MB"
            )
    data = bytes(buf)

    ext = asset_store.client_ext(file.filename)
    kind = asset_store.sniff_kind(data[:16])
    if kind is None or not asset_store.same_family(ext, kind):
        raise ValidationFailed("文件内容与扩展名不符，仅支持 png/jpg/jpeg/gif/webp 图片")

    return {"ok": True, "data": asset_store.save_asset(data_root(user), data, ext)}


@router.get("/{name}")
def get_asset(name: str, user: str | None = None) -> FileResponse:
    path, media_type = asset_store.resolve_asset(data_root(user), name)
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
        },
    )
