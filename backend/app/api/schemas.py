"""Pydantic 请求模型（SPEC-M2 §2 API 契约）。

约定：
- 时间字段一律声明 str：解析权在 service（naive → Asia/Shanghai，SPEC §2.1），
  避免 pydantic 自动 datetime 转换引入时区歧义。
- Patch/全部模型 extra="forbid"：未知字段 → 422（main.py 中文化 handler）。
  TodoPatch 不含 status 字段 = 决策 B（PATCH 拒绝 status，状态走专用动作）。
- PATCH 语义：exclude_unset 区分"没传"（不动）与"显式 null"（清除该字段）。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TodoCreate(BaseModel):
    """POST /api/todos 请求体（SPEC-M2 §2.1）。"""

    model_config = ConfigDict(extra="forbid")

    summary: str
    description: str | None = None
    important: bool = False
    urgent: bool = False
    due: str | None = None
    dtstart: str | None = None
    duration_minutes: int | None = None
    all_day: bool = False
    categories: list[str] | None = None
    parent_uid: str | None = None


class TodoPatch(BaseModel):
    """PATCH /api/todos/{uid} 请求体：可改业务字段；不接受 status（决策 B）。"""

    model_config = ConfigDict(extra="forbid")

    summary: str | None = None
    description: str | None = None
    important: bool | None = None
    urgent: bool | None = None
    due: str | None = None
    dtstart: str | None = None
    duration_minutes: int | None = None
    all_day: bool | None = None
    categories: list[str] | None = None
    parent_uid: str | None = None


class EventCreate(BaseModel):
    """POST /api/events 请求体（SPEC-M2 §2.2；dtend 为 RFC 排他语义）。"""

    model_config = ConfigDict(extra="forbid")

    summary: str
    dtstart: str
    dtend: str | None = None
    duration_minutes: int | None = None
    location: str | None = None
    description: str | None = None
    categories: list[str] | None = None
    all_day: bool = False


class EventPatch(BaseModel):
    """PATCH /api/events/{uid} 请求体。"""

    model_config = ConfigDict(extra="forbid")

    summary: str | None = None
    dtstart: str | None = None
    dtend: str | None = None
    duration_minutes: int | None = None
    location: str | None = None
    description: str | None = None
    categories: list[str] | None = None
    all_day: bool | None = None


class NoteCreate(BaseModel):
    """POST /api/notes 请求体（SPEC-M2 §2.3；id/文件名服务端生成）。"""

    model_config = ConfigDict(extra="forbid")

    title: str
    content: str = ""
    tags: list[str] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)


class NoteUpdate(BaseModel):
    """PUT /api/notes/{id} 请求体：全文更新（标题变更时重命名文件，id 不变）。"""

    model_config = ConfigDict(extra="forbid")

    title: str
    content: str = ""
    tags: list[str] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)
