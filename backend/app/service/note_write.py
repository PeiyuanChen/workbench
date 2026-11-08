"""笔记写操作（#4；ADR-0001 同构契约 + ADR-0002 真实文件夹）。

与备忘的差异只在集合配置（NOTES：目录 notes/、id 前缀 note-）与文件夹能力：
- id = `YYYYMMDD-note-<标题清洗>`，全树唯一性校验（跨文件夹查重）；
- 文件夹归属仅由物理相对路径表达，frontmatter 不写 folder 字段；
- 每次写入都把正文 assets 链接归一到所在文件夹深度，移动改变深度时
  链接自动改写（rewrite_asset_links 定深幂等），保证通用 Markdown 工具打开不裂图；
- 备份集中在 notes/.backup/ 扁平存放，文件名带文件夹前缀，滚动 10 份。
"""

from __future__ import annotations

from pathlib import Path

import frontmatter

from app.core.errors import ApiError, NotFound
from app.core.uids import hex_suffix, local_now, new_doc_id
from app.datastore import md_store
from app.datastore.md_store import NOTES
from app.service.markdown_docs import clean_title, compose_body, date_from_filename


def _load_note_or_500(base_dir: Path, note_id: str) -> dict:
    note = md_store.get_note(base_dir, NOTES, note_id)
    if note is None:  # 理论不可达：刚写盘就读不到 = 严重错误
        raise ApiError(f"笔记写后读取失败: {note_id}", 500)
    return note


def _metadata(payload: dict, note_id: str, created: str) -> dict:
    """frontmatter 固定四键、固定落盘序（id/created/tags/related），不出现 folder/updated。"""
    return {
        "id": note_id,
        "created": created,
        "tags": [str(t) for t in (payload.get("tags") or [])],
        "related": [str(r) for r in (payload.get("related") or [])],
    }


def create_note(base_dir: Path, payload: dict) -> dict:
    """新建笔记（POST /api/notes）→ 完整 note（含 content、folder）。"""
    title = clean_title(payload.get("title"))
    folder = md_store.ensure_folder_exists(base_dir, NOTES, payload.get("folder") or "")
    now = local_now()
    date_str = now.strftime("%Y-%m-%d")
    # id 全树唯一（同日同题即使在不同文件夹也追加短后缀区分身份）
    note_id = new_doc_id(NOTES.id_prefix, title, now)
    existing = {d["id"] for d in md_store.list_notes(base_dir, NOTES)}
    while note_id in existing:
        note_id = f"{new_doc_id(NOTES.id_prefix, title, now)}-{hex_suffix()}"
    filename = md_store.make_note_filename(base_dir, NOTES, folder, date_str, title)
    depth = len(folder.split("/")) if folder else 0
    body = md_store.rewrite_asset_links(
        compose_body(title, payload.get("content") or ""), depth
    )
    md_store.write_note(base_dir, NOTES, folder, filename, _metadata(payload, note_id, date_str), body)
    return _load_note_or_500(base_dir, note_id)


def update_note(base_dir: Path, note_id: str, payload: dict, folder_given: bool) -> dict:
    """全文更新（PUT /api/notes/{id}）；载荷含 folder 时移动，只换目录不改 id/日期前缀。"""
    title = clean_title(payload.get("title"))
    old_path = md_store.find_note_path(base_dir, NOTES, note_id)
    if old_path is None:
        raise NotFound(f"笔记不存在: {note_id}")
    coll_dir = md_store.collection_dir(base_dir, NOTES)
    current_folder = "/".join(old_path.relative_to(coll_dir).parts[:-1])
    target_folder = (
        md_store.ensure_folder_exists(base_dir, NOTES, payload.get("folder") or "")
        if folder_given
        else current_folder
    )

    old_meta = dict(frontmatter.load(old_path).metadata)
    created = str(old_meta.get("created") or "") or date_from_filename(old_path.name) \
        or local_now().strftime("%Y-%m-%d")
    date_prefix = date_from_filename(old_path.name) or created[:10]
    metadata = _metadata(payload, str(old_meta.get("id") or note_id), created)

    depth = len(target_folder.split("/")) if target_folder else 0
    body = md_store.rewrite_asset_links(
        compose_body(title, payload.get("content") or ""), depth
    )

    # 目标文件名：优先同名（原地覆盖/平搬）；被别的文件占用才走冲突后缀
    target_dir = md_store.folder_dir(base_dir, NOTES, target_folder)
    new_filename = f"{date_prefix}-{md_store.slugify_title(title)}.md"
    occupant = target_dir / new_filename
    if occupant.exists() and occupant != old_path:
        new_filename = md_store.make_note_filename(base_dir, NOTES, target_folder, date_prefix, title)
    moved_or_renamed = target_folder != current_folder or new_filename != old_path.name
    md_store.write_note(
        base_dir, NOTES, target_folder, new_filename, metadata, body,
        old_path=old_path if moved_or_renamed else None,
    )
    return _load_note_or_500(base_dir, metadata["id"])


def delete_note(base_dir: Path, note_id: str) -> dict:
    """物理删除（DELETE /api/notes/{id}）→ {"id","filename"}；删除前带文件夹前缀备份。"""
    try:
        path = md_store.delete_note(base_dir, NOTES, note_id)
    except FileNotFoundError as e:
        raise NotFound(str(e)) from e
    return {"id": note_id, "filename": path.name}


# ------------------------------------------------- 文件夹端点编排（薄封装）


def create_folder(base_dir: Path, folder: str) -> dict:
    return md_store.create_folder(base_dir, NOTES, folder)


def rename_folder(base_dir: Path, folder: str, new_folder: str) -> dict:
    return md_store.rename_folder(base_dir, NOTES, folder, new_folder)


def delete_folder(base_dir: Path, folder: str) -> None:
    md_store.delete_folder(base_dir, NOTES, folder)
