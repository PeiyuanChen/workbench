"""Markdown（备忘 notes / 时间线 timeline）读写：文件系统唯一通道。

约定（见 CLAUDE.md 数据契约）：
- 备忘：notes/YYYY-MM-DD-标题.md，frontmatter 含 id / tags / related + 正文。
- 时间线：timeline/YYYY/MM.md，同构；只读已生成文件，无则视为"未生成"
  （LLM 生成在 M3）。

M2 写入（SPEC-M2 §2.3）：write_note / delete_note 与 ics 同口径——
写前备份到 notes/.backup/（滚动 10 份）、原子写、写后 frontmatter 回读校验。
"""

from __future__ import annotations

import re
from pathlib import Path

import frontmatter

from app.core.contract import FRONTMATTER_KEYS
# slugify_title/TITLE_MAX/UNTITLED 定义在 core.uids（id 与文件名共用规则），此处转发
from app.core.uids import TITLE_MAX, UNTITLED, hex_suffix, slugify_title  # noqa: F401
from app.datastore.atomic import BACKUP_DIRNAME, AtomicWriteError, backup_file, safe_write

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


def find_note_path(base_dir: Path, note_id: str) -> Path | None:
    """按 id 定位备忘文件路径：优先 frontmatter id，其次文件名（去扩展名）。

    与 get_note 匹配规则一致；坏文件（frontmatter 解析失败）跳过。
    """
    notes_dir = Path(base_dir) / NOTES_DIR
    if not notes_dir.exists():
        return None
    for p in notes_dir.glob("*.md"):
        try:
            meta = frontmatter.load(p).metadata
        except Exception:  # noqa: BLE001 坏文件跳过，与 list_notes 容错一致
            continue
        if str(meta.get("id") or "") == note_id or p.stem == note_id:
            return p
    return None


def get_note(base_dir: Path, note_id: str) -> dict | None:
    """单篇备忘：优先 frontmatter id 匹配，其次文件名（去扩展名）匹配。"""
    path = find_note_path(base_dir, note_id)
    if path is None:
        return None
    n = _parse_note(path)
    if n is None:
        return None
    post = frontmatter.load(path)
    return {**n, "content": post.content.strip()}


# ---------------------------------------------------------------- 写入（M2）


def make_note_filename(base_dir: Path, date_str: str, title: str) -> str:
    """生成不冲突的备忘文件名：YYYY-MM-DD-<标题清洗>.md。

    同名冲突追加 -<4hex> 短后缀（SPEC-M2 §2.3）。
    """
    slug = slugify_title(title)
    notes_dir = Path(base_dir) / NOTES_DIR
    name = f"{date_str}-{slug}.md"
    if not (notes_dir / name).exists():
        return name
    for _ in range(64):
        name = f"{date_str}-{slug}-{hex_suffix()}.md"
        if not (notes_dir / name).exists():
            return name
    raise AtomicWriteError(f"备忘文件名冲突重试耗尽：{title}")


def _verify_note(path: Path) -> None:
    """回读闸门：frontmatter 可重解析且契约三键（id/tags/related）齐全。"""
    post = frontmatter.load(path)
    missing = [k for k in FRONTMATTER_KEYS if k not in post.metadata]
    if missing:
        raise ValueError(f"frontmatter 缺少契约键：{missing}")


def write_note(
    base_dir: Path,
    filename: str,
    metadata: dict,
    body: str,
    old_path: Path | None = None,
) -> Path:
    """写备忘（原子写 + 写前备份 notes/.backup/ 滚动 10 份 + 回读校验）。

    - metadata 需含契约三键 id/tags/related（可含 created）；键序即落盘序
      （dumps sort_keys=False），调用方按 id/created/tags/related 传入。
    - 覆盖已有同名文件时 safe_write 自动备份旧内容。
    - old_path：改标题重命名场景的旧文件路径，备份后删除（防新旧两份并存）。
    """
    notes_dir = Path(base_dir) / NOTES_DIR
    notes_dir.mkdir(parents=True, exist_ok=True)
    path = notes_dir / filename
    post = frontmatter.Post(body, **metadata)
    raw = frontmatter.dumps(post, sort_keys=False).encode("utf-8")
    safe_write(path, raw, verify=_verify_note, backup_dir=notes_dir / BACKUP_DIRNAME)
    if old_path is not None and Path(old_path) != path:
        backup_file(Path(old_path), notes_dir / BACKUP_DIRNAME)
        Path(old_path).unlink(missing_ok=True)
    return path


def delete_note(base_dir: Path, note_id: str) -> Path:
    """物理删除备忘文件（删除前备份，.backup/ 里可找回）。

    找不到抛 FileNotFoundError（service 层映射 404）。
    """
    path = find_note_path(base_dir, note_id)
    if path is None:
        raise FileNotFoundError(f"备忘不存在: {note_id}")
    backup_file(path, Path(base_dir) / NOTES_DIR / BACKUP_DIRNAME)
    path.unlink()
    return path


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
