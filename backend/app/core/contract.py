"""数据契约常量（对应 CLAUDE.md「数据契约」与 data-samples/）。

契约变更必须先经用户确认，不得自行修改。
"""

# ---- 四象限标签（iCalendar 标准 X- 扩展） ----
X_IMPORTANT = "X-IMPORTANT"
X_URGENT = "X-URGENT"
# 宽松解析：视为真的取值（其余一律 False）
TRUE_VALUES = {"TRUE", "1", "YES"}

# 象限（由 important×urgent 现算，与有无时间正交）
Q1 = "q1"  # 重要且紧急 → 立即做
Q2 = "q2"  # 重要不紧急 → 计划做
Q3 = "q3"  # 紧急不重要 → 快做/委托
Q4 = "q4"  # 不重要不紧急 → 有空再做

# ---- VTODO STATUS（RFC 5545） ----
STATUS_NEEDS_ACTION = "NEEDS-ACTION"
STATUS_COMPLETED = "COMPLETED"
STATUS_IN_PROCESS = "IN-PROCESS"
STATUS_CANCELLED = "CANCELLED"
DEFAULT_STATUS = STATUS_NEEDS_ACTION

# ---- 待办时间三阶段（全部可选、渐进；界面禁止出现"收件箱"字样） ----
STAGE_UNSCHEDULED = "unscheduled"  # 无 DTSTART 无 DUE = 未排期·最近要做
STAGE_DUE = "due"                  # 仅 DUE = 截止时点（不占时长，日历画 ⚑）
STAGE_BLOCK = "block"              # DTSTART+DURATION = 执行时间块（日历画 ▸）
STAGE_BOTH = "both"                # 截止 + 执行块并存

# ---- 父子任务 ----
# 项目约定：子任务携带 RELATED-TO;RELTYPE=CHILD:<父UID>（见 CLAUDE.md）。
# 同时兼容 RFC 惯例的 RELTYPE=PARENT（默认）指向父任务——两种写法都解释为
# "被引用的 UID 是我的父任务"，保证外部 CalDAV 客户端数据也能归位。
RELTYPE_CHILD = "CHILD"
RELTYPE_PARENT = "PARENT"
MAX_TREE_DEPTH = 2  # 默认两级：父 + 子

# ---- Markdown frontmatter ----
FRONTMATTER_KEYS = ("id", "tags", "related")

# ---- 时区 ----
TIMEZONE = "Asia/Shanghai"
