"""时间线路由（M1 只读：仅读已生成的 md，不做生成——生成是 M3 的事）。

GET /api/timeline/{year}/{month}
- 已存在 → {"exists": true, "frontmatter": ..., "body": ...}
- 不存在 → {"exists": false, "message": ...}（前端显示"未生成"占位）
"""

from fastapi import APIRouter, HTTPException

from app.core.config import data_root
from app.datastore import md_store

router = APIRouter(prefix="/api/timeline", tags=["timeline"])


@router.get("/{year}/{month}")
def get_timeline(year: int, month: int, user: str | None = None) -> dict:
    if not 1 <= month <= 12 or not 1970 <= year <= 2100:
        raise HTTPException(status_code=422, detail="非法年月")
    got = md_store.read_timeline(data_root(user), year, month)
    if got is None:
        return {
            "exists": False,
            "message": f"{year}年{month}月的时间线尚未生成（M3 起支持 LLM 生成）",
        }
    return {
        "exists": True,
        "frontmatter": got["frontmatter"],
        "body": got["body"],
    }
