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

import os
import re
from dataclasses import dataclass
from pathlib import Path

import frontmatter

from app.core.contract import FRONTMATTER_KEYS
from app.core.errors import NotFound, ValidationFailed
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


# 备忘集合（平铺，无文件夹）
MEMOS = MarkdownCollection(dir_name="memos", id_prefix="memo")

# 笔记集合（T3：支持真实子目录分类，见 ADR 0001/0002）
NOTES = MarkdownCollection(dir_name="notes", id_prefix="note")

# 文件夹保留名（集合内部目录，禁止用户占用，ADR-0002）
RESERVED_FOLDER_NAMES = frozenset({BACKUP_DIRNAME, "assets"})
# 文件夹单段/整条路径长度上限（防 Windows 长路径与滥用）
FOLDER_SEGMENT_MAX = 200
FOLDER_PATH_MAX = 400
# 文件夹名单字符规则：复用 Windows 文件系统非法字符 + 控制字符（斜杠由 split 先消化）
_FOLDER_ILLEGAL_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

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


# ------------------------------------------------- 笔记文件夹（ADR-0002）
#
# 文件夹即 notes/ 下真实子目录，无 sidecar、无 frontmatter folder 字段：
# 笔记归属仅由文件相对路径表达。下列函数对任意集合通用，但目前只有 NOTES 启用。


def normalize_folder_path(folder: str) -> str:
    """校验并归一化文件夹相对路径；根层（散放）返回空串。

    拒绝：空段/点段（. ..）/保留名（.backup、assets）/文件系统非法字符/
    以点或空格结尾（Windows 不友好）/超长。不做静默改写——文件夹名是用户
    在资源管理器里直接可见的数据，名称不可预测比报错更糟。
    """
    raw = str(folder or "")
    if not raw.strip():
        return ""
    if raw != raw.strip():
        raise ValidationFailed("文件夹路径首尾不能有空白")
    # 宽容外层斜杠（"/a/b/" 视作 "a/b"）；连续斜杠产生空段，下面按非法拒绝
    s = raw.strip("/")
    if not s:
        return ""
    segments = s.split("/")
    if len(s) > FOLDER_PATH_MAX:
        raise ValidationFailed(f"文件夹路径过长（≤{FOLDER_PATH_MAX} 字）")
    for seg in segments:
        if not seg or not seg.strip():
            raise ValidationFailed("文件夹名不能为空段")
        if seg != seg.strip():
            raise ValidationFailed("文件夹名首尾不能有空白")
        if seg in (".", ".."):
            raise ValidationFailed("文件夹路径不能含 . 或 .. 段")
        if seg in RESERVED_FOLDER_NAMES:
            raise ValidationFailed(f"保留文件夹名不可用：{seg}")
        if _FOLDER_ILLEGAL_RE.search(seg):
            raise ValidationFailed("文件夹名含非法字符（尖括号/冒号/引号/斜杠/竖线/问号/星号/控制字符）")
        if seg.endswith((".", " ")):
            raise ValidationFailed("文件夹名不能以点或空格结尾")
        if len(seg) > FOLDER_SEGMENT_MAX:
            raise ValidationFailed(f"文件夹名单段过长（≤{FOLDER_SEGMENT_MAX} 字）")
    return "/".join(segments)


def folder_dir(base_dir: Path, collection: MarkdownCollection, folder: str) -> Path:
    """归一化文件夹 → 物理目录（不保证存在）；解析后越出集合目录一律拒绝。"""
    rel = normalize_folder_path(folder)
    coll = collection_dir(base_dir, collection).resolve()
    target = (coll / rel).resolve() if rel else coll
    if target != coll and not target.is_relative_to(coll):
        raise ValidationFailed("文件夹路径越界")
    return target


def ensure_folder_exists(base_dir: Path, collection: MarkdownCollection, folder: str) -> str:
    """归一化并确保文件夹真实存在；根层恒合法，非根不存在 → 422（不隐式建目录）。"""
    rel = normalize_folder_path(folder)
    if rel and not folder_dir(base_dir, collection, rel).is_dir():
        raise ValidationFailed(f"文件夹不存在：{rel}")
    return rel


def folder_depth(folder: str) -> int:
    """归一化文件夹相对路径的目录深度（根层 0，'a/b' 为 2）。"""
    rel = normalize_folder_path(folder)
    return len(rel.split("/")) if rel else 0


def depth_prefix(folder: str) -> str:
    """文件夹深度对应的正文相对链接前缀（根层 ''，深度 2 → '../../'）。"""
    return "../" * folder_depth(folder)


