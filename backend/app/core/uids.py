"""标识符与标题清洗（SPEC-M2 决策 #2 / 决策 D；T1 参数化）。

- 待办/事件 UID：`YYYYMMDDTHHMMSS-<4位hex>@workbench.local`
  （时间用 Asia/Shanghai 本地钟面，4 位 hex 用 secrets.token_hex(2)）。
- Markdown 文档 id：`YYYYMMDD-<前缀>-<标题清洗>`（保留中文；冲突短后缀由调用方追加）；
  前缀由集合配置注入（备忘 = memo，未来笔记 = note）。
- slugify_title：Markdown 文件名与 id 共用的标题清洗规则。
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.core.contract import TIMEZONE

UID_DOMAIN = "@workbench.local"
# 标题清洗（决策 D）：保留中文，截断上限；清洗后为空回退"未命名"
TITLE_MAX = 60
UNTITLED = "未命名"

# Windows 文件系统非法字符 + 控制字符（跨平台取最严）
_ILLEGAL_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE_RE = re.compile(r"\s+")

LOCAL_TZ = ZoneInfo(TIMEZONE)


def utc_now() -> datetime:
    """当前 UTC 时间（DTSTAMP/COMPLETED/CREATED 用，RFC 规定为 UTC）。"""
    return datetime.now(timezone.utc)


def local_now() -> datetime:
    """当前 Asia/Shanghai 本地钟面（UID 时间戳用，决策 #2）。"""
    return datetime.now(LOCAL_TZ)


def new_uid(now: datetime | None = None) -> str:
    """生成待办/事件 UID：YYYYMMDDTHHMMSS-<4hex>@workbench.local。"""
    now = now or local_now()
    return f"{now.strftime('%Y%m%dT%H%M%S')}-{secrets.token_hex(2)}{UID_DOMAIN}"


def slugify_title(title: str) -> str:
    """标题清洗（决策 D）：去文件系统非法字符/控制字符、空白折叠为 '-'、
    保留中文、截断 60 字符；清洗后为空回退"未命名"。

    Windows 文件名不得以点/空格结尾，首尾 '-' 也一并去掉。
    """
    s = _ILLEGAL_CHARS_RE.sub("", title or "")
    s = _WHITESPACE_RE.sub("-", s.strip())
    s = s.strip("-.")[:TITLE_MAX].rstrip("-.")
    return s or UNTITLED


def new_doc_id(id_prefix: str, title: str, now: datetime | None = None) -> str:
    """Markdown 文档 id：YYYYMMDD-<前缀>-<标题清洗>（保留中文，决策 D）。

    id_prefix 由 MarkdownCollection 注入（备忘 "memo" / 未来笔记 "note"）；
    id 冲突时由调用方（service 层）追加 -<4hex> 短后缀重试。
    """
    now = now or local_now()
    return f"{now.strftime('%Y%m%d')}-{id_prefix}-{slugify_title(title)}"


def hex_suffix() -> str:
    """4 位 hex 短后缀（文件名/id 同名冲突时追加）。"""
    return secrets.token_hex(2)
