#!/usr/bin/env bash
# ============================================================
# M2 沙箱验收脚本（SPEC-M2 §5 完整实现）
#
# 设计原则：
#   - **对仓库 data/users/me/ 只读不写**：只跑两次冒烟（icalendar 解析、待办结构完整），
#     不断言任何具体状态（用户数据处于何种状态都不该让脚本失败）；
#   - **沙箱化**：系统 temp 目录下建临时目录，WORKBENCH_DATA 指向它，
#     基底数据从 data/users/example 复制为 users/m2accept；
#     所有 POST/PATCH/DELETE/complete/abandon 生命周期都打 ?user=m2accept；
#   - **自启动 uvicorn（健壮生命周期）**：
#     * 直接用 backend/.venv/Scripts/python.exe -m uvicorn（绕过 uv shim——
#       否则 $! 拿到的是 uv.exe 的 PID，kill 只杀 shim，真 uvicorn 会孤儿残留占端口）；
#     * 子 shell + exec 启动，$! 即真实 python 进程；
#     * 启动前检查端口 8765：已被占用直接 FATAL，绝不在别人的服务上假跑；
#     * 探活以 HTTP 200 为准（60 次 × 1s），所有 curl 统一 --noproxy '*'
#       （公司代理会劫持 127.0.0.1，造成"服务器活着但探测不通"）；
#     * FATAL 时打印 uvicorn 日志尾 20 行（日志在沙箱内，退出零残留）；
#   - **自动清理**：trap EXIT 时杀 uvicorn + 删除整个沙箱目录（含失败路径）；
#   - **零 uv / 零网络依赖**：所有 python 调用走 .venv 解释器（$PY），
#     代理/断网环境下同样可跑；
#   - **跨用户/跨机器可移植**：不依赖特定用户数据、特定 UID、特定计数。
#
# 用户真实数据的保护承诺：
#   - me/ 的任何状态（例如已勾选完成的待办）被原样保留，本脚本既不修改也不恢复；
#   - me/.backup/ 数量、calendar.ics 内容（md5）不因本脚本运行而变化。
#
# 支持平台：
#   - 当前仅在 Windows git-bash 环境实测验证（脚本中所有 Windows 编码/路径坑
#     均在该环境下发现并记录）；
#   - Linux/macOS 下的路径处理已做兼容写法（venv 解释器探测、cygpath 不存在时
#     回退原路径），但未在 CI 验证，不算正式支持；
#   - 不引入新依赖、不加 Docker/CI——单用户本地工具，跨平台验证留到真有第二个
#     平台用户时再做。
#
# Windows 编码/路径四坑（实测踩过，勿改回）：
#   1) export PYTHONUTF8=1 —— 本机 python 管道默认 gbk+surrogateescape，会把 UTF-8
#      响应解码成 mojibake，导致 == 断言假失败、in 断言假通过；
#   2) 中文 JSON payload 一律 heredoc → stdin（curl -d @-），不得内联在 curl -d
#      参数里——原生 Windows curl.exe 会按 GBK 转码命令行参数，请求体变非法 UTF-8；
#   3) 多行 python 输出被 bash 捕获时带 \r（Windows 换行），需 tr -d '\r'；
#      嵌入 python 源码的仓库路径必须用 cygpath -m 的 Windows 形式（D:/...），
#      MSYS 形式 /d/... 会被 Windows Python 当成 UNC \\d\...；
#   4) 【硬规则】任何传给 Windows 原生可执行文件（python.exe 等）的路径参数
#      必须经 cygpath -m 转为 Windows 形式（D:/...、C:/...）；/d/、/tmp 形式的
#      MSYS 路径禁止直接传参——MSYS 的参数自动转换在不同 shell 环境下不可靠
#      （实测外部复跑被转成 D:\d\tasks\... 导致 can't open file）。
#      例外：MSYS 自带工具（cp/ls/tail/rm/mkdir）、bash 重定向、cd、相对路径
#      （如 pytest tests/）与 curl（仅 URL）不受此限。
# ============================================================
set -euo pipefail
export PYTHONUTF8=1
# 双保险：即使有工具绕过 curlx 走系统代理，也对回环地址直连
export NO_PROXY="127.0.0.1,localhost"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# 后端 venv 解释器探测（平台自适应）：
# - Windows: .venv/Scripts/python.exe（PY_WIN=1，需 cygpath 转路径）
# - POSIX:   .venv/bin/python（PY_WIN=0，路径原样）
if [ -x "$REPO_ROOT/backend/.venv/Scripts/python.exe" ]; then
  PY="$REPO_ROOT/backend/.venv/Scripts/python.exe"
  PY_WIN=1
