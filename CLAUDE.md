# CLAUDE.md — 个人工作台（Local-First Workbench）

> 本文件是 Claude Code 在本仓库的最高工作守则。动手前务必通读。
> 完整背景见同目录 `概要设计-v1.md`、`技术方案-v1.md`、`data-samples/`、`prototype/index.html`。

## 项目是什么

一个**本地优先（local-first）的单用户个人工作台**，包含五个视图：
**四象限（艾森豪威尔优先级）、待办、日历、时间线、备忘**。
Web 先行（PWA），未来 iOS/Android 复用同一后端。

## 🚨 第一性原则：数据主权（不可违背）

1. **所有业务数据只能是开放纯文本格式**：
   - 待办 + 日历事件 → **iCalendar `.ics`**（RFC 5545，CalDAV 可同步）。
   - 备忘 + 时间线 → **Markdown**（带 YAML frontmatter）。
2. **禁止引入任何数据库**（不得用 SQLite/Postgres/MySQL 等）存储业务数据。
   后端只读写 `data/` 目录下的 `.ics`/`.md` 文件，**不持有私有数据模型**。
   违反此条 = 项目地基崩塌。
3. 数据必须在**没有本应用**时也能被通用工具打开（记事本、Obsidian、Google/Apple 日历、任意 CalDAV 客户端）。
4. **视图 ≠ 数据**：四象限、时间线是从基础数据现场计算/生成的视图，不是独立存储结构。
5. 数据文件格式（字段、目录结构）如需变更，必须先停下来问用户，不得自行更改。

## 技术栈（已拍板，不要更换）

- **后端**：Python 3.11+ / FastAPI / Type hints。iCalendar 读写用 `icalendar` 库；Markdown frontmatter 用 `python-frontmatter`。
- **CalDAV 服务器**：Radicale（第三方，M2 才接入；M1 直接读 .ics 文件，不启动它）。
- **前端**：Vue 3（Composition API + `<script setup>`）+ TypeScript + Vite + Tailwind CSS；状态 Pinia；PWA 用 `vite-plugin-pwa`；拖拽用 VueDraggable。
- **不做**：用户注册/登录/权限/多租户（单用户）。微服务、消息队列等一律不要。

## 目录结构（后端单向依赖）

```
workbench/
├─ backend/
│  └─ app/
│     ├─ api/        # HTTP 路由：接请求返 JSON，不含业务逻辑（routes_todos/events/notes/timeline）
│     ├─ service/    # 业务逻辑：四象限归位、时间线聚合、未排期过滤、父子任务进度
│     ├─ datastore/  # 唯一碰文件系统：ics_store.py(.ics读写)、md_store.py(.md读写)
│     └─ core/       # 配置、data_root() 路径解析、日志、数据契约常量
├─ frontend/        # Vue 3 + Vite 工程（M1 前端可先用 prototype/index.html 的静态版对照）
├─ data/            # ⚠️ 真实用户数据（开放格式文件）
│  └─ users/me/
│     ├─ calendar.ics
│     ├─ notes/           # YYYY-MM-DD-标题.md
│     └─ timeline/YYYY/MM.md
├─ data-samples/    # 参考样例（已用 icalendar 库校验通过，见 validate.py）
├─ prototype/       # 静态原型（布局/交互基准，index.html）
└─ CLAUDE.md
```

**依赖纪律**：`api → service → datastore → 文件系统`，`core` 被各层引用。
下层不得 import 上层。所有文件访问必须经过 `core.data_root()`，**代码中禁止写死数据路径**。

## 数据契约（严格遵守，样例见 data-samples/）

### VTODO（待办）字段
- 必填：`UID`、`DTSTAMP`；常用：`SUMMARY`、`DESCRIPTION`、`STATUS`(NEEDS-ACTION/COMPLETED)、`CATEGORIES`、`PRIORITY`。
- **四象限标签**：`X-IMPORTANT:TRUE/FALSE`、`X-URGENT:TRUE/FALSE`（iCalendar 标准 X- 扩展）。
  - 四象限 = (IMPORTANT, URGENT) 两标签现算；与有无时间正交。
- **时间三阶段（全部可选，渐进）**：
  - 无 DTSTART 无 DUE = **未排期/未归类**（RFC5545：关联到每天直到完成），界面**不得出现"收件箱"字样**。
  - `DUE` = 截止时间点（不占时长）→ 日历显示为 ⚑ 小旗。
  - `DTSTART`+`DURATION` = 执行时间块（可跨小时/跨多天）→ 日历显示为 ▸ 色块；全天用 `VALUE=DATE`。
  - 可同时有 DUE 和执行块。
- **父子任务**：子任务 VTODO 用 `RELATED-TO;RELTYPE=CHILD:<父UID>` 关联父任务。
  - 子任务是完整待办，可独立设时间/标签/勾选；父任务进度 = 子任务完成率（如 2/3）。
  - **默认两级**，不做无限层级。轻量并列清单项写在 DESCRIPTION 的 Markdown `- [ ]` 里，不建子任务。

### VEVENT（日历事件）
- 标准字段：`DTSTART`、`DTEND`(或 DURATION)、`SUMMARY`、`LOCATION`、`DESCRIPTION`、`CATEGORIES`。
- 日历视图**只读聚合展示**：事件 + 待办执行块（DTSTART+DURATION）画色块 + DUE 画小旗；无时间待办不上日历。

