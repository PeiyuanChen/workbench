"""健康检查路由。"""

from fastapi import APIRouter

from app.core.config import data_root

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict:
    """返回服务状态与数据根目录（便于确认读到的是哪个数据目录）。"""
    return {"status": "ok", "data_root": str(data_root())}
