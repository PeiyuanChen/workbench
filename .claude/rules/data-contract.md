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

## Markdown（备忘 / 笔记 / 时间线）
- 备忘 `memos/YYYY-MM-DD-标题.md`：frontmatter 固定四键 `id,created,tags,related`（落盘键序同序，无 updated 等额外键），id 前缀 `memo-`（如 `20260903-memo-workbench-arch`）；正文首行 H1 承载标题；图片资产 `memos/assets/`，正文以 `![](assets/<名>)` 引用。
- 笔记 `notes/`（ADR 0001/0002）：与备忘同构四键 frontmatter，id 前缀 `note-`（如 `20260903-note-k8s-intro`）；**不写 folder/updated 字段**，文件夹归属仅由文件相对路径表达。
  - 文件夹即 `notes/` 下真实子目录（支持中文与多层嵌套，根层允许散放）；保留名 `.backup`、`assets` 禁止作为文件夹名，禁止 `. / ..` 路径段与文件系统非法字符。
  - 文件名 `YYYY-MM-DD-<标题清洗>.md`，同文件夹同名冲突追加 `-<4hex>` 后缀；移动笔记只换目录，id 与文件名日期前缀不变。
  - 图片资产平铺于 `notes/assets/`（不随笔记进子目录），磁盘名带文件夹扁平前缀：段间以 `__` 连接并尾随 `__`（`k8s/网络` → `k8s__网络__<时间戳>-<8hex>.png`），根层笔记无前缀；正文按所在深度写相对链接（深度 2 → `../../assets/<名>`，根层 → `assets/<名>`），移动导致深度变化时服务端自动改写链接。
  - 写备份集中在 `notes/.backup/` 平铺，文件名带同样的文件夹前缀，滚动保留 10 份；原子写 + 回读闸门与备忘同原语。
  - 图片安全规则与备忘对等：5 MiB 上限、扩展名白名单 png/jpg/jpeg/gif/webp（SVG 排除）、magic byte 嗅探、路径穿越防护、服务端命名 write-once 不可变。
- 备忘与笔记共用参数化 Markdown 存储内核，差异仅在集合配置（目录名/id 前缀/资产基址），禁止两套近似实现。
- 时间线 `timeline/YYYY/MM.md`：同 Markdown 结构，正文是某月主线/决策/回顾。

## 时区
统一用 `TZID=Asia/Shanghai`；存储/传输注意 UTC 与本地时区转换。
