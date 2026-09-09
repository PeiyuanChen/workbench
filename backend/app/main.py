"""个人工作台后端入口。

M1 阶段只读：提供 GET 接口，读取 data/ 目录下的 .ics / .md 开放格式文件。
启动：在 backend/ 目录下执行 `uv run uvicorn app.main:app --reload`。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_events, routes_health, routes_notes, routes_timeline, routes_todos

app = FastAPI(title="个人工作台 API", version="0.1.0")

# 开发期允许 Vite dev server 跨域（生产走同源代理，无影响）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(routes_health.router)
app.include_router(routes_todos.router)
app.include_router(routes_events.router)
app.include_router(routes_notes.router)
app.include_router(routes_timeline.router)
