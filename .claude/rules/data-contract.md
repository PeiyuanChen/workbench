---
paths: ["backend/**"]
---

# 数据契约（严格遵守，样例见 data-samples/）

> 全局守则见仓库根 `CLAUDE.md`。本文件是后端（backend/**）读写开放数据文件时必须遵守的字段级契约。

## VTODO（待办）字段
- 必填：`UID`、`DTSTAMP`；常用：`SUMMARY`、`DESCRIPTION`、`STATUS`(NEEDS-ACTION/COMPLETED)、`CATEGORIES`、`PRIORITY`。
- **四象限标签**：`X-IMPORTANT:TRUE/FALSE`、`X-URGENT:TRUE/FALSE`（iCalendar 标准 X- 扩展）。
  - 四象限 = (IMPORTANT, URGENT) 两标签现算；与有无时间正交。
- **时间三阶段（全部可选，渐进）**：
  - 无 DTSTART 无 DUE = **未排期/未归类**（RFC5545：关联到每天直到完成）。
  - `DUE` = 截止时间点（不占时长）→ 日历显示为 ⚑ 小旗。
  - `DTSTART`+`DURATION` = 执行时间块（可跨小时/跨多天）→ 日历显示为 ▸ 色块；全天用 `VALUE=DATE`。
  - 可同时有 DUE 和执行块。
- **父子任务**：子任务 VTODO 用 `RELATED-TO;RELTYPE=CHILD:<父UID>` 关联父任务。
  - 子任务是完整待办，可独立设时间/标签/勾选；父任务进度 = 子任务完成率（如 2/3）。
  - **默认两级**，不做无限层级。轻量并列清单项写在 DESCRIPTION 的 Markdown `- [ ]` 里，不建子任务。

## VEVENT（日历事件）
- 标准字段：`DTSTART`、`DTEND`(或 DURATION)、`SUMMARY`、`LOCATION`、`DESCRIPTION`、`CATEGORIES`。
- 日历视图**只读聚合展示**：事件 + 待办执行块（DTSTART+DURATION）画色块 + DUE 画小旗；无时间待办不上日历。

## Markdown（备忘 / 时间线）
- 备忘 `notes/YYYY-MM-DD-标题.md`：frontmatter 含 `id,tags,related`，正文 Markdown。
- 时间线 `timeline/YYYY/MM.md`：同 Markdown 结构，正文是某月主线/决策/回顾。

## 时区
统一用 `TZID=Asia/Shanghai`；存储/传输注意 UTC 与本地时区转换。
