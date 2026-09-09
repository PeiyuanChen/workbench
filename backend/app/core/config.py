"""配置与数据根路径解析。

纪律：所有文件访问必须经过 data_root()，代码中禁止写死数据路径。
将来支持多用户时，仅需在认证后把 user 换成用户 id（data/users/{uid}/）。
"""

import os
from pathlib import Path

# 默认用户目录名（M1 单用户；example 为示例数据目录）
DEFAULT_USER = os.environ.get("WORKBENCH_USER", "me")

# 仓库根目录 = backend/ 的上一级
_REPO_ROOT = Path(__file__).resolve().parents[3]


def data_root(user: str | None = None) -> Path:
    """解析某用户的数据根目录：{仓库根}/data/users/{user}。

    可用环境变量 WORKBENCH_DATA 覆盖数据总根（仍按 users/{user} 组织）。
    本函数只负责解析路径，不保证目录存在（容错交给调用方）。
    """
    base = os.environ.get("WORKBENCH_DATA")
    root = Path(base) if base else _REPO_ROOT / "data"
    return root / "users" / (user or DEFAULT_USER)
