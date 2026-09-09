"""数据契约校验脚本（standalone 可跑）。

用法：
    python validate.py                 # 校验 data-samples 自身
    python validate.py <目录>          # 校验指定用户数据目录（如 ../data/users/example）
    uv run --with icalendar python validate.py

校验项（任一失败即契约违规，退出码 1）：
  1. calendar.ics 可被 icalendar 严格解析
  2. UID 全局唯一（VTODO + VEVENT）
  3. VTODO 必有 UID/DTSTAMP 与 X-IMPORTANT/X-URGENT，且取值 ∈ {TRUE, FALSE}
  4. RELATED-TO（RELTYPE=CHILD）必须指向已存在的 UID
  5. VEVENT 必有 DTSTART，且 DTEND 与 DURATION 至少有一个
  6. notes/ 与 timeline/ 的 Markdown frontmatter 必含 id / tags / related

另打印信息性覆盖统计（不作为失败条件）：时间三阶段、父子任务样例覆盖情况。
"""

import re
import sys
from pathlib import Path

# Windows 控制台默认 GBK：统一按 UTF-8 输出，避免中文/符号乱码或崩溃
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001 某些嵌入式环境无 reconfigure
    pass

try:
    from icalendar import Calendar
except ImportError:
    sys.exit("缺少依赖：请 `uv run --with icalendar python validate.py` 或 pip install icalendar")


def str_of(v) -> str:
    return str(v) if v is not None else ""


def validate_calendar(path: Path, errors: list[str]) -> None:
    if not path.exists():
        errors.append(f"缺少 {path}")
        return
    raw = path.read_text(encoding="utf-8")
    try:
        cal = Calendar.from_ical(raw)
    except Exception as e:  # noqa: BLE001 解析失败即契约违规
        errors.append(f"{path.name} 无法被 icalendar 解析: {e}")
        return

    todos = list(cal.walk("VTODO"))
    events = list(cal.walk("VEVENT"))
    print(f"解析成功: {len(events)} 事件 / {len(todos)} 待办")

    # --- UID 唯一 ---
    uids: set[str] = set()
    for comp in todos + events:
        uid = str_of(comp.get("UID"))
        if not uid:
            errors.append(f"{comp.name} 缺少 UID: {str_of(comp.get('SUMMARY'))[:30]}")
            continue
        if uid in uids:
            errors.append(f"UID 重复: {uid}")
        uids.add(uid)

    # --- VTODO 契约 ---
    stats = {"no_time": 0, "due_only": 0, "block": 0, "all_day": 0, "child": 0, "both": 0}
    for t in todos:
        summary = str_of(t.get("SUMMARY"))[:30]
        if not t.get("DTSTAMP"):
            errors.append(f"VTODO 缺 DTSTAMP: {summary}")
        for key in ("X-IMPORTANT", "X-URGENT"):
            val = t.get(key)
            if val is None:
                errors.append(f"VTODO 缺 {key}: {summary}")
            elif str(val).upper() not in ("TRUE", "FALSE"):
                errors.append(f"{key} 取值非法（应 TRUE/FALSE）: {summary} -> {val}")
        # RELATED-TO 指向校验
        related = t.get("RELATED-TO")
        if related is not None:
            items = related if isinstance(related, list) else [related]
            for rt in items:
                if rt.params.get("RELTYPE", "PARENT") == "CHILD" and str(rt) not in uids:
                    errors.append(f"RELATED-TO 指向不存在的父任务: {summary} -> {rt}")
                if rt.params.get("RELTYPE") == "CHILD":
                    stats["child"] += 1
        # 时间三阶段统计
        has_due = t.get("DUE") is not None
        dtstart = t.get("DTSTART")
        if dtstart is None and not has_due:
            stats["no_time"] += 1
        else:
            if dtstart is not None and t.get("DURATION") is not None:
                stats["block"] += 1
                if has_due:
                    stats["both"] += 1
                dt = dtstart.dt if hasattr(dtstart, "dt") else dtstart
                if not hasattr(dt, "hour"):  # VALUE=DATE → 全天
                    stats["all_day"] += 1
            elif has_due:
                stats["due_only"] += 1
    print(
        "覆盖统计(信息性): 无时间 %(no_time)d | 仅DUE %(due_only)d | 执行块 %(block)d"
        "（其中块+DUE %(both)d、全天 %(all_day)d）| 子任务 %(child)d" % stats
    )

    # --- VEVENT 契约 ---
    for ev in events:
        summary = str_of(ev.get("SUMMARY"))[:30]
        if ev.get("DTSTART") is None:
            errors.append(f"VEVENT 缺 DTSTART: {summary}")
        if ev.get("DTEND") is None and ev.get("DURATION") is None:
            errors.append(f"VEVENT 缺 DTEND/DURATION（二者至少其一）: {summary}")


# frontmatter 键存在性：轻量正则即可（不引入 yaml 依赖）
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def validate_markdown(path: Path, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        errors.append(f"缺 YAML frontmatter: {path}")
        return
    block = m.group(1)
    for key in ("id", "tags", "related"):
        if not re.search(rf"^{key}\s*:", block, re.MULTILINE):
            errors.append(f"frontmatter 缺 {key}: {path}")


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
    target = target.resolve()
    print(f"校验目录: {target}\n")
    errors: list[str] = []

    validate_calendar(target / "calendar.ics", errors)

    md_files = sorted((target / "notes").glob("*.md")) if (target / "notes").exists() else []
    md_files += sorted((target / "timeline").rglob("*.md")) if (target / "timeline").exists() else []
    for md in md_files:
        validate_markdown(md, errors)
    print(f"Markdown 文件: {len(md_files)} 个")

    if errors:
        print(f"\n[FAIL] 发现 {len(errors)} 处契约违规:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("\n[OK] 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