def list_folders(base_dir: Path, collection: MarkdownCollection) -> list[dict]:
    """递归列举真实子目录 → [{path, name}]，按 path 排序；保留名子树整体排除。"""
    coll = collection_dir(base_dir, collection)
    if not coll.exists():
        return []
    folders: list[dict] = []
    for p in coll.rglob("*"):
        if not p.is_dir():
            continue
        parts = p.relative_to(coll).parts
        if any(part in RESERVED_FOLDER_NAMES for part in parts):
            continue
        rel = "/".join(parts)
        folders.append({"path": rel, "name": parts[-1]})
    folders.sort(key=lambda f: f["path"])
    return folders


def create_folder(base_dir: Path, collection: MarkdownCollection, folder: str) -> dict:
    """新建文件夹（支持多层嵌套，中间层一并创建）；已存在 → 422。"""
    rel = normalize_folder_path(folder)
    if not rel:
        raise ValidationFailed("文件夹名不能为空")
    target = folder_dir(base_dir, collection, rel)
    if target.exists():
        raise ValidationFailed(f"文件夹已存在：{rel}")
    try:
        target.mkdir(parents=True, exist_ok=False)
    except OSError as e:
        # 中间段是已有文件（a.md/sub）等文件系统冲突：统一走中文 422 契约，不裸 500
        raise ValidationFailed(f"文件夹路径与已有文件冲突：{rel}") from e
    return {"path": rel, "name": rel.split("/")[-1]}


def rename_folder(
    base_dir: Path, collection: MarkdownCollection, folder: str, new_folder: str
) -> dict:
    """同父目录重命名（os.replace 原子改目录名）；内部笔记内容零改动。

    跨父目录移动会改变笔记深度、需批量改写正文资产链接，不在本端点语义内，
    显式 422 拒绝（移动单篇笔记走 PUT folder）。
    """
    rel = normalize_folder_path(folder)
    new_rel = normalize_folder_path(new_folder)
    if not rel or not new_rel:
        raise ValidationFailed("文件夹名不能为空")
    src = folder_dir(base_dir, collection, rel)
    if not src.is_dir():
        raise NotFound(f"文件夹不存在：{rel}")
    old_parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
    new_parent = new_rel.rsplit("/", 1)[0] if "/" in new_rel else ""
    if old_parent != new_parent:
        raise ValidationFailed("重命名仅限同父目录，不能跨目录移动文件夹")
    dst = folder_dir(base_dir, collection, new_rel)
    if dst.exists():
        raise ValidationFailed(f"目标文件夹已存在：{new_rel}")
    os.replace(src, dst)
    return {"path": new_rel, "name": new_rel.split("/")[-1]}


def delete_folder(base_dir: Path, collection: MarkdownCollection, folder: str) -> None:
    """删除空文件夹；非空 → 422 中文提示，不存在 → 404，保留名/根目录 → 422。"""
    rel = normalize_folder_path(folder)
    if not rel:
        raise ValidationFailed("集合根目录不可删除")
    target = folder_dir(base_dir, collection, rel)
    if not target.is_dir():
        raise NotFound(f"文件夹不存在：{rel}")
    if any(target.iterdir()):
        raise ValidationFailed(f"文件夹非空，清空后才能删除：{rel}")
    target.rmdir()


# ------------------------------------------------- 笔记递归读写（NOTES 专用）


def _iter_note_files(base_dir: Path, collection: MarkdownCollection):
    """递归枚举集合内 .md 文件；保留名子树（.backup/assets）整体跳过。"""
    coll = collection_dir(base_dir, collection)
    if not coll.exists():
        return
    for p in coll.rglob("*.md"):
        parts = p.relative_to(coll).parts
        if any(part in RESERVED_FOLDER_NAMES for part in parts[:-1]):
            continue
        yield p


def list_notes(base_dir: Path, collection: MarkdownCollection) -> list[dict]:
    """递归列举笔记（摘要形状，附 folder 字段；根层 folder 为空串）。

    排序沿用备忘内核：文件名日期倒序、同日按标题。
    """
    coll = collection_dir(base_dir, collection)
    docs: list[dict] = []
    for p in _iter_note_files(base_dir, collection):
        doc = _parse_doc(p)
        if doc is None:
            continue
        doc["folder"] = "/".join(p.relative_to(coll).parts[:-1])
        docs.append(doc)
    docs.sort(key=lambda d: (d["date"] or "", d["title"]), reverse=True)
    return docs


def find_note_path(base_dir: Path, collection: MarkdownCollection, doc_id: str) -> Path | None:
    """全树按 id 定位笔记：优先 frontmatter id，其次文件名（去扩展名）；坏文件跳过。"""
    for p in _iter_note_files(base_dir, collection):
        try:
            meta = frontmatter.load(p).metadata
        except Exception:  # noqa: BLE001 坏文件跳过，与 list_notes 容错一致
            continue
        if str(meta.get("id") or "") == doc_id or p.stem == doc_id:
            return p
    return None


