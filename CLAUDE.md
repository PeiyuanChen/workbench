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
3. 数据必须在**没有本应用**时也能被通用工具打开（记事本、Obsidian、Google/Apple 日历、任意 CalDAV 客户端）。
4. **视图 ≠ 数据**：四象限、时间线是从基础数据现场计算/生成的视图，不是独立存储结构。
5. 数据文件格式（字段、目录结构）如需变更，必须先停下来问用户，不得自行更改。

## 技术栈（已拍板，不要更换）

- **后端**：Python 3.11+ / FastAPI / Type hints。iCalendar 读写用 `icalendar` 库；Markdown frontmatter 用 `python-frontmatter`。
- **CalDAV 服务器**：Radicale（第三方，**M3 才接入**；M2 直读直写文件，见 SPEC-M2 决策 #7）。
- **前端**：Vue 3 + TypeScript + Vite（决策细节见 `frontend/CLAUDE.md`）。
- **不做**：用户注册/登录/权限/多租户（单用户）。微服务、消息队列等一律不要。

## 依赖纪律（后端单向依赖）

`api → service → datastore → 文件系统`，`core` 被各层引用。
下层不得 import 上层。所有文件访问必须经过 `core.data_root()`，**代码中禁止写死数据路径**。

## 数据契约

字段级契约（VTODO / VEVENT / Markdown / 时区）已移至 `.claude/rules/data-contract.md`（编辑 `backend/**` 时自动加载）；样例与校验器见 `data-samples/`。契约变更必须先问用户（见第一性原则第 5 条）。

## API（M2 可写，M3 加生成；M1 只读 GET 已完成）

M2 写：`POST/PATCH/DELETE /api/todos`（含 parent、DUE、DTSTART+DURATION、象限标签）、`POST/PATCH/DELETE /api/events`、`PUT/POST /api/notes`。
M3：`POST /api/timeline/generate?range=2026-03`（LLM 基于该范围待办+事件+备忘，用固定模板 prompt 生成，**落盘为 timeline md**，可重新生成、可手改）。

## 界面基准

五视图布局/交互基准已移至 `frontend/CLAUDE.md`（静态原型见 `prototype/index.html`）。

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
- **M2**：待办/事件/备忘可增删改（直读直写 .ics/.md，含原子写、备份、回读闸门，规格见 `SPEC-M2.md`）；父子任务、三阶段时间可写。Radicale 不在 M2。
  - 验收命令（后端启动后，git-bash 仓库根执行）：
    ```bash
    bash scripts/accept-m2.sh
    ```
    期望：全脚本退出码 0，末行输出 `[M2 验收通过]`。覆盖 SPEC-M2 §5 全部 7 步（新建→complete→
    scope=archived 归档区→数据主权闸门 validate.py→旧数据无损→备份滚动→备忘链→事件全天排他）
    + 自动清理验收临时数据。
    ⚠ 勿破坏脚本内两个 Windows 编码对策（实测踩坑）：`export PYTHONUTF8=1`（python 管道默认
    gbk 会把 UTF-8 响应解码成 mojibake）；中文 payload 一律 heredoc→stdin（`curl -d @-`，原生
    Windows curl 会按 GBK 转码命令行参数）。
- **M3**：时间线 LLM 生成 + 旧数据（TickTick 等）AI 迁入脚本；Radicale/CalDAV 接入、拖拽排期等 M2 未尽完善项。
- **M4**：自托管 + PWA 手机端 + 可选日历双向同步。

## 多用户扩展预留（现在单用户，但别埋雷）

- 不写登录/权限；但所有数据路径走 `core.data_root()`，目录用 `data/users/me/...` 起步。
- 将来加"每人私有工作台"只需：加认证 + data_root(user) + 查询过滤；业务逻辑不变。**协作式多用户不做、不预埋。**
