"""个人工作台后端入口。

M2：读写接口——直读直写 data/ 下 .ics/.md 开放格式文件，
写入走安全闸门（原子写 + 写前备份 + 写后回读，见 datastore/atomic.py）。
启动：在 backend/ 目录下执行 `uv run uvicorn app.main:app --reload`。
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import routes_events, routes_health, routes_notes, routes_timeline, routes_todos
from app.core.errors import ApiError
from app.datastore.atomic import AtomicWriteError

app = FastAPI(title="个人工作台 API", version="0.2.0")

# 开发期允许 Vite dev server 跨域（生产走同源代理，无影响）；M2 起放行写方法
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- 错误契约
# SPEC-M2 §2：错误 = HTTP 4xx/5xx + {"detail": "中文错误信息"}


def _cn_validation_message(exc: RequestValidationError) -> str:
    """pydantic 原生 422 是英文结构化信息，统一转中文 detail。"""
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", ()) if x not in ("body", "query"))
        etype = err.get("type", "")
        if etype == "extra_forbidden":
            if loc == "status":
                parts.append("不接受 status 字段：完成/放弃/恢复请用 complete/abandon/reopen 专用动作")
            else:
                parts.append(f"不接受的字段: {loc}")
        elif etype == "missing":
            parts.append(f"缺少必填字段: {loc}")
        elif etype == "string_pattern_mismatch":
            parts.append(f"参数取值非法: {loc}")
        else:
            parts.append(f"字段非法: {loc}（{err.get('msg', '')}）")
    return "；".join(parts) or "请求校验失败"


@app.exception_handler(ApiError)
async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    """业务异常（NotFound/ValidationFailed/…）→ 状态码 + 中文 detail。"""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(AtomicWriteError)
async def _atomic_write_error_handler(request: Request, exc: AtomicWriteError) -> JSONResponse:
    """写闸门失败（现场已恢复/删除，磁盘无坏数据）→ 500 + 中文 detail。"""
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.exception_handler(RequestValidationError)
async def _request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """请求体/查询参数校验失败 → 422 中文 detail。"""
    return JSONResponse(status_code=422, content={"detail": _cn_validation_message(exc)})


app.include_router(routes_health.router)
app.include_router(routes_todos.router)
app.include_router(routes_events.router)
app.include_router(routes_notes.router)
app.include_router(routes_timeline.router)
