"""Markdown 集合读写内核（文件系统唯一通道）。

T1 起内核按 `MarkdownCollection` 配置参数化，备忘（memos）与未来笔记（notes）
共用同一套实现，差异只在配置（物理目录名、id 前缀、资产子目录名），
不存在两套复制实现（ADR 0001）。

约定（见 CLAUDE.md 数据契约）：
- 集合文档：`<dir_name>/YYYY-MM-DD-标题.md`，frontmatter 含 id / tags / related + 正文。
- 时间线：timeline/YYYY/MM.md，同构但布局不同，只读已生成文件，无则视为"未生成"
  （LLM 生成在 M3），故不走集合内核。

M2 写入（SPEC-M2 §2.3）：write_markdown / delete_markdown 与 ics 同口径——
写前备份到 <dir_name>/.backup/（滚动 10 份）、原子写、写后 frontmatter 回读校验。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import frontmatter

from app.core.contract import FRONTMATTER_KEYS
# slugify_title/TITLE_MAX/UNTITLED 定义在 core.uids（id 与文件名共用规则），此处转发
from app.core.uids import TITLE_MAX, UNTITLED, hex_suffix, slugify_title  # noqa: F401
from app.datastore.atomic import BACKUP_DIRNAME, AtomicWriteError, backup_file, safe_write

TIMELINE_DIR = "timeline"
EXCERPT_MAX = 80


@dataclass(frozen=True)
class MarkdownCollection:
    """一类 Markdown 文档集合的存储配置。

    - dir_name：用户数据根下的物理目录名（备忘 "memos"，未来笔记 "notes"）。
    - id_prefix：frontmatter id 前缀（备忘 "memo"，未来笔记 "note"）。
    - assets_dirname：图片资产子目录名（当前恒为 "assets"，预留参数化）。
    """

    dir_name: str
    id_prefix: str
    assets_dirname: str = "assets"


# 备忘集合（T1 唯一在用的集合；notes 配置预留给未来「笔记」模块，见 ADR 0001/0002）
MEMOS = MarkdownCollection(dir_name="memos", id_prefix="memo")

# 文件名：YYYY-MM-DD-标题.md
_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)\.md$")
# 正文首个一级标题 → 标题
_H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
# 摘要清洗：图片整段删、链接取文字、去强调/代码/方括号标记、空白折叠
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MARK_CHARS_RE = re.compile(r"[*_`\[\]]")
_WS_RE = re.compile(r"\s+")


def _is_table_separator(line: str) -> bool:
    """表格分隔行（如 | --- | :---: |）：含 | 且整行仅由 | - : 空白组成。"""
    return "|" in line and not re.sub(r"[\s|:\-]", "", line)


def _excerpt(body: str) -> str:
    """摘取正文第一段有效文本作为摘要（截断到 80 字）。

    富文本适配：跳过标题/引言/表格分隔行；图片行清空后继续下一行；
    链接取链接文字；表格竖线转空格。清理后为空的行继续向下找。
    """
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(">"):
            continue
        if _is_table_separator(line):
            continue
        text = _IMAGE_RE.sub("", line)
        text = _LINK_RE.sub(r"\1", text)
        text = _MARK_CHARS_RE.sub("", text)
        text = text.replace("|", " ")
        text = _WS_RE.sub(" ", text).strip()
        if not text:
            continue
        return text[:EXCERPT_MAX]
    return ""


def collection_dir(base_dir: Path, collection: MarkdownCollection) -> Path:
    """集合物理目录（base_dir/<dir_name>）；集合目录知识只留在 datastore 层。"""
    return Path(base_dir) / collection.dir_name


def _parse_doc(path: Path) -> dict | None:
    """解析单篇文档 → 领域 dict；文件名非法或解析失败返回 None（跳过）。"""
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


def list_markdown(base_dir: Path, collection: MarkdownCollection) -> list[dict]:
    """集合文档列表：按文件名日期倒序（新在前），同日按标题排序。"""
    coll_dir = collection_dir(base_dir, collection)
    if not coll_dir.exists():
        return []
    docs = [d for d in (_parse_doc(p) for p in coll_dir.glob("*.md")) if d]
    docs.sort(key=lambda d: (d["date"] or "", d["title"]), reverse=True)
    return docs


def find_markdown_path(base_dir: Path, collection: MarkdownCollection, doc_id: str) -> Path | None:
    """按 id 定位文档文件路径：优先 frontmatter id，其次文件名（去扩展名）。

    与 get_markdown 匹配规则一致；坏文件（frontmatter 解析失败）跳过。
    """
    coll_dir = collection_dir(base_dir, collection)
    if not coll_dir.exists():
        return None
    for p in coll_dir.glob("*.md"):
        try:
            meta = frontmatter.load(p).metadata
        except Exception:  # noqa: BLE001 坏文件跳过，与 list_markdown 容错一致
            continue
        if str(meta.get("id") or "") == doc_id or p.stem == doc_id:
            return p
    return None


def get_markdown(base_dir: Path, collection: MarkdownCollection, doc_id: str) -> dict | None:
    """单篇文档：优先 frontmatter id 匹配，其次文件名（去扩展名）匹配。"""
    path = find_markdown_path(base_dir, collection, doc_id)
    if path is None:
        return None
    doc = _parse_doc(path)
    if doc is None:
        return None
    post = frontmatter.load(path)
    return {**doc, "content": post.content.strip()}


# ---------------------------------------------------------------- 写入（M2）


def make_markdown_filename(
    base_dir: Path, collection: MarkdownCollection, date_str: str, title: str
) -> str:
    """生成不冲突的文档文件名：YYYY-MM-DD-<标题清洗>.md。

    同名冲突追加 -<4hex> 短后缀（SPEC-M2 §2.3）。
    """
    slug = slugify_title(title)
    coll_dir = collection_dir(base_dir, collection)
    name = f"{date_str}-{slug}.md"
    if not (coll_dir / name).exists():
        return name
    for _ in range(64):
        name = f"{date_str}-{slug}-{hex_suffix()}.md"
        if not (coll_dir / name).exists():
            return name
    raise AtomicWriteError(f"文档文件名冲突重试耗尽：{title}")


def _verify_doc(path: Path) -> None:
    """回读闸门：frontmatter 可重解析且契约三键（id/tags/related）齐全。"""
    post = frontmatter.load(path)
    missing = [k for k in FRONTMATTER_KEYS if k not in post.metadata]
    if missing:
        raise ValueError(f"frontmatter 缺少契约键：{missing}")


def write_markdown(
    base_dir: Path,
    collection: MarkdownCollection,
    filename: str,
    metadata: dict,
    body: str,
    old_path: Path | None = None,
) -> Path:
    """写文档（原子写 + 写前备份 <dir>/.backup/ 滚动 10 份 + 回读校验）。

    - metadata 需含契约三键 id/tags/related（可含 created）；键序即落盘序
      （dumps sort_keys=False），调用方按 id/created/tags/related 传入。
    - 覆盖已有同名文件时 safe_write 自动备份旧内容。
    - old_path：改标题重命名场景的旧文件路径，备份后删除（防新旧两份并存）。
    """
    coll_dir = collection_dir(base_dir, collection)
    coll_dir.mkdir(parents=True, exist_ok=True)
    path = coll_dir / filename
    post = frontmatter.Post(body, **metadata)
    raw = frontmatter.dumps(post, sort_keys=False).encode("utf-8")
    safe_write(path, raw, verify=_verify_doc, backup_dir=coll_dir / BACKUP_DIRNAME)
    if old_path is not None and Path(old_path) != path:
        backup_file(Path(old_path), coll_dir / BACKUP_DIRNAME)
        Path(old_path).unlink(missing_ok=True)
    return path


def delete_markdown(base_dir: Path, collection: MarkdownCollection, doc_id: str) -> Path:
    """物理删除文档文件（删除前备份，.backup/ 里可找回）。

    找不到抛 FileNotFoundError（service 层映射 404）。
    """
    path = find_markdown_path(base_dir, collection, doc_id)
    if path is None:
        raise FileNotFoundError(f"文档不存在: {doc_id}")
    backup_file(path, collection_dir(base_dir, collection) / BACKUP_DIRNAME)
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
