"""multipart 图片上传的共享读取与安全闸门（备忘/笔记两个资产路由共用）。

安全水位两模块完全对等，差异仅在落盘集合配置，故分块限流、扩展名白名单、
magic byte 嗅探只此一份实现（ADR-0001：禁止两套近似实现）。
"""

from fastapi import UploadFile

from app.core.errors import ValidationFailed
from app.datastore import asset_store

_READ_CHUNK = 64 * 1024


async def read_validated_image(file: UploadFile) -> tuple[bytes, str]:
    """读完整张图片并过安全闸门，返回 (字节内容, 归一扩展名)。

    - 分块累积，超 5 MiB 在写盘前立即拒绝（无目标文件、无 .tmp 残留）；
    - 扩展名白名单 + magic byte 嗅探双校验，不信 file.content_type。
    """
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
    return data, ext
