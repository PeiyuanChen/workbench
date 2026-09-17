# M2 收尾与 M3 启动 · 会话承接

> 用途：新会话（Hermes 或 Claude Code）承接 workbench 工作时先读本文。
> 完整过程复盘见 `D:\tasks\ai-coding\02-practice\workbench-M1M2-实践复盘.md`。
> 最后更新：2026-09-17。

## 当前状态

- **M1 已交付**（commit `6c61a61`）：只读五视图，45 测试。
- **M2 已完成并前端验收通过，尚未 commit**：
  - 后端 148 测试全绿（M1 基线 57 → +91）；`bash scripts/accept-m2.sh` 通过。
  - 前端 5 项 UX 走查改进已完成（完成按钮替代勾选圈、编辑面板自动关闭、
    四象限固定高度卡内滚动、分区顺序调换、备忘创建留列表），`npm run build` 通过。
  - 新增文件：`atomic.py`、`schemas.py`、`errors.py`、`uids.py`、`todo_write.py`、
    `event_write.py`、`note_write.py`；前端 `QuickAdd`、`TodoEditPanel`、`ArchiveSection`、
    `EventForm`、`BaseModal`。

## 下一步要做的事（按序）

1. ~~审 SPEC-M2.md 的 6 处〔修订〕标注~~ ✅ 已审并确认。
2. ~~前端人工走查~~ ✅ 5 项 C 类 UX 改进已完成（完成按钮、面板自动关闭、
   四象限高度、分区顺序、备忘流程）。
3. **M2 收尾 commit**：确认 `.claude/settings.local.json`（含 API key）**不入库**
   （已加 .gitignore）；SPEC-M2.md、accept-m2.sh、三层 CLAUDE.md、
   .claude/rules/ 入库；`data/users/me/` 保持 gitignore。
4. **课 4（权限模式）**：回看 M2 实际使用的权限模式。
5. **课 7（Stop hook）**：把 accept-m2.sh + pytest 接成 Claude Code Stop hook。
6. **M3 规划（新 SPEC）**：时间线 LLM 生成、TickTick 旧数据 AI 迁入、
   Radicale/CalDAV 接入、拖拽排期等。

## 验收脚本使用

```bash
# 后端可不启动（脚本自起沙箱服务于 8765）；Windows git-bash 仓库根执行：
bash scripts/accept-m2.sh        # 退出码 0 = 通过；me/ 全程只读，md5 不变
```

已实测：连跑/代理环境/端口占用场景均处理；平台支持声明为"仅 Windows git-bash 实测，
POSIX 有兼容写法但未 CI 验证"。Windows 坑已固化脚本头注：PYTHONUTF8=1、中文 payload 走 stdin、
传 .exe 的路径必经 cygpath -m。

## 协作方式（已验证有效，继续沿用）

- **Hermes**：规格决策、外部独立复核（不轻信 Claude 自报）、跨会话记忆、课程引导。
- **Claude Code**：新会话 + `--permission-mode plan` 读 SPEC 出计划 → 审计划（Ctrl+G 可改）
  → 批准后小步实施，每步停下给测试证据。
- 实现者不给自己当验收者；写测试永不触达 `data/users/me/`。

## 关键文件指针

| 文件 | 内容 |
|---|---|
| `CLAUDE.md`（88行）/ `.claude/rules/data-contract.md`（backend paths）/ `frontend/CLAUDE.md` | 三层项目守则 |
| `SPEC-M2.md` | M2 规格（含〔修订〕标注，待审） |
| `scripts/accept-m2.sh` | 沙箱验收（M2 完成定义） |
| `data/users/example/` | 示例数据（入库）；`me/` 真实数据（gitignore） |
| `D:\tasks\ai-coding\01-claude-code\` | 官方课程 + 四篇中英对照 HTML |
| `D:\tasks\ai-coding\02-practice\workbench-M1M2-实践复盘.md` | M0-M2 完整复盘与教训 |
