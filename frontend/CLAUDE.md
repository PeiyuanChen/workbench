# frontend/CLAUDE.md — 前端工作守则

> 全局守则见仓库根 `CLAUDE.md`；数据契约见 `.claude/rules/data-contract.md`。
> 本文件只管 frontend/ 工程内的技术栈决策与界面基准。

## 技术栈（已拍板，不要更换）

- Vue 3（Composition API + `<script setup>`）+ TypeScript + Vite + Tailwind CSS
- 状态管理：Pinia
- PWA：`vite-plugin-pwa`
- 拖拽：VueDraggable
- M1 前端可先用 `prototype/index.html` 的静态版对照

## 界面基准（见 prototype/index.html）

- 5 视图左侧导航：四象限 / 待办 / 日历 / 时间线 / 备忘。
- 四象限 2×2：红=重要紧急、蓝=重要不紧急、橙=紧急不重要、灰=都不；卡片显示标签、截止/时间块、未排期标记、子任务进度。
- 待办视图分"未排期·最近要做"与"已排期·近期"（未排期分组在界面上只能叫"未排期"，禁止使用"收件箱/inbox"字样）；复杂事项可展开子任务 + 进度条。
- 日历月视图：执行块=▸色块、跨多天=▣横跨、截止=⚑小旗、普通事件=●。
- 时间线：顶部范围切换（月/季/半年/年/自定义）+ "✨LLM 生成/重新生成"徽标；正文按主线/决策组织。
- "＋快速记录"框**仅出现在四象限、待办、备忘**三视图（待办/四象限记事，备忘记笔记）；时间线、日历无此框。
