# M2 实现规格（SPEC-M2）

> 状态：**已实现并通过验收**（2026-09-14，`bash scripts/accept-m2.sh` 全绿）。
> 文中标注〔修订〕的条目为 2026-09-14 实现期经用户拍板/验证后的规格回改（原留白或矛盾处的定稿）。
> 本文件是 M2 的唯一规格来源；与 CLAUDE.md 同级遵守。冲突时以本文件为准并回头修订 CLAUDE.md。
>
> 范围一句话：在 M1 只读基础上，后端直读直写 `.ics`/`.md` 实现待办/事件/备忘的增删改，
> 前端接通快速记录与编辑交互；**不接 Radicale、不做拖拽改时间**（Radicale 接入、拖拽排期等
> 完善项统一推迟到 M3，本项目不设 M2.1/M2.5 等中间版本）。

## 1. 已拍板决策（不可自行变更）

| # | 决策点 | 结论 |
|---|---|---|
| 1 | 完成/放弃 | 三态：`NEEDS-ACTION` / `COMPLETED` / `CANCELLED`；放弃 = `STATUS:CANCELLED`（RFC 5545 标准值，外部日历显示"已取消"，自家 UI 文案显示"已放弃"）。**不使用非标准的 ABANDONED 状态值，不加 X-ABANDONED 扩展**（未知 STATUS 在外部日历会被当成未完成，违反数据主权；单一标准值最简） |
| 2 | UID | `YYYYMMDDTHHMMSS-<4位hex>@workbench.local`，如 `20260911T173000-a7f3@workbench.local`；时间用 Asia/Shanghai 本地钟面，4 位 hex 用 `secrets.token_hex(2)` |
| 3 | 写入安全 | ① 原子写：临时文件 `calendar.ics.tmp` → flush+`os.fsync` → `os.replace()` 原子替换；② 写前备份：旧文件复制到 `data/users/<user>/.backup/calendar-<UTC时间戳>.ics`，每用户滚动保留最近 **10 份**，超量删最旧；③ **写后回读**：新文件立即用 `Calendar.from_ical()` 重新解析，解析失败=文件损坏，恢复备份并返回 500（回读只验证文件合法性；"改动是否只动了该动的"语义正确性靠 §3 的往返 diff 测试保证）；④ 备份目录是数据目录内部实现，API 永不读取/展示它 |
| 4 | 时间输入 | 全量时间：日期时间选择器，DUE 可精确到分钟；全天事项用 `VALUE=DATE`；写回统一 `TZID=Asia/Shanghai` |
| 5 | 快速记录（待办） | 输入框 + **重要/紧急两个 toggle 按钮**（默认都 FALSE），回车即创建为未排期待办。**不做文本符号解析**（无 `!`/`?`/`#tag` 魔法语法）；分类标签 M2 暂不在快速记录里输入 |
| 6 | 快速记录（备忘） | 输入标题回车 → 创建 md（frontmatter 含 id/tags:[]/related:[]/created）→ 打开正文编辑 |
| 7 | CalDAV | M2 不接 Radicale，后端直接读写文件 |
| 8 | 实体范围 | 待办、备忘、**事件**全部支持增删改；事件表单入口在日历页（快速记录框不建事件） |
| 9 | 完结呈现 | COMPLETED/CANCELLED 默认从主列表消失；提供"已完成"归档区（含放弃项，视觉区分）可查看、可恢复 |
| 10 | 编辑入口 | M2 提供卡片编辑面板：改时间（DUE / DTSTART+DURATION）、象限两标签、描述、父子关系；删除（物理移除）仅在编辑面板"更多"里，二次确认 |

补充语义：

- **物理删除保留**：编辑面板里的"删除"= 从 ics 移除组件（区别于放弃）。放弃可恢复（状态翻转），物理删除不可恢复，但写前备份仍在 `.backup/`。
- **勾选完成**：勾选动作写 `STATUS:COMPLETED` + `COMPLETED:<UTC时间戳>`；取消勾选翻回 `NEEDS-ACTION` 并移除 COMPLETED。
- **放弃动作**：写 `STATUS:CANCELLED`；恢复时翻回 NEEDS-ACTION。
- 父任务进度 = 子任务中 `STATUS:COMPLETED` 占比（CANCELLED 不计入分母——放弃的子任务不拖累进度）。
  〔修订：M1 原口径确为 CANCELLED 计入分母（`build_tree` 用 `len(children)` 做分母），已按本规格修正；
  实现细节：`children[]` 仍含全部子任务（前端"已放弃"样式需要），`children_total` 只计非 CANCELLED，
  新增 `children_cancelled` 字段；全部子任务被放弃时 progress=None〕

## 2. API 契约

所有写接口：JSON 请求/响应；`user` 查询参数沿用 M1（缺省 me，example 允许写但 UI 标"示例数据"）。
响应统一信封：`{"ok": true, "data": <对象或列表>}`；错误：HTTP 4xx/5xx + `{"detail": "中文错误信息"}`。
**写操作成功后返回受影响对象的完整最新视图**（GET 单条同构），前端直接替换 store 数据。

