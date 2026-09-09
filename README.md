# 个人工作台（Local-First Workbench）

一个**本地优先（local-first）的单用户个人工作台**，Web 应用，包含五个视图：

- **四象限** —— 艾森豪威尔优先级（重要×紧急，2×2 现场计算，不是独立存储）
- **待办** —— 分"未排期 · 最近要做"与"已排期 · 近期"，支持父子任务与进度
- **日历** —— 月视图：执行时间块 ▸ / 跨多天 ▣ / 截止小旗 ⚑ / 普通事件 ●
- **时间线** —— 按月回顾（M3 起由 LLM 生成）
- **备忘** —— Markdown 笔记列表 + 详情

## 🚨 第一性原则：数据主权

**所有业务数据只以开放纯文本格式存在你本地，没有任何数据库：**

| 数据 | 格式 | 位置 |
| --- | --- | --- |
| 待办 + 日历事件 | iCalendar `.ics`（RFC 5545） | `data/users/{用户}/calendar.ics` |
| 备忘 | Markdown（YAML frontmatter） | `data/users/{用户}/notes/YYYY-MM-DD-标题.md` |
| 时间线 | Markdown（YAML frontmatter） | `data/users/{用户}/timeline/YYYY/MM.md` |

没有本应用，这些文件也能用记事本、Obsidian、Apple/Google 日历、任意 CalDAV 客户端打开。
**软件只是一层皮**：直接用文本编辑器改 `calendar.ics`，刷新页面即生效。

当前为 **M1（只读）**：后端只读文件返回 JSON，前端渲染；增删改请直接把数据写进文件（M2 才提供写接口）。

## 目录结构

```
workbench/
├─ backend/        # FastAPI 后端（api → service → datastore 单向依赖）
├─ frontend/       # Vue 3 + Vite + TS + Tailwind + Pinia
├─ data/users/
│  ├─ me/          # 你的实际数据目录（默认为空，各接口容错返回空）
│  └─ example/     # 示例数据（演示/测试，可随时改着玩）
├─ data-samples/   # 参考样例 + validate.py 契约校验器
├─ prototype/      # 静态原型（布局基准）
└─ CLAUDE.md       # 项目工作守则（数据契约、技术栈、里程碑）
```

## 环境要求

- Python **3.11+**（推荐用 [uv](https://github.com/astral-sh/uv) 管理）
- Node.js **18+**

## 启动后端

```bash
cd backend

# 方式一：uv（推荐，已配清华镜像源）
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 方式二：原生 venv
python -m venv .venv
# Windows: .venv\Scripts\activate   Linux/macOS: source .venv/bin/activate
pip install -e .
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

健康检查：`curl http://127.0.0.1:8000/api/health`

可选环境变量：

| 变量 | 作用 | 默认 |
| --- | --- | --- |
| `WORKBENCH_USER` | 默认用户目录（未传 `?user=` 时用） | `me` |
| `WORKBENCH_DATA` | 数据总根（仍按 `users/{user}/` 组织） | 仓库内 `data/` |

## 启动前端

```bash
cd frontend
npm install        # 国内网络可加 --registry=https://registry.npmmirror.com
npm run dev
```

开发服务器已配置代理：前端对 `/api/*` 的请求自动转发到 `http://127.0.0.1:8000`，无需处理跨域。

## 访问方式

浏览器打开 **http://127.0.0.1:5173**

1. 左侧导航切换五个视图：四象限 / 待办 / 日历 / 时间线 / 备忘。
2. 侧栏底部有**数据源切换**：
   - `example` —— 示例数据（默认），首次打开即可看到完整效果；
   - `me` —— 你自己的数据目录（初始为空，各视图显示空态）。
3. 想看到自己的真实数据：把 `.ics` / `.md` 文件放进 `data/users/me/`（结构见上表），刷新页面即可；或用文本编辑器直接改文件，刷新即变。

### 只读 API（M1）

| 端点 | 说明 |
| --- | --- |
| `GET /api/health` | 健康检查 |
| `GET /api/todos?view=&unscheduled=&status=&user=` | 待办（含父子层级、象限、进度、时间三阶段） |
| `GET /api/todos/{uid}` | 单条待办 |
| `GET /api/events?month=YYYY-MM&user=` | 日历聚合（事件 + 执行块 + 截止标记） |
| `GET /api/timeline/{year}/{month}?user=` | 时间线（未生成返回 `exists:false`） |
| `GET /api/notes?user=` / `GET /api/notes/{id}?user=` | 备忘列表 / 详情 |

`user` 参数缺省取 `WORKBENCH_USER`（默认 `me`）。示例：
`http://127.0.0.1:8000/api/todos?user=example`

## 测试与校验

```bash
# 后端单元/集成测试（45 项：读写往返、中文折行、象限归位、父子进度、跨月裁剪、API）
cd backend && uv run pytest        # 或 .venv 下：python -m pytest

# 数据契约校验（字段合法性、UID 唯一、frontmatter 完整）
python data-samples/validate.py data/users/example
```

## 里程碑

- **M1（已完成）**：只读后端 + 五视图前端，能看到自己的真实数据。
- **M2**：写接口（待办/事件/备忘增删改）+ 接入 Radicale（CalDAV）。
- **M3**：时间线 LLM 生成；旧数据（TickTick 等）AI 迁入。
- **M4**：自托管 + PWA 手机端 + 可选日历双向同步。

更多设计背景见 `概要设计-v1.md`、`技术方案-v1.md`、`CLAUDE.md`。
