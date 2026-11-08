# 备忘模块改名 notes → memos，新「笔记」模块占用 notes

新增「笔记」模块时，`note/notes` 命名已被备忘全链路占用（物理目录 `notes/`、API `/api/notes`、Pinia store `notes`、frontmatter id 前缀 `note-`）。决定将备忘整体改名为 **memos**（目录 `memos/`、API `/api/memos`、路由 `#/memos`、store id `memos`、id 前缀 `memo-`、资产 `/api/memos/assets`），新模块「笔记」干净占用 **notes** 全链路命名。

## 考虑过的备选

- **新模块叫 `notebooks`，备忘不动**：被否。note 是「笔记」最自然的英文词，notebooks 语义偏离领域概念，且会让两个 md 模块的命名长期混淆。
- **旧备忘 id 冻结、仅新建用 `memo-` 前缀**：被否。两个模块永远共享前缀、日志不可辨。

## 后果

- 一次性迁移脚本 `scripts/migrate-notes-to-memos.py`：跑前将整个 `data/users/me/` zip 备份到仓库外 `.migration-backups/`；目录改名；活跃 md 的 frontmatter id 重写 `note-`→`memo-`（冷备份 `.backup/` 不动）；内置文件数/可解析性/旧目录消失校验。
- 已查实重写自包含：现有 `related` 无任何对备忘 id 的外部引用，无悬空风险。
- [SPEC-M2.md](../../SPEC-M2.md) 正文全量改写为现状规格（历史版本靠 git history 追溯）。
- 验收脚本 `accept-m2.sh`、`accept-memos-rich.sh` 及前后端约 17 个文件的命名同步更新。