### 2.1 待办

| 方法路径 | 语义 |
|---|---|
| `POST /api/todos` | 新建。body：`summary`(必填)、`description?`、`important?`、`urgent?`、`due?`、`dtstart?`、`duration_minutes?`、`all_day?`、`categories?`、`parent_uid?`。服务端生成 uid/dtstamp/created |
| `PATCH /api/todos/{uid}` | 局部更新；可改上述任意业务字段。**不接受 `status`（传入→422，detail 指引专用动作）**〔修订：消除原文与"完成/放弃走专用动作"的矛盾〕；显式 null = 清除字段 |
| `POST /api/todos/{uid}/complete` | 勾选完成（幂等：已完成再调无副作用，不落盘不产生备份） |
| `POST /api/todos/{uid}/reopen` | 取消完成；**兼作放弃项的恢复入口**（CANCELLED → NEEDS-ACTION，清 COMPLETED）〔修订〕 |
| `POST /api/todos/{uid}/abandon` | 放弃（STATUS:CANCELLED，清 COMPLETED——放弃不是完成） |
| `DELETE /api/todos/{uid}` | 物理删除，**级联删除全部子任务**〔修订：用户拍板，原规格未定〕；二次确认在前端且确认文案列出将被级联删除的子任务；返回 `{"deleted":[uid...]}` |

归档过滤〔修订：补齐 §5 第 2 步留白的参数设计〕：`GET /api/todos?scope=active|archived|all`，
缺省 `active`（顶层排除 COMPLETED/CANCELLED，即决策 #9 的"默认从主列表消失"由后端保证）；
`archived` 只返回顶层完成+放弃项（归档区数据源）；`all` 保留 M1 行为（验收比对用）。
scope 只作用于顶层，父任务 `children[]` 不受影响（完成/放弃的子任务照常显示在父节点内）。

校验规则（不满足 → 422，中文 detail）：

- `summary` 去空白后非空，长度 ≤ 200
- `due` / `dtstart` 接受 ISO 8601（`YYYY-MM-DD` 或带时区 datetime；无时区按 Asia/Shanghai 解释）
- 同时有 `dtstart` 与 `due` 时，`due >= dtstart`
- `duration_minutes` 正整数；与 `dtstart` 成对（只有 duration 没有 dtstart → 422）
- `parent_uid` 必须存在且不能是自己/自己的后代（防环）；父子保持两级，给一个已经是子任务的 uid 再挂子任务 → 422，detail 说明"默认两级"
- uid 冲突（理论不该发生）→ 500 并保留旧文件

### 2.2 事件

| 方法路径 | 语义 |
|---|---|
| `GET /api/events/{uid}` | 单条事件详情〔修订补充：月聚合项缺 dtend/description/alarms，编辑表单必需的数据源〕 |
| `POST /api/events` | 新建：`summary` 必填，`dtstart` 必填，`dtend` 与 `duration_minutes` 二选一（都不给默认 dtstart+30 分钟；**全天事件缺省 dtend=dtstart+1 天**〔修订〕）；`location?`、`description?`、`categories?`、`all_day?` |
| `PATCH /api/events/{uid}` | 局部更新（显式 null：dtend 清除后按缺省规则重算） |
| `DELETE /api/events/{uid}` | 物理删除；返回 `{"deleted":[uid]}` |

dtend 语义定稿〔修订〕：API 的 `dtend` **恒为 RFC 5545 排他语义**（GET/POST 对称，后端不做 ±1 天）；
"前端选择器呈现含首尾、提交 +1 天/回显 −1 天"的转换由前端 EventForm 承担（已有专项测试
`test_post_event_all_day_exclusive_dtend` 锁死排他存储 ↔ 含首尾呈现的往返）。

校验：`dtend > dtstart`；全天事件用纯日期，dtend 按 RFC5545 排他日语义（前端选择器呈现为含首尾，序列化时结束日 +1 天——此细节实现计划中需明确测试覆盖）。

### 2.3 备忘

| 方法路径 | 语义 |
|---|---|
| `POST /api/notes` | 新建：`title` 必填、`content?`（正文 markdown）、`tags?`、`related?`；服务端生成 id 与文件名 `YYYY-MM-DD-<标题清洗>.md`，同名追加短后缀 |
| `PUT /api/notes/{id}` | 全文更新（tags/related 未传即重置为空）；标题变更时同步重命名文件并**保留原创建日期前缀**，旧 id/created 不变〔修订〕 |
| `DELETE /api/notes/{id}` | 物理删除 md 文件（删除前备份） |

id 与标题清洗规则定稿〔修订：用户拍板" id 含中文标题"〕：
`id = YYYYMMDD-note-<标题清洗>`（日期=创建日/上海钟面）；标题清洗 = 只去文件系统非法字符
`<>:"/\|?*` 与控制字符、空白折叠为 `-`、**保留中文**、截断 60 字、空回退"未命名"；
id/文件名同名冲突追加 `-<4hex>` 短后缀。标题三源一致：frontmatter（经首行 H1）承载原标题、
文件名承载清洗版、正文以 `# {title}` 开头（合 data-samples 惯例），PUT 改标题时同步替换首行 H1 防"标题弹回"。

