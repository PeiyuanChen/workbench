"""业务异常（SPEC-M2 §2：错误 = HTTP 4xx/5xx + {"detail": "中文错误信息"}）。

service/datastore 抛 ApiError 及子类，main.py 注册统一 handler 转 JSON 响应；
路由层不再手动拼 HTTPException（M1 已有 GET 的 404 保持不动）。
"""

from __future__ import annotations


class ApiError(Exception):
    """业务错误基类：status_code + 中文 detail。"""

    status_code = 500

    def __init__(self, detail: str, status_code: int | None = None):
        super().__init__(detail)
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code


class NotFound(ApiError):
    """404：资源不存在。"""

    status_code = 404


class ValidationFailed(ApiError):
    """422：业务校验失败（中文规则说明，SPEC-M2 §2.1）。"""

    status_code = 422