elif [ -x "$REPO_ROOT/backend/.venv/bin/python" ]; then
  PY="$REPO_ROOT/backend/.venv/bin/python"
  PY_WIN=0
else
  echo "[FATAL] 找不到 venv python，请先在 backend/ 执行 uv sync"
  echo "        Windows 路径: backend/.venv/Scripts/python.exe"
  echo "        POSIX 路径:   backend/.venv/bin/python"
  exit 1
fi
echo "[PLATFORM] PY_WIN=$PY_WIN（$PY）"

# 给 Python -c 字符串用的平台兼容路径：
# Windows 需 cygpath 转 Windows 形式（见头注坑 3/4）；POSIX 原样
if [ "$PY_WIN" = "1" ] && command -v cygpath >/dev/null 2>&1; then
  REPO_ROOT_WIN="$(cygpath -m "$REPO_ROOT")"
else
  REPO_ROOT_WIN="$REPO_ROOT"
fi

PORT=8765
BASE="http://127.0.0.1:$PORT/api"
SANDBOX_USER=m2accept

# 统一 curl：-s 静默、--noproxy '*' 绕过任何代理、--max-time 10 防挂死
# （调用方可再传 --max-time 覆盖，curl 以最后一个为准）
curlx() { curl -s --noproxy '*' --max-time 10 "$@"; }

# ------------------------------------------------------------
# 沙箱与服务器生命周期
# ------------------------------------------------------------
SANDBOX_ROOT="$(mktemp -d)"
# SANDBOX_ROOT_WIN = 沙箱的 Windows 形式路径（头注坑 4 硬规则）：
# WORKBENCH_DATA 给 uvicorn/Python 用；validate.py 等 .exe 路径参数也一律用它。
# 无 cygpath 的环境回退原值（此时假定本身即 Windows 路径）。
if [ "$PY_WIN" = "1" ] && command -v cygpath >/dev/null 2>&1; then
  SANDBOX_ROOT_WIN="$(cygpath -m "$SANDBOX_ROOT")"
else
  SANDBOX_ROOT_WIN="$SANDBOX_ROOT"
fi
export WORKBENCH_DATA="$SANDBOX_ROOT_WIN"
UVICORN_LOG="$SANDBOX_ROOT/uvicorn.log"   # 仅供 bash 重定向/tail（MSYS 工具），用 MSYS 形式
echo "[SANDBOX] $SANDBOX_ROOT (WORKBENCH_DATA=$WORKBENCH_DATA)"

# 复制 example 用户作为 m2accept 基底（含 calendar.ics/notes/timeline）
mkdir -p "$SANDBOX_ROOT/users"
cp -r "$REPO_ROOT/data/users/example" "$SANDBOX_ROOT/users/$SANDBOX_USER"

UVICORN_PID=""
cleanup() {
  [ -n "${UVICORN_PID:-}" ] && kill "$UVICORN_PID" 2>/dev/null && wait "$UVICORN_PID" 2>/dev/null || true
  [ -n "${SANDBOX_ROOT:-}" ] && [ -d "$SANDBOX_ROOT" ] && rm -rf "$SANDBOX_ROOT"
}
trap cleanup EXIT

