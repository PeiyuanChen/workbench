#!/usr/bin/env bash
# ============================================================
# Workbench 一键启动（dev）
#
# 一次完成：① 起 FastAPI 后端(8000) ② 起 Vite 前端(5173)
#          ③ 探活通过后自动用默认浏览器打开 http://127.0.0.1:5173
#
# 使用（Windows git-bash，仓库根）：
#   bash scripts/dev.sh
#   停止：在本终端按 Ctrl+C（会同时停掉后端与前端）。
#
# 设计要点（沿用 scripts/accept-m2.sh 趟过的 Windows 坑）：
#   - 直接用 backend/.venv/Scripts/python.exe -m uvicorn（绕过 uv shim，
#     否则 $! 拿到 uv.exe PID，杀不干净、真 uvicorn 孤儿占端口）；
#   - 前端用 npm（node 原生程序），路径走仓库根、不手拼 MSYS 路径；
#   - 启动前若端口 8000 / 5173 已被占用 → 直接报错退出，不叠加第二份服务；
#   - 探活以 HTTP 200 为准，curl 一律 --noproxy '*'（公司代理会劫持回环地址）；
#   - trap INT/TERM/EXIT 统一回收两个子进程；
#   - 仅 Windows git-bash 实测；不引入新依赖。
# ============================================================
set -euo pipefail
export PYTHONUTF8=1
export NO_PROXY="127.0.0.1,localhost"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACK_DIR="$REPO_ROOT/backend"
FRONT_DIR="$REPO_ROOT/frontend"
URL="http://127.0.0.1:5173"
API_HEALTH="http://127.0.0.1:8000/api/health"

# 后端解释器探测（Windows: Scripts/python.exe；POSIX: bin/python）
if [ -x "$BACK_DIR/.venv/Scripts/python.exe" ]; then
  PY="$BACK_DIR/.venv/Scripts/python.exe"
elif [ -x "$BACK_DIR/.venv/bin/python" ]; then
  PY="$BACK_DIR/.venv/bin/python"
else
  echo "[FATAL] 找不到后端 venv 解释器，先在 backend/ 建虚拟环境并安装依赖" >&2
  exit 1
fi

# 端口占用检查（被占用说明你可能已经手动起过服务）
port_busy() {
  local p="$1"
  if curl -s --noproxy '*' -o /dev/null "http://127.0.0.1:$p/" 2>/dev/null \
     || curl -s --noproxy '*' -o /dev/null "http://127.0.0.1:$p/api/health" 2>/dev/null; then
    return 0
  fi
  return 1
}
for p in 8000 5173; do
  if port_busy "$p"; then
    echo "[FATAL] 端口 $p 已有服务在跑（先停掉，或直接用它）。" >&2
    exit 1
  fi
done

BACK_PID=""
FRONT_PID=""
# Windows 兜底：按端口找到并杀掉仍在监听的进程（处理后台强杀/孤儿场景）
kill_port_win() {
  command -v netstat >/dev/null 2>&1 || return 0
  local pids
  pids=$(netstat -ano 2>/dev/null \
    | grep -E "127.0.0.1:$1" | grep LISTENING \
    | awk '{print $NF}' | sort -u)
  for pid in $pids; do
    MSYS_NO_PATHCONV=1 taskkill /PID "$pid" /F >/dev/null 2>&1 || true
  done
}
cleanup() {
  trap - EXIT INT TERM
  echo
  echo "[dev] 正在停止服务…"
  [ -n "$FRONT_PID" ] && kill "$FRONT_PID" 2>/dev/null || true
  [ -n "$BACK_PID" ] && kill "$BACK_PID" 2>/dev/null || true
  sleep 0.5
  # 强杀/子进程残留时按端口兜底（仅 Windows；POSIX 靠上面的 kill 进程组）
  kill_port_win 5173
  kill_port_win 8000
}
trap cleanup EXIT INT TERM

# ① 后端
echo "[dev] 启动后端 :8000 …"
( cd "$BACK_DIR" && exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 ) \
  >"$REPO_ROOT/.dev-backend.log" 2>&1 &
BACK_PID=$!

# ② 前端
echo "[dev] 启动前端 :5173 …"
( cd "$FRONT_DIR" && exec npm run dev ) \
  >"$REPO_ROOT/.dev-frontend.log" 2>&1 &
FRONT_PID=$!

# 探活（后端健康检查 + 前端页面），最多等 ~60s
# 注意：原生 Windows curl.exe 在 git-bash 下写 `-o /dev/null` 会因路径问题返回
# rc=23（写输出失败），即使 HTTP 200 也非 0。故不写 /dev/null，改用 -w 取 HTTP 码、
# body 丢弃到真实临时文件（Windows TEMP）。
wait_http() {
  local url="$1" n="${2:-60}" code
  local out="${TEMP:-/tmp}/.dev-probe-$$.out"
  for _ in $(seq 1 "$n"); do
    code=$(curl -s --noproxy '*' -o "$out" -w "%{http_code}" "$url" 2>/dev/null || echo "000")
    if [ "$code" = "200" ]; then rm -f "$out"; return 0; fi
    sleep 1
  done
  rm -f "$out"
  return 1
}

echo "[dev] 等待后端就绪…"
if ! wait_http "$API_HEALTH" 60; then
  echo "[FATAL] 后端未就绪，日志尾部：" >&2
  tail -n 20 "$REPO_ROOT/.dev-backend.log" >&2 || true
  exit 1
fi
echo "[dev] 等待前端就绪…"
if ! wait_http "$URL/" 60; then
  echo "[FATAL] 前端未就绪，日志尾部：" >&2
  tail -n 20 "$REPO_ROOT/.dev-frontend.log" >&2 || true
  exit 1
fi

# ③ 服务已就绪：先打印访问信息，再尝试打开浏览器
#    （即使开浏览器这步意外卡住/失败，地址也已输出，用户不会误判为启动失败）
echo "[dev] 已启动。前端=$URL 后端=http://127.0.0.1:8000"
echo "[dev] 日志：.dev-frontend.log / .dev-backend.log；本窗口 Ctrl+C 停止全部。"

# 自动打开默认浏览器（best-effort：失败/超时绝不影响已运行的服务）。
# Windows + mintty 坑（实测）：mintty 给原生程序的 stdin 是 pty 模拟管道，
# `cmd /c start` 拉起的浏览器会继承该句柄并长期持有，cmd 等其释放而永久挂起，
# 脚本卡在本行不动（现象：终端停在“打开浏览器”，服务其实存活，用户误以为
# 启动失败而 Ctrl+C，反而被 cleanup 杀掉全部服务）。
# 对策：`</dev/null` 切断 stdin 句柄继承（挂起立即消失）；timeout 再兜底 5 秒。
echo "[dev] 打开浏览器 $URL"
if command -v cmd.exe >/dev/null 2>&1; then
  timeout 5 cmd.exe /c start "" "$URL" </dev/null >/dev/null 2>&1 || true
elif command -v xdg-open >/dev/null 2>&1; then
  timeout 5 xdg-open "$URL" </dev/null >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then
  timeout 5 open "$URL" </dev/null >/dev/null 2>&1 || true
fi
# 前台等待，任一子进程退出则整体结束
wait -n "$BACK_PID" "$FRONT_PID" 2>/dev/null || wait
