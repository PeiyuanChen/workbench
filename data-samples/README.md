# 个人工作台 · 开放数据层样例

这一套演示：**四象限 / 备忘 / 时间线 / 待办 / 日历** 五个视图，底层只用到两类开放格式。

## 数据只有两种文件

| 你看到的视图 | 底层数据格式 | 文件 |
|---|---|---|
| 待办（todo） | iCalendar `VTODO`（CalDAV 同步） | `calendar.ics` |
| 日历（事件） | iCalendar `VEVENT`（.ics） | `calendar.ics` |
| 四象限 | **不是独立数据**——就是待办上的两个标签 `X-IMPORTANT` / `X-URGENT` | 由 `calendar.ics` 生成 |
| 备忘 note | **Markdown** + YAML frontmatter | `notes/*.md` |
| 时间线 timeline | **Markdown**（按月一文件） | `timeline/YYYY/MM.md` |

## 目录结构

```
data-samples/
├─ calendar.ics                  # 待办 + 日历（CalDAV 标准，任何日历软件能打开）
├─ notes/                        # 备忘：一篇一个 .md
│  └─ 2026-09-03-工作台设计决策.md
└─ timeline/                     # 时间线：按月回溯
   └─ 2026/
      └─ 03.md
```

## 关键设计点

1. **四象限 = 视图，不是数据**。一个待办只多两个布尔标记，四象限界面是前端按这两个标记归位：

   |              | 紧急 URGENT=TRUE | 不紧急 URGENT=FALSE |
   |--------------|------------------|---------------------|
   | **重要 IMPORTANT=TRUE**  | 立即做（简历V2） | 计划做（回溯时间线） |
   | **不重要 IMPORTANT=FALSE** | 委托/快做 | 有空再做（读闲书） |

2. **.ics 是纯文本**，记事本就能开；Google/Apple/Outlook/Nextcloud/Vikunja 全都能导入。
3. **Markdown 是纯文本**，任何编辑器、任何年代都能读，Git 可版本化、可 diff。
4. 自定义字段以 `X-` 开头（`X-IMPORTANT`）是 iCalendar 标准允许的扩展，别的工具读不懂会忽略，不会报错。
5. note 和 timeline 里用 `uid:xxx` / `[[2026/03]]` 做相互链接，前端可渲染成跳转链接，但去掉前端它们也只是普通文字。

## 待办不需要时间（RFC 5545 官方支持）

- **只有日历事件（VEVENT）必须有时间**；**待办（VTODO）的 `DTSTART`/`DUE` 都是可选的**。
- RFC 5545 原文：*"A VTODO without the DTSTART and DUE (or DURATION) properties specifies a to-do that will be associated with each successive calendar date, until it is completed."* —— 即"没有时间的待办 = 一直挂着、直到完成"，正好对应你"最近要做、先不排期"的收件箱/想法。
- 一条待办**唯一必填**的只有 `UID` 和 `DTSTAMP`（创建时间戳，不等于截止日）。
- 所以"四象限"和"时间"完全解耦：想法进来先打 `X-IMPORTANT`/`X-URGENT` 归象限、不设时间；等你愿意排期时再补 `DUE`。本样例 6 条待办中 5 条无时间，已用真实 `icalendar` 库校验通过（`python validate.py` / `uv run --with icalendar python validate.py`）。
