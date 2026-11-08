"""Markdown 集合图片资产存取（data/users/{user}/<集合目录>/assets/）。

T1 起按 MarkdownCollection 配置决定落盘位置（备忘 memos/assets，
未来笔记 notes/assets），与 md_store 同一套参数化内核。

设计约束（数据主权 + 安全）：
- 图片是用户数据：落盘为开放格式（png/jpeg/gif/webp），正文以标准 Markdown
  `![](assets/<名>)` 引用，记事本/Obsidian 可直接打开。
- 磁盘名一律由服务端生成（ASCII：日期时间 + 随机 hex），绝不使用客户端文件名，
  从源头回避中文文件名/路径穿越/保留设备名等问题。
- write-once 不可变随机名：永不覆盖、无旧版本，故只走原子写，不进 .backup。
- 只放行四种光栅位图；**SVG 明确排除**（可执行 XML，可带 <script>）。
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.errors import NotFound, ValidationFailed
from app.core.uids import hex_suffix, local_now
from app.datastore.atomic import atomic_write_bytes
from app.datastore.md_store import MarkdownCollection, collection_dir

MAX_ASSET_BYTES = 5 * 1024 * 1024  # 5 MiB（路由层在写盘前按此限流）

# 扩展名 → Content-Type（jpeg 族归一）
MEDIA_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# 磁盘名白名单：字母/数字开头，仅含 . _ -，长度 ≤100（挡掉 ../、斜杠、点开头）
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def _assets_dir(base_dir: Path, collection: MarkdownCollection) -> Path:
    return collection_dir(base_dir, collection) / collection.assets_dirname


def client_ext(filename: str | None) -> str:
    """从客户端文件名取小写后缀；不在白名单（含无后缀）→ 422。

    绝不信任 file.content_type（浏览器按扩展名猜，可伪造）。
    """
    ext = Path(filename or "").suffix.lower()
    if ext not in MEDIA_TYPES:
        raise ValidationFailed("仅支持 png/jpg/jpeg/gif/webp 图片")
    return ext


def sniff_kind(head: bytes) -> str | None:
    """按 magic byte 嗅探图片真实类型；无法识别返回 None。

    返回归一扩展名族：.jpg/.jpeg 都归 ".jpg"，便于与 client_ext 归一比族。
    """
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    # RIFF????WEBP
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    return None


def same_family(ext_a: str, ext_b: str) -> bool:
    """扩展名是否同族（.jpg/.jpeg 视为同族）。"""
    fam = {".jpg", ".jpeg"}
    return ext_a == ext_b or ({ext_a, ext_b} <= fam)


def new_asset_name(assets_dir: Path, ext: str, now=None) -> str:
    """生成不冲突的磁盘名：YYYYMMDD-HHMMSS-<8位hex><扩展名>，冲突重试。"""
    stamp = (now or local_now()).strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{hex_suffix()}{hex_suffix()}{ext}"
    if not (assets_dir / name).exists():
        return name
    for _ in range(16):
        name = f"{stamp}-{hex_suffix()}{hex_suffix()}{ext}"
        if not (assets_dir / name).exists():
            return name
    raise ValidationFailed("图片命名冲突，请重试")  # 极小概率：16 次全撞


def save_asset(base_dir: Path, collection: MarkdownCollection, data: bytes, ext: str) -> dict:
    """原子写入一张图片，返回 {name, path, size, content_type}。

    调用方须先完成大小闸门、扩展名白名单与 magic 嗅探。
    path 相对集合目录（正文以 ![](assets/<name>) 引用），与集合名解耦。
    """
    assets = _assets_dir(base_dir, collection)
    assets.mkdir(parents=True, exist_ok=True)
    name = new_asset_name(assets, ext)
    atomic_write_bytes(assets / name, data)
    return {
        "name": name,
        "path": f"{collection.assets_dirname}/{name}",
        "size": len(data),
        "content_type": MEDIA_TYPES[ext],
    }


def resolve_asset(base_dir: Path, collection: MarkdownCollection, name: str) -> tuple[Path, str]:
    """GET 取图：校验名字 → 后缀 → 目录边界 → 文件存在；返回 (路径, media_type)。"""
    if not SAFE_NAME_RE.match(name):
        # 路径穿越/非法字符一律按 422（不暴露文件是否存在）
        raise ValidationFailed("图片名非法")
    ext = Path(name).suffix.lower()
    media = MEDIA_TYPES.get(ext)
    if media is None:
        raise NotFound("图片不存在")
    assets = _assets_dir(base_dir, collection).resolve()
    target = (assets / name).resolve()
    if not target.is_relative_to(assets) or not target.is_file():
        raise NotFound("图片不存在")
    return target, media