def get_note(base_dir: Path, collection: MarkdownCollection, doc_id: str) -> dict | None:
    """单篇笔记：列表字段 + content + folder；找不到/坏文件返回 None。"""
    path = find_note_path(base_dir, collection, doc_id)
    if path is None:
        return None
    doc = _parse_doc(path)
    if doc is None:
        return None
    coll = collection_dir(base_dir, collection)
    doc["folder"] = "/".join(path.relative_to(coll).parts[:-1])
    post = frontmatter.load(path)
    return {**doc, "content": post.content.strip()}


# 正文 Markdown 资产链接：兼容 ../、./ 裸写三种相对前缀，以及尖括号目标 <...>
# 与链接标题（"t"）；同时覆盖图片 ![]( 与普通链接 [](。非 assets 目标不命中。
_ASSET_LINK_RE = re.compile(
    r"(!?\[[^\]]*\]\()(<)?(?:\.\./|\./)*(assets/[^)\s>]+)(>)?(\s+\"[^\"]*\")?(\))"
)


def rewrite_asset_links(body: str, new_depth: int) -> str:
    """把正文内 assets 相对链接统一改写为新目录深度的相对前缀。

    笔记在文件夹间移动、深度变化时调用：旧链接的 ../|./ 层数不剥除只归一化，
    目标统一为 ("../" * new_depth) + "assets/..."；根层 new_depth=0 即裸
    assets/...（与备忘写法一致）。尖括号与标题原样保留；非 assets 链接
    （外链/相邻文档）原样保留。
    """
    prefix = "../" * new_depth
    return _ASSET_LINK_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2) or ''}{prefix}{m.group(3)}"
        f"{m.group(4) or ''}{m.group(5) or ''}{m.group(6)}",
        body,
    )


def folder_flat_prefix(folder: str) -> str:
    """文件夹 → 扁平备份/资产名前缀：'k8s/网络' → 'k8s__网络__'；根层 → ''。"""
    rel = normalize_folder_path(folder)
    return "__".join(rel.split("/")) + "__" if rel else ""


def make_note_filename(
    base_dir: Path,
    collection: MarkdownCollection,
    folder: str,
    date_str: str,
    title: str,
) -> str:
    """目标文件夹内不冲突的笔记文件名：YYYY-MM-DD-<标题清洗>.md（冲突加 4hex 后缀）。

    冲突作用域是所在文件夹：不同文件夹允许同名文件。
    """
    target_dir = folder_dir(base_dir, collection, folder)
    slug = slugify_title(title)
    name = f"{date_str}-{slug}.md"
    if not (target_dir / name).exists():
        return name
    for _ in range(64):
        name = f"{date_str}-{slug}-{hex_suffix()}.md"
        if not (target_dir / name).exists():
            return name
    raise AtomicWriteError(f"笔记文件名冲突重试耗尽：{title}")


def write_note(
    base_dir: Path,
    collection: MarkdownCollection,
    folder: str,
    filename: str,
    metadata: dict,
    body: str,
    old_path: Path | None = None,
) -> Path:
    """写笔记到指定文件夹（原子写 + 写前备份 + 回读闸门，规则同 write_markdown）。

    备份集中在集合根 .backup/ 平铺，文件名带文件夹前缀（根层无前缀）；
    old_path 为移动/重命名场景的旧文件，按其自身所在文件夹前缀备份后删除。
    """
    rel = normalize_folder_path(folder)
    coll_dir = collection_dir(base_dir, collection)
    target_dir = folder_dir(base_dir, collection, rel)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / filename
    post = frontmatter.Post(body, **metadata)
    raw = frontmatter.dumps(post, sort_keys=False).encode("utf-8")
    safe_write(
        path, raw, verify=_verify_doc,
        backup_dir=coll_dir / BACKUP_DIRNAME,
        name_prefix=folder_flat_prefix(rel),
    )
    if old_path is not None and Path(old_path) != path:
        old_folder = "/".join(Path(old_path).relative_to(coll_dir).parts[:-1])
        backup_file(
            Path(old_path), coll_dir / BACKUP_DIRNAME,
            name_prefix=folder_flat_prefix(old_folder),
        )
        Path(old_path).unlink(missing_ok=True)
    return path


def delete_note(base_dir: Path, collection: MarkdownCollection, doc_id: str) -> Path:
    """物理删除笔记（删除前按文件夹前缀备份到扁平 .backup/）；找不到抛 FileNotFoundError。"""
    path = find_note_path(base_dir, collection, doc_id)
    if path is None:
        raise FileNotFoundError(f"笔记不存在: {doc_id}")
    coll_dir = collection_dir(base_dir, collection)
    folder = "/".join(path.relative_to(coll_dir).parts[:-1])
    backup_file(
        path, coll_dir / BACKUP_DIRNAME,
        name_prefix=folder_flat_prefix(folder),
    )
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
