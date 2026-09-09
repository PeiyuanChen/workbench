import re, pathlib

ics = pathlib.Path(__file__).parent.joinpath("calendar.ics").read_text(encoding="utf-8")

# 极简解析(仅演示;生产用 icalendar 库或 CalDAV 服务器)
blocks = re.findall(r"BEGIN:(VEVENT|VTODO)(.*?)END:\1", ics, re.S)
events, todos = [], []
for kind, body in blocks:
    def g(name):
        m = re.search(rf"^{name}[^:]*:(.+)$", body, re.M)
        return m.group(1).strip() if m else ""
    item = {"SUMMARY": g("SUMMARY"), "DUE": g("DUE"), "DTSTART": g("DTSTART"),
            "IMP": g("X-IMPORTANT"), "URG": g("X-URGENT")}
    (events if kind == "VEVENT" else todos).append(item)

print("===== 日历事件（VEVENT）=====")
for e in events:
    print(f"  📅 {e['SUMMARY']}  起:{e['DTSTART'][:15]}")

print("\n===== 待办（VTODO）按四象限归位 =====")
def cell(imp, urg):
    return [t for t in todos if t["IMP"] == imp and t["URG"] == urg]
def has_time(t):
    return bool(t["DUE"] or t["DTSTART"])
q = [("重要且紧急（立即做）", "TRUE","TRUE"),
     ("重要不紧急（计划做）", "TRUE","FALSE"),
     ("紧急不重要（快做/委托）", "FALSE","TRUE"),
     ("不重要不紧急（有空再做）", "FALSE","FALSE")]
for label, i, u in q:
    ts = cell(i, u)
    print(f"\n【{label}】")
    for t in ts:
        when = "有排期" if has_time(t) else "无时间·收件箱"
        print(f"  • [{when}] {t['SUMMARY']}")

print("\n===== 未排期待办（无 DTSTART/DUE，RFC:关联到每一天直到完成）=====")
unscheduled = [t for t in todos if not has_time(t)]
for t in unscheduled:
    quad = "重要" if t["IMP"]=="TRUE" else "不重要"
    quad += "且紧急" if t["URG"]=="TRUE" else "不紧急"
    print(f"  • {t['SUMMARY']}   （{quad}）")
