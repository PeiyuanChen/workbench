"""Markdown（备忘 notes / 时间线 timeline）读取：文件系统唯一通道。

约定（见 CLAUDE.md 数据契约）：
- 备忘：notes/YYYY-MM-DD-标题.md，frontmatter 含 id / tags / related + 正文。
- 时间线：timeline/YYYY/MM.md，同构；M1 只读已生成文件，无则视为"未生成"。
M1 只读；写入（PUT/POST）在 M2 实现。
"""

from __future__ import annotations

import re
from pathlib import Path

import frontmatter

NOTES_DIR = "notes"
TIMELINE_DIR = "timeline"
EXCERPT_MAX = 80

# 文件名：YYYY-MM-DD-标题.md
_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)\.md$")
# 正文首个一级标题 → 标题
_H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def _excerpt(body: str) -> str:
    """摘取正文第一段非标题文本作为摘要（截断到 80 字）。"""
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(">"):
            continue
        text = re.sub(r"[*_`\[\]]", "", line)  # 去掉常见 Markdown 标记
        return text[:EXCERPT_MAX]
    return ""


def _parse_note(path: Path) -> dict | None:
    """解析单篇备忘 → 领域 dict；文件名非法或解析失败返回 None（跳过）。"""
    m = _FILENAME_RE.match(path.name)
    date_str = m.group(1) if m else None
    title_from_name = m.group(2) if m else path.stem
    try:
        post = frontmatter.load(path)
    except Exception:  # noqa: BLE001 坏文件跳过，不影响列表
        return None
    meta = dict(post.metadata)
    body = post.content.strip()
    h1 = _H1_RE.search(body)
    return {
        "id": str(meta.get("id") or path.stem),
        "title": h1.group(1).strip() if h1 else title_from_name,
        "date": date_str,
        "tags": [str(t) for t in (meta.get("tags") or [])],
        "related": [str(r) for r in (meta.get("related") or [])],
        "created": str(meta["created"]) if meta.get("created") else None,
        "excerpt": _excerpt(body),
        "filename": path.name,
    }


def list_notes(base_dir: Path) -> list[dict]:
    """备忘列表：按文件名日期倒序（新在前），同日按标题排序。"""
    notes_dir = Path(base_dir) / NOTES_DIR
    if not notes_dir.exists():
        return []
    notes = [n for n in (_parse_note(p) for p in notes_dir.glob("*.md")) if n]
    notes.sort(key=lambda n: (n["date"] or "", n["title"]), reverse=True)
    return notes


def get_note(base_dir: Path, note_id: str) -> dict | None:
    """单篇备忘：优先 frontmatter id 匹配，其次文件名（去扩展名）匹配。"""
    for n in list_notes(base_dir):
        if n["id"] == note_id or Path(n["filename"]).stem == note_id:
            path = Path(base_dir) / NOTES_DIR / n["filename"]
            post = frontmatter.load(path)
            return {**n, "content": post.content.strip()}
    return None


def read_timeline(base_dir: Path, year: int, month: int) -> dict | None:
    """读某月时间线：不存在返回 None（上层转为"未生成"提示）。"""
    path = Path(base_dir) / TIMELINE_DIR / f"{year:04d}" / f"{month:02d}.md"
    if not path.exists():
        return None
    post = frontmatter.load(path)
    return {
        "frontmatter": dict(post.metadata),
        "body": post.content.strip(),
    }
