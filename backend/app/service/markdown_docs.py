"""备忘/笔记共享的 Markdown 文档写原语（ADR-0001：禁止两套近似实现）。

两类文档数据契约同构（frontmatter 四键 + 首行 H1 承载标题），标题清洗、
H1 拼装、文件名日期前缀规则完全一致，差异只在集合配置（目录名/id 前缀），
由各自 service 注入，本模块不感知具体集合。
"""

from __future__ import annotations

import re

from app.core.errors import ValidationFailed

# 标题长度上限（与待办 summary 同口径；文件名 slug 另有 60 字截断）
TITLE_MAX = 200

_FILENAME_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")


def clean_title(value) -> str:
    """title 去空白后非空、≤200 字；内部换行/连续空白折叠为单空格（保 H1 单行）。"""
    s = " ".join(str(value or "").split())
    if not s:
        raise ValidationFailed("title 不能为空")
    if len(s) > TITLE_MAX:
        raise ValidationFailed(f"title 过长（≤{TITLE_MAX} 字）：当前 {len(s)} 字")
    return s


def compose_body(title: str, content: str) -> str:
    """拼装正文：首行 H1 = 标题（三源一致），后接用户正文。

    - content 已以 "# {title}" 开头 → 原样保留（GET→PUT 幂等往返）；
    - content 以其他 H1 开头 → 替换为新标题（改标题场景，防双 H1）；
    - 其余 → 前面补 H1。
    """
    content = (content or "").strip()
    if not content:
        return f"# {title}\n"
    first, _, rest = content.partition("\n")
    if first.strip() == f"# {title}":
        return content
    if first.startswith("# "):
        rest = rest.strip("\n")
        return f"# {title}\n\n{rest}" if rest else f"# {title}\n"
    return f"# {title}\n\n{content}"


def date_from_filename(name: str) -> str | None:
    """从文件名取 YYYY-MM-DD 创建日期前缀；非法命名返回 None。"""
    m = _FILENAME_DATE_RE.match(name)
    return m.group(1) if m else None