### Markdown（备忘 / 时间线）
- 备忘 `notes/YYYY-MM-DD-标题.md`：frontmatter 含 `id,tags,related`，正文 Markdown。
- 时间线 `timeline/YYYY/MM.md`：同 Markdown 结构，正文是某月主线/决策/回顾。

### 时区
统一用 `TZID=Asia/Shanghai`；存储/传输注意 UTC 与本地时区转换。

## API（M1 只读，M2 可写，M3 加生成）

M1 全部 GET：
- `GET /api/health`
- `GET /api/todos?view=quadrant|list&unscheduled=1&status=` → 返回含父子层级、象限、进度、时间三阶段
- `GET /api/events?month=YYYY-MM` → 聚合事件 + 待办执行块 + 截止标记
- `GET /api/timeline/{year}/{month}` → 读已生成的 md（无则返回空/提示未生成）
- `GET /api/notes`、`GET /api/notes/{id}`

M2 写：`POST/PATCH/DELETE /api/todos`（含 parent、DUE、DTSTART+DURATION、象限标签）、`POST/PATCH/DELETE /api/events`、`PUT/POST /api/notes`。
M3：`POST /api/timeline/generate?range=2026-03`（LLM 基于该范围待办+事件+备忘，用固定模板 prompt 生成，**落盘为 timeline md**，可重新生成、可手改）。

## 界面基准（见 prototype/index.html）

- 5 视图左侧导航：四象限 / 待办 / 日历 / 时间线 / 备忘。
- 四象限 2×2：红=重要紧急、蓝=重要不紧急、橙=紧急不重要、灰=都不；卡片显示标签、截止/时间块、未排期标记、子任务进度。
- 待办视图分"未排期·最近要做"与"已排期·近期"；复杂事项可展开子任务 + 进度条。
- 日历月视图：执行块=▸色块、跨多天=▣横跨、截止=⚑小旗、普通事件=●。
- 时间线：顶部范围切换（月/季/半年/年/自定义）+ "✨LLM 生成/重新生成"徽标；正文按主线/决策组织。
- "＋快速记录"框**仅出现在四象限、待办、备忘**三视图（待办/四象限记事，备忘记笔记）；时间线、日历无此框。

## 开发方式 / 质量要求

- **小步快跑**：一次做一个 package 或一个接口，跑通测试再下一步；不要一次性写完全部。
- 每个里程碑开工前先给实现计划（Plan），经确认再写。
- **测试**：pytest 覆盖 datastore（.ics/.md 读写往返不丢字段）与 service（象限归位、进度、时间线聚合）。
  关键校验：写出的 .ics 必须能被 `icalendar` 库重新解析（参考 data-samples/validate.py），Markdown frontmatter 往返一致。
- 时间线 LLM 生成在 M3，接口先留位但 M1/M2 不接外部模型。
- 代码注释与文档用**中文**（用户偏好）。
- Windows 环境；shell 是 git-bash（POSIX），但给原生 Windows 程序传路径用 `C:/...` 正斜杠。

## 验收纪律（不可跳过）

1. **"测试通过" ≠ 任务完成**。每个里程碑/功能的完成定义 = 功能正确（pytest 绿）**且**交付验收通过：真实数据走通默认使用路径（`data/users/me/`）。
2. **演示数据只放 `data/users/example/`**，禁止用演示数据宣告里程碑验收通过。
3. **完成声明必须附证据**：验收命令、实际输出（count/关键字段），而非"已验证"。
4. **每个里程碑在 CLAUDE.md 里写明一条可执行的验收命令**（curl/脚本 + 断言 + 期望输出）。

## 里程碑

- **M1**：FastAPI 读 `data/` 开放文件 → 返回只读 JSON；前端渲染五视图（可先对照静态原型用真实数据）。验收：能看到自己真实数据。
  - 验收命令（后端启动后执行）：
    ```bash
    curl -s "http://127.0.0.1:8000/api/todos?user=me" | python -c "
    import sys, json
    d = json.load(sys.stdin)
    assert d['count'] >= 3, f'待办数不足: {d[\"count\"]}'
    summaries = [t['summary'] for t in d['items']]
    assert any('Agent' in s for s in summaries), f'缺少真实待办: {summaries}'
    print(f'[M1 OK] count={d[\"count\"]}, 含子任务={sum(t[\"children_total\"] for t in d[\"items\"])}')
    "
    ```
    期望：退出码 0，输出 `[M1 OK] count=3, 含子任务=2`。退出码非 0 即验收失败。
- **M2**：接入 Radicale；待办/事件/备忘可增删改；父子任务、三阶段时间可写。
- **M3**：时间线 LLM 生成 + 旧数据（TickTick 等）AI 迁入脚本。
- **M4**：自托管 + PWA 手机端 + 可选日历双向同步。

## 多用户扩展预留（现在单用户，但别埋雷）

- 不写登录/权限；但所有数据路径走 `core.data_root()`，目录用 `data/users/me/...` 起步。
- 将来加"每人私有工作台"只需：加认证 + data_root(user) + 查询过滤；业务逻辑不变。**协作式多用户不做、不预埋。**