备忘同样做写前备份：复制到 `notes/.backup/`（滚动 10 份）；原子写同待办。

## 3. datastore / service 约束

- 写操作走 **read-modify-write**：`read_calendar()` → 在内存 list 中增删改 → `write_calendar()`，全程不手拼 ics 文本。
- `write_calendar` 改为：先备份旧文件（存在时）→ 原子写新文件。**写完必须立即 `Calendar.from_ical()` 回读校验**，回读失败视为严重错误：恢复备份、返回 500、记录日志（这是数据主权底线的运行时闸门，比测试更硬）。
- 序列化后"未被修改的组件"必须字段无损：M2 测试要求对每个写操作做**往返 diff 断言**（抓 M1 已有的真实 5 待办数据做 fixture，改一条、其余逐条比对关键字段）。
- 单用户本地工具，M2 不做并发锁；但 read-modify-write 全程在一个函数内完成，不要把读到的数据缓存进模块全局。
- 禁止写入/删除 `.backup/` 之外的任何额外目录；路径必须继续全部经过 `core.data_root()`。

## 4. 前端范围

1. 快速记录框落地（三视图）：待办输入框 + 重要/紧急 toggle + 回车；备忘标题回车建笔记并打开编辑。
2. 待办卡片：勾选框真实可用（complete/reopen）；编辑面板（时间、标签、描述、父任务、放弃/删除）；归档区（默认隐藏已完成/已放弃，可展开；放弃项样式区分；两者都可恢复）。
3. 日历页：事件新建/编辑/删除表单（月视图点击某天或"＋事件"）；DUE 小旗和执行块点击能打开对应待办编辑。
4. store：每个写 action 成功后用响应数据替换本地状态；失败显示后端中文 detail，不做乐观更新（M2 优先正确性）。
5. 继续遵守 `frontend/CLAUDE.md` 全部界面基准（未排期禁止"收件箱"字样、⚑▸▣● 语义等）。

## 5. 验收（M2 完成定义）

功能正确：pytest 全绿（含新增写操作测试、往返 diff 测试、校验 422 测试、回读失败恢复测试）；
前端 vue-tsc + build 通过。交付验收〔修订：骨架已补全落地为可执行脚本〕：

```bash
# 后端启动后，git-bash 仓库根执行（期望：退出码 0，末行输出 [M2 验收通过]）
bash scripts/accept-m2.sh
```

脚本覆盖原骨架全部 7 步 + 自动清理（trap 兜底，验收临时数据不残留在 me/）：
1. 新建带 due 的重要待办（断言 important/due/quadrant/status/created）；
2. 端到端：active 可见 → complete 消失 → **scope=archived** 归档区可见 → complete 幂等（时间戳不变）
   → reopen 清除 COMPLETED → abandon → 放弃项可恢复；
3. 数据主权闸门：calendar.ics 可被 icalendar 严格解析 + `data-samples/validate.py` 契约全绿；
4. 旧数据无损：M1 的 5 条真实待办逐条 summary/status/契约字段不变，父任务 children_total=2；
5. 备份与原子写：.backup/ 滚动备份 1~10 份；非法写入恢复由 pytest 直测 datastore（绕过 API）；
6. 备忘：POST → 列表 → PUT → 单篇一致 → DELETE → 404（含中文 id 的 URL 编码往返）；
7. 事件：POST 全天（dtend 排他）→ 当月聚合"含首尾不含排他日" → DELETE → 消失；
8. 终态：me/ 恢复 count=3、含子任务=2、无验收残留，validate.py 终检。

2026-09-14 实测通过。**Windows 编码注意（勿改回）**：脚本内 `export PYTHONUTF8=1`（本机 python
管道默认 gbk+surrogateescape，会把 UTF-8 响应解码成 mojibake，导致断言假失败/假通过）；中文
JSON payload 一律 heredoc→stdin（`curl -d @-`），不得内联在 curl 参数（原生 Windows curl 按 GBK 转码参数）。

前端交付验收（需浏览器人工走查）：`cd frontend && npm run dev` + 后端 uvicorn :8000，
数据目录选 me：三视图快速记录、勾选→归档区→恢复、编辑面板（时间/标签/父任务/放弃/级联删除确认）、
日历点天建全天事件（含首尾呈现）/点 ⚑▸▣ 开待办编辑、备忘建/改/删。

## 6. 明确不做（防范围蔓延）

- Radicale / CalDAV 网络协议、多端同步（推迟 M3）
- 拖拽排期、拖拽改时间（推迟 M3，M2 只用编辑表单改时间）
- 提醒编辑 UI（VALARM 已能读写但不做编辑入口）
- 重复事件（RRULE）、子任务超过两级
- 时间线 LLM 生成（M3）、旧数据迁入（M3）
- 登录权限、协作