start_server() {
  # 启动前端口检查：8765 已有监听（如上次验收孤儿残留）→ 立即失败并给诊断，
  # 绝不在旧服务上假跑生命周期测试
  if curlx -o /dev/null --max-time 2 "$BASE/health" >/dev/null 2>&1; then
    echo "[FATAL] 端口 $PORT 已被占用，请先释放后重跑（可能是上次验收残留的 uvicorn）："
    netstat -ano | grep ":$PORT " || echo "  （netstat 未找到监听行，可能是非 HTTP 进程）"
    return 1
  fi

  # 子 shell + exec：$! 即真实 python 进程 PID（kill 直达，不留孤儿）
  ( cd "$REPO_ROOT/backend" && exec "$PY" -m uvicorn app.main:app \
      --host 127.0.0.1 --port "$PORT" ) > "$UVICORN_LOG" 2>&1 &
  UVICORN_PID=$!

  # 探活：仅 HTTP 200 算就绪；60 次 × 1s。
  # ⚠ 赋值里的 curl 必须 || true——set -e 下未就绪（exit 7）会直接终止脚本
  local i code
  for i in $(seq 1 60); do
    code=$(curlx -o /dev/null -w '%{http_code}' --max-time 2 "$BASE/health" 2>/dev/null || true)
    if [ "$code" = "200" ]; then
      return 0
    fi
    sleep 1
  done
  echo "[FATAL] uvicorn 60 秒内未就绪（端口 $PORT，pid=$UVICORN_PID），日志尾 20 行："
  tail -20 "$UVICORN_LOG" 2>/dev/null || echo "  （日志为空或不存在）"
  return 1
}
start_server
echo "[SERVER] uvicorn pid=$UVICORN_PID port=$PORT（venv python 直启，无 uv shim）"

# ============================================================
# me/ 只读冒烟（不经过服务器，直接读仓库 data/users/me/，不修改任何文件）
# ============================================================
echo "=== me/ 只读冒烟 ==="
"$PY" -c "
from pathlib import Path
from icalendar import Calendar
me_dir = Path('$REPO_ROOT_WIN/data/users/me')
Calendar.from_ical((me_dir / 'calendar.ics').read_bytes())
print('[me 冒烟 OK] calendar.ics 可被 icalendar 严格解析')"

