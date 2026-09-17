"""备忘写操作（SPEC-M2 §2.3 + 决策 D）。

语义：
- id = `YYYYMMDD-note-<标题清洗>`（保留中文，日期=创建日/上海钟面）；
  id 冲突追加 -<4hex> 短后缀。
- 文件名 = `YYYY-MM-DD-<标题清洗>.md`；同名冲突追加短后缀（md_store 负责）。
- 标题三源一致（frontmatter 首行 H1 承载标题 / 文件名承载清洗版 / _parse_note
  优先取 H1）：新建正文以 "# {title}" 开头（合 data-samples 惯例）；PUT 改标题
  同步替换首行 H1 并重命名文件（保留原创建日期前缀，id/created 不变），防"标题弹回"。
- PUT = 全文更新：tags/related 未传即重置为 []（与 SPEC "全文更新" 一致）。
- 写前备份 notes/.backup/（滚动 10 份）+ 原子写 + 回读闸门，全部由 md_store 承担。
"""

from __future__ import annotations

import re
from pathlib import Path

import frontmatter

from app.core.errors import ApiError, NotFound, ValidationFailed
from app.core.uids import hex_suffix, local_now, new_note_id
from app.datastore import md_store

# 标题长度上限（与待办 summary 同口径；文件名 slug 另有 60 字截断）
TITLE_MAX = 200

_FILENAME_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")


def _clean_title(value) -> str:
    """title 去空白后非空、≤200 字；内部换行/连续空白折叠为单空格（保 H1 单行）。"""
    s = " ".join(str(value or "").split())
    if not s:
        raise ValidationFailed("title 不能为空")
    if len(s) > TITLE_MAX:
        raise ValidationFailed(f"title 过长（≤{TITLE_MAX} 字）：当前 {len(s)} 字")
    return s


def _compose_body(title: str, content: str) -> str:
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


def _date_from_filename(name: str) -> str | None:
    m = _FILENAME_DATE_RE.match(name)
    return m.group(1) if m else None


def _load_note_or_500(base_dir: Path, note_id: str) -> dict:
    note = md_store.get_note(base_dir, note_id)
    if note is None:  # 理论不可达：刚写盘就读不到 = 严重错误
        raise ApiError(f"备忘写后读取失败: {note_id}", 500)
    return note


def create_note(base_dir: Path, payload: dict) -> dict:
    """新建备忘（POST /api/notes）→ 完整 note（含 content）。

    服务端生成 id 与文件名（SPEC-M2 §2.3）；created = 上海今天。
    """
    title = _clean_title(payload.get("title"))
    now = local_now()
    date_str = now.strftime("%Y-%m-%d")
    # id 冲突（同日同题）追加短后缀；文件名冲突由 make_note_filename 独立处理
    note_id = new_note_id(title, now)
    existing = {n["id"] for n in md_store.list_notes(base_dir)}
    while note_id in existing:
        note_id = f"{new_note_id(title, now)}-{hex_suffix()}"
    filename = md_store.make_note_filename(base_dir, date_str, title)
    metadata = {
        "id": note_id,
        "created": date_str,
        "tags": [str(t) for t in (payload.get("tags") or [])],
        "related": [str(r) for r in (payload.get("related") or [])],
    }
    md_store.write_note(base_dir, filename, metadata, _compose_body(title, payload.get("content") or ""))
    return _load_note_or_500(base_dir, note_id)


def update_note(base_dir: Path, note_id: str, payload: dict) -> dict:
    """全文更新（PUT /api/notes/{id}）→ 完整 note（含 content）。

    标题变更 → 重命名文件（保留原创建日期前缀），id/created 不变（决策 D）。
    """
    title = _clean_title(payload.get("title"))
    old_path = md_store.find_note_path(base_dir, note_id)
    if old_path is None:
        raise NotFound(f"备忘不存在: {note_id}")
    old_meta = dict(frontmatter.load(old_path).metadata)
    created = str(old_meta.get("created") or "") or _date_from_filename(old_path.name) \
        or local_now().strftime("%Y-%m-%d")
    date_prefix = _date_from_filename(old_path.name) or created[:10]
    metadata = {
        "id": str(old_meta.get("id") or note_id),  # 旧 id 不变（SPEC-M2 §2.3）
        "created": created,
        "tags": [str(t) for t in (payload.get("tags") or [])],
        "related": [str(r) for r in (payload.get("related") or [])],
    }
    # 目标文件名：优先原名（标题未变 → 原地覆盖）；被别的文件占用才走冲突后缀
    notes_dir = Path(base_dir) / md_store.NOTES_DIR
    new_filename = f"{date_prefix}-{md_store.slugify_title(title)}.md"
    occupant = notes_dir / new_filename
    if occupant.exists() and occupant != old_path:
        new_filename = md_store.make_note_filename(base_dir, date_prefix, title)
    md_store.write_note(
        base_dir, new_filename, metadata,
        _compose_body(title, payload.get("content") or ""),
        old_path=None if new_filename == old_path.name else old_path,
    )
    return _load_note_or_500(base_dir, metadata["id"])


def delete_note(base_dir: Path, note_id: str) -> dict:
    """物理删除（DELETE /api/notes/{id}）→ {"id","filename"}；删除前备份仍在 .backup/。"""
    try:
        path = md_store.delete_note(base_dir, note_id)
    except FileNotFoundError as e:
        raise NotFound(str(e)) from e
    return {"id": note_id, "filename": path.name}
