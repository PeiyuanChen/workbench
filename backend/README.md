# backend —— FastAPI 后端

本地优先工作台的后端：**不持有私有数据模型、不使用任何数据库**，只读写
`data/users/{user}/` 下的 `.ics` / `.md` 开放文件。

## 分层（单向依赖）

```
api → service → datastore → 文件系统
        ↑ core 被各层引用（data_root、配置、UID 生成等）
```

下层不得 import 上层；所有文件访问必须经过 `core.data_root()`，禁止写死数据路径。

## 运行

```bash
# uv（推荐）
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 原生 venv
python -m venv .venv
.venv\Scripts\activate            # Windows；POSIX 为 source .venv/bin/activate
pip install -e .
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

也可以直接在仓库根执行 `bash scripts/dev.sh`，同时拉起前后端。

可选环境变量：

| 变量 | 作用 | 默认 |
| --- | --- | --- |
| `WORKBENCH_USER` | 默认用户目录（未传 `?user=` 时用） | `me` |
| `WORKBENCH_DATA` | 数据总根（仍按 `users/{user}/` 组织） | 仓库内 `data/` |

## 测试

```bash
uv run pytest        # 或 .venv 下：python -m pytest
```

覆盖：`.ics`/`.md` 读写往返不丢字段、中文折行、象限归位、父子进度、跨月裁剪、
API、原子写与备份、状态机、备忘/笔记集合内核隔离、旧路由 404。

## HTTP API 参考

所有端点都带可选 `user` 查询参数，缺省取 `WORKBENCH_USER`（默认 `me`），
示例数据用 `?user=example`。写操作响应信封为 `{"ok": true, "data": ...}`，
错误为 4xx/5xx + `{"detail": "中文原因"}`。

### 健康检查

| 方法 | 端点 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |

### 待办 `/api/todos`

数据落在 `calendar.ics` 的 VTODO；字段契约见仓库 `.claude/rules/data-contract.md`。

| 方法 | 端点 | 说明 |
| --- | --- | --- |
| GET | `/api/todos` | 树形列表（子任务挂父节点，含象限、时间三阶段、进度、逾期） |
| GET | `/api/todos/{uid}` | 单条待办 |
| POST | `/api/todos` | 新建待办（含 parent、DUE、DTSTART+DURATION、象限标签） |
| PATCH | `/api/todos/{uid}` | 局部更新（不接受 status，状态走专用动作） |
| POST | `/api/todos/{uid}/complete` | 勾选完成（幂等） |
| POST | `/api/todos/{uid}/reopen` | 取消完成 / 恢复放弃 |
| POST | `/api/todos/{uid}/abandon` | 放弃（STATUS:CANCELLED） |
| DELETE | `/api/todos/{uid}` | 物理删除（级联子任务） |

`GET /api/todos` 查询参数：

| 参数 | 取值 | 说明 |
| --- | --- | --- |
| `view` | `quadrant` / `list` | 仅语义区分，分组由前端完成 |
| `unscheduled` | `1` | 只看未排期 |
| `status` | `NEEDS-ACTION` / `COMPLETED` / ... | 按 VTODO 状态过滤 |
| `scope` | `active`（默认）/ `archived` / `all` | active 顶层隐藏完成/放弃项 |
| `user` | 目录名 | 数据目录用户 |

### 日历事件 `/api/events`

| 方法 | 端点 | 说明 |
| --- | --- | --- |
| GET | `/api/events?month=YYYY-MM` | 月聚合：事件 + 待办执行块 + 截止标记 |
| GET | `/api/events/{uid}` | 单条事件详情 |
| POST | `/api/events` | 新建事件 |
| PATCH | `/api/events/{uid}` | 更新事件 |
| DELETE | `/api/events/{uid}` | 删除事件 |

### 备忘 `/api/memos`

物理目录 `memos/`，id 前缀 `memo-`，frontmatter 固定四键
`id,created,tags,related`。

| 方法 | 端点 | 说明 |
| --- | --- | --- |
| GET | `/api/memos` | 备忘列表 |
| GET | `/api/memos/{id}` | 备忘详情（含正文） |
| POST | `/api/memos` | 新建备忘（id/文件名服务端生成） |
| PUT | `/api/memos/{id}` | 全文更新 |
| DELETE | `/api/memos/{id}` | 删除（删除前备份） |
| POST | `/api/memos/assets` | 上传图片资产（multipart，5 MiB 上限，png/jpg/jpeg/gif/webp） |
| GET | `/api/memos/assets/{name}` | 读取图片资产 |

### 笔记 `/api/notes`

物理目录 `notes/`，id 前缀 `note-`，与备忘共用同一套 Markdown 存储内核
（ADR-0001/0002）。文件夹即真实子目录，文件夹路径含斜杠/中文时走请求体或
query，不进 URL path（规避 `%2F` 歧义）。

| 方法 | 端点 | 说明 |
| --- | --- | --- |
| GET | `/api/notes` | 递归列表（`{count, folders, items}`） |
| GET | `/api/notes/{id}` | 单篇（含正文与 folder） |
| POST | `/api/notes` | 新建笔记（`folder` 可选，id/文件名服务端生成） |
| PUT | `/api/notes/{id}` | 全文更新；载荷含 `folder` 时移动并按深度改写资产链接 |
| DELETE | `/api/notes/{id}` | 物理删除（备份到 `notes/.backup/`，滚动保留 10 份） |
| POST | `/api/notes/folders` | 新建文件夹（支持嵌套） |
| PUT | `/api/notes/folders` | 同父目录重命名 |
| DELETE | `/api/notes/folders?path=` | 删除空文件夹（非空返回 422） |
| POST | `/api/notes/assets` | 上传图片资产（磁盘名带文件夹扁平前缀，规则同备忘） |
| GET | `/api/notes/assets/{name}` | 读取图片资产 |

### 时间线 `/api/timeline`

| 方法 | 端点 | 说明 |
| --- | --- | --- |
| GET | `/api/timeline/{year}/{month}` | 某月时间线；未生成返回 `exists:false` |

M3 起增加 `POST /api/timeline/generate?range=YYYY-MM`（LLM 按固定模板生成并
落盘为 timeline Markdown，可重新生成、可手改），当前版本不接外部模型。