(cd "$REPO_ROOT/backend" && "$PY" -c "
from pathlib import Path
from app.datastore.ics_store import read_calendar
from app.service.todo_service import build_tree
me_dir = Path('$REPO_ROOT_WIN/data/users/me')
cal = read_calendar(me_dir)
tree = build_tree(cal['todos'])
for node in tree:
    assert node.get('uid'), 'UID 为空'
    assert isinstance(node.get('summary'), str) and node['summary'], 'summary 缺失'
    assert node.get('status'), 'status 缺失'
    for c in node.get('children', []):
        assert c.get('uid')
print('[me 冒烟 OK] %d 顶层待办全部可读、UID 非空、字段结构完整' % len(tree))")

# ============================================================
# 沙箱基底完整性（不硬编码具体 UID/计数，只断言结构）
# ============================================================
# tr -d '\r'：见头注坑 3
BASELINE_UIDS=$(curlx "$BASE/todos?user=$SANDBOX_USER&scope=all" | "$PY" -c "
import sys, json
d = json.load(sys.stdin)
assert d['count'] > 0, 'm2accept 基底无数据'
for t in d['items']:
    assert t.get('uid'), 'UID 为空'
    assert isinstance(t['summary'], str) and t['summary'], 'summary 缺失'
    assert t['status'] in ('NEEDS-ACTION', 'IN-PROCESS', 'COMPLETED', 'CANCELLED')
print('\n'.join(t['uid'] for t in d['items']))" | tr -d '\r')

BASELINE_COUNT=$(echo "$BASELINE_UIDS" | wc -l | tr -d ' ')
echo "[基底 OK] m2accept 基底 $BASELINE_COUNT 条待办、结构完整"

# ============================================================
# 1) 新建：带 due 的重要待办，断言落库可读回、象限/状态正确
# ============================================================
NEW_UID=$(curlx -X POST "$BASE/todos?user=$SANDBOX_USER" -H 'Content-Type: application/json' -d @- <<'JSON' | "$PY" -c "
import sys, json
r = json.load(sys.stdin); assert r['ok'], r
t = r['data']
assert t['important'] is True and t['urgent'] is False, t
assert t['due'] == '2026-09-20T18:00:00+08:00', t
assert t['status'] == 'NEEDS-ACTION' and t['quadrant'] == 'q2', t
assert t['created'] and t['dtstamp'], t
print(t['uid'])" | tr -d '\r'
{"summary":"M2验收-临时待办","important":true,"due":"2026-09-20T18:00"}
JSON
)
export NEW_UID
echo "[1 OK] POST 待办 uid=$NEW_UID"

# ============================================================
# 2) 端到端：active 可见 → complete 消失 → scope=archived 可见 → 幂等 → reopen
#    → abandon → 恢复（归档过滤参数 = scope，决策 A）
# ============================================================
curlx "$BASE/todos?user=$SANDBOX_USER" | "$PY" -c "
import sys, json, os
d = json.load(sys.stdin)
assert any(t['uid'] == os.environ['NEW_UID'] for t in d['items']), '默认列表缺新建项'
print('[2a OK] 默认 active 列表可见 count=%d' % d['count'])"

curlx -X POST "$BASE/todos/$NEW_UID/complete?user=$SANDBOX_USER" | "$PY" -c "
import sys, json
t = json.load(sys.stdin)['data']
assert t['status'] == 'COMPLETED' and t['completed'], t
print('[2b OK] complete → COMPLETED（含 UTC 时间戳）')"

curlx "$BASE/todos?user=$SANDBOX_USER" | "$PY" -c "
import sys, json, os
d = json.load(sys.stdin)
assert not any(t['uid'] == os.environ['NEW_UID'] for t in d['items']), '完成后默认列表仍在'
print('[2c OK] 完成后默认列表消失')"

curlx "$BASE/todos?user=$SANDBOX_USER&scope=archived" | "$PY" -c "
import sys, json, os
d = json.load(sys.stdin)
assert any(t['uid'] == os.environ['NEW_UID'] and t['status'] == 'COMPLETED' for t in d['items']), '归档区不可见'
print('[2d OK] scope=archived 归档区可见')"

COMPLETED_TS=$(curlx -X POST "$BASE/todos/$NEW_UID/complete?user=$SANDBOX_USER" | "$PY" -c "
import sys, json
t = json.load(sys.stdin)['data']
assert t['status'] == 'COMPLETED', t
print(t['completed'])" | tr -d '\r')
curlx "$BASE/todos?user=$SANDBOX_USER&scope=archived" | COMPLETED_TS="$COMPLETED_TS" "$PY" -c "
import sys, json, os
d = json.load(sys.stdin)
me = next(t for t in d['items'] if t['uid'] == os.environ['NEW_UID'])
assert me['completed'] == os.environ['COMPLETED_TS'], '幂等：COMPLETED 时间戳不应变化'
print('[2e OK] complete 幂等（时间戳不变）')"

curlx -X POST "$BASE/todos/$NEW_UID/reopen?user=$SANDBOX_USER" | "$PY" -c "
import sys, json
t = json.load(sys.stdin)['data']
assert t['status'] == 'NEEDS-ACTION' and not t['completed'], t
print('[2f OK] reopen → NEEDS-ACTION，COMPLETED 已清除')"

curlx -X POST "$BASE/todos/$NEW_UID/abandon?user=$SANDBOX_USER" | "$PY" -c "
import sys, json
assert json.load(sys.stdin)['data']['status'] == 'CANCELLED'
print('[2g OK] abandon → CANCELLED（UI 文案=已放弃）')"

curlx -X POST "$BASE/todos/$NEW_UID/reopen?user=$SANDBOX_USER" | "$PY" -c "
import sys, json
assert json.load(sys.stdin)['data']['status'] == 'NEEDS-ACTION'
print('[2h OK] 放弃项可恢复（reopen 兼作恢复）')"

# ============================================================
# 3) 数据主权闸门（沙箱内）：calendar.ics 可被 icalendar 严格解析
#    + validate.py 契约全绿
# ============================================================
"$PY" -c "
from pathlib import Path
from icalendar import Calendar
import os
sandbox = Path(os.environ['WORKBENCH_DATA'])
Calendar.from_ical((sandbox / 'users' / '$SANDBOX_USER' / 'calendar.ics').read_bytes())
print('[3a OK] 沙箱 calendar.ics 可被 icalendar 严格解析')"
"$PY" "$REPO_ROOT_WIN/data-samples/validate.py" "$SANDBOX_ROOT_WIN/users/$SANDBOX_USER" >/dev/null \
  && echo "[3b OK] validate.py 契约校验通过（沙箱）"

# ============================================================
# 4) 基底无损：生命周期测试未污染基底 UID 集合（结构完整性）
# ============================================================
curlx "$BASE/todos?user=$SANDBOX_USER&scope=all" | BASELINE_UIDS="$BASELINE_UIDS" "$PY" -c "
import sys, json, os
d = json.load(sys.stdin)
baseline = set(os.environ['BASELINE_UIDS'].strip().split('\n'))
current = set(t['uid'] for t in d['items'])
missing = baseline - current
extra = current - baseline
assert not missing, '基底 UID 丢失: %s' % missing
# extra 应该只有 NEW_UID
assert extra == {os.environ['NEW_UID']}, '意外新增 UID: %s' % extra
print('[4 OK] 基底 %d 条 UID 集合完整，唯一新增=NEW_UID' % len(baseline))"

# ============================================================
# 5) 备份与原子写：沙箱 .backup/ 滚动备份 1~10 份；
#    datastore 级回读失败恢复/往返 diff 由 pytest 独立覆盖
# ============================================================
N_BAK=$(ls "$SANDBOX_ROOT/users/$SANDBOX_USER/.backup/" 2>/dev/null | grep -c '^calendar-.*\.ics$' || echo 0)
[ "$N_BAK" -ge 1 ] && [ "$N_BAK" -le 10 ]
echo "[5a OK] 沙箱 .backup 滚动备份 $N_BAK 份（1~10）"
(cd "$REPO_ROOT/backend" && "$PY" -m pytest tests/ -q >/dev/null) \
  && echo "[5b OK] pytest 全绿（含回读失败恢复/往返 diff/级联删除/校验 422）"

# ============================================================
# 6) 备忘：POST → 列表可见 → PUT 改正文 → 单篇一致 → DELETE → 404
# ============================================================
NOTE=$(curlx -X POST "$BASE/notes?user=$SANDBOX_USER" -H 'Content-Type: application/json' -d @- <<'JSON' | "$PY" -c "
import sys, json
from urllib.parse import quote
n = json.load(sys.stdin)['data']
assert n['title'] == 'M2验收-临时笔记', n
assert 'M2验收-临时笔记' in n['id'], n          # 决策 D：id 含中文标题
assert n['filename'].endswith('.md'), n
assert n['content'].startswith('# M2验收-临时笔记'), n   # 标题三源一致（H1）
print(n['id'] + ' ' + quote(n['id'], safe=''))" | tr -d '\r'
{"title":"M2验收-临时笔记","content":"正文一","tags":["验收"]}
JSON
)
export NOTE_ID=${NOTE% *}; export NOTE_ENC=${NOTE#* }
echo "[6a OK] POST 笔记 id=$NOTE_ID"

curlx "$BASE/notes?user=$SANDBOX_USER" | "$PY" -c "
import sys, json, os
d = json.load(sys.stdin)
assert any(n['id'] == os.environ['NOTE_ID'] for n in d['items']), '列表缺新笔记'
print('[6b OK] 备忘列表可见 count=%d' % d['count'])"

curlx -X PUT "$BASE/notes/$NOTE_ENC?user=$SANDBOX_USER" -H 'Content-Type: application/json' -d @- <<'JSON' | "$PY" -c "
import sys, json
n = json.load(sys.stdin)['data']
assert '正文二-已修改' in n['content'], n
assert n['id'] == __import__('os').environ['NOTE_ID'], 'id 不得变化'
print('[6c OK] PUT 全文更新')"
{"title":"M2验收-临时笔记","content":"正文二-已修改","tags":["验收"],"related":[]}
JSON

curlx "$BASE/notes/$NOTE_ENC?user=$SANDBOX_USER" | "$PY" -c "
import sys, json
n = json.load(sys.stdin)
assert '正文二-已修改' in n['content'], n
print('[6d OK] GET 单篇内容一致')"

curlx -X DELETE "$BASE/notes/$NOTE_ENC?user=$SANDBOX_USER" | "$PY" -c "
import sys, json
assert json.load(sys.stdin)['ok']
print('[6e OK] DELETE 备忘')"

[ "$(curlx -o /dev/null -w '%{http_code}' "$BASE/notes/$NOTE_ENC?user=$SANDBOX_USER")" = "404" ]
echo "[6f OK] 删除后 404"

# ============================================================
# 7) 事件：POST 全天（dtend 排他）→ 当月聚合可见（含首尾不含排他日）→ DELETE → 消失
# ============================================================
EV_UID=$(curlx -X POST "$BASE/events?user=$SANDBOX_USER" -H 'Content-Type: application/json' -d @- <<'JSON' | "$PY" -c "
import sys, json
e = json.load(sys.stdin)['data']
assert e['all_day'] is True and e['summary'] == 'M2验收-临时事件', e
assert e['dtstart'] == '2026-09-20' and e['dtend'] == '2026-09-22', e
print(e['uid'])" | tr -d '\r'
{"summary":"M2验收-临时事件","dtstart":"2026-09-20","dtend":"2026-09-22","all_day":true}
JSON
)
export EV_UID
echo "[7a OK] POST 全天事件 uid=$EV_UID"

curlx "$BASE/events?month=2026-09&user=$SANDBOX_USER" | "$PY" -c "
import sys, json, os
d = json.load(sys.stdin)
it = [i for i in d['items'] if i['uid'] == os.environ['EV_UID']]
assert it, '月聚合缺新事件'
days = it[0]['days_in_month']
assert it[0]['all_day'] is True, it[0]
assert days == ['2026-09-20', '2026-09-21'], days   # 含首尾、不含排他日 09-22
print('[7b OK] 当月聚合可见，含首尾不含排他日:', days)"

curlx -X DELETE "$BASE/events/$EV_UID?user=$SANDBOX_USER" | "$PY" -c "
import sys, json
assert json.load(sys.stdin)['ok']
print('[7c OK] DELETE 事件')"

curlx "$BASE/events?month=2026-09&user=$SANDBOX_USER" | "$PY" -c "
import sys, json, os
d = json.load(sys.stdin)
assert not any(i['uid'] == os.environ['EV_UID'] for i in d['items']), '删除后仍在'
print('[7d OK] 删除后聚合消失')"

# ============================================================
# 8) 终检：基底 UID 集合在生命周期测试后仍完整；validate.py 终检
# ============================================================
curlx "$BASE/todos?user=$SANDBOX_USER&scope=all" | BASELINE_UIDS="$BASELINE_UIDS" "$PY" -c "
import sys, json, os
d = json.load(sys.stdin)
baseline = set(os.environ['BASELINE_UIDS'].strip().split('\n'))
current = set(t['uid'] for t in d['items'])
# NEW_UID 在 2h reopen 后仍活跃（未删），应还在 current 中
assert baseline | {os.environ['NEW_UID']} == current, 'UID 集合异常'
print('[8a OK] 终态 UID 集合正确（基底 + NEW_UID）')"

"$PY" "$REPO_ROOT_WIN/data-samples/validate.py" "$SANDBOX_ROOT_WIN/users/$SANDBOX_USER" >/dev/null \
  && echo "[M2 验收通过] 沙箱无副作用，me/ 只读冒烟通过，临时目录将由 trap 清理"
