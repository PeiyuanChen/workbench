"""个人工作台后端应用包。

分层纪律（单向依赖）：api → service → datastore → 文件系统；
core 为配置/路径/契约常量，被各层引用。下层不得 import 上层。
"""
