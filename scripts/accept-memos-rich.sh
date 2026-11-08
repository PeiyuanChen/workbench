#!/usr/bin/env bash
# ============================================================
# 备忘富文本验收脚本（列表/表格/粗斜体/标题字号/图片）
# T1（#2）改名 notes → memos：端点 /api/memos(/assets)、沙箱目录 memos/；
# T2（#3）真实 me/ 已由 scripts/migrate-notes-to-memos.py 迁到 memos/。
#
# 纪律与 scripts/accept-m2.sh 完全一致（勿改回，坑均实测）：
#   - 沙箱化：mktemp 临时目录 + WORKBENCH_DATA，基底从 data/users/example
#     复制为 users/richtest；全部请求打 ?user=richtest，不碰 me/；
#   - 直启 backend/.venv 的 python -m uvicorn（绕过 uv shim，kill 不留孤儿）；
#   - 端口 8766 启动前探活，占用即 FATAL；curl 一律 --noproxy '*'；
#   - export PYTHONUTF8=1，中文 JSON 一律 heredoc → stdin（curl -d @-）；
#   - 传给原生 python.exe/curl.exe 的路径用 cygpath -m 的 Windows 形式；
#   - trap EXIT 杀 uvicorn + 删整个沙箱。
#
# 覆盖：图片上传落盘/字节回读/非法类型/伪装内容；富文本正文（粗/斜/H2-4/
#       两种列表/表格/图片语法）PUT→GET 逐字保留；GET→PUT H1 幂等；
#       assets/ 不进备忘列表；磁盘 .md 记事本可读（数据主权）；pytest 全绿。
# ============================================================
set -euo pipefail
export PYTHONUTF8=1
export NO_PROXY="127.0.0.1,localhost"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ -x "$REPO_ROOT/backend/.venv/Scripts/python.exe" ]; then
  PY="$REPO_ROOT/backend/.venv/Scripts/python.exe"
  PY_WIN=1
elif [ -x "$REPO_ROOT/backend/.venv/bin/python" ]; then
  PY="$REPO_ROOT/backend/.venv/bin/python"
  PY_WIN=0
else
  echo "[FATAL] 找不到 venv python，请先在 backend/ 执行 uv sync"
  exit 1
fi
echo "[PLATFORM] PY_WIN=$PY_WIN（$PY）"

if [ "$PY_WIN" = "1" ] && command -v cygpath >/dev/null 2>&1; then
  REPO_ROOT_WIN="$(cygpath -m "$REPO_ROOT")"
else
  REPO_ROOT_WIN="$REPO_ROOT"
fi

PORT=8766
BASE="http://127.0.0.1:$PORT/api"
U=richtest
curlx() { curl -s --noproxy '*' --max-time 10 "$@"; }

# ------------------------------------------------------------ 沙箱/服务生命周期
SANDBOX_ROOT="$(mktemp -d)"
if [ "$PY_WIN" = "1" ] && command -v cygpath >/dev/null 2>&1; then
  SANDBOX_ROOT_WIN="$(cygpath -m "$SANDBOX_ROOT")"
else
  SANDBOX_ROOT_WIN="$SANDBOX_ROOT"
fi
export WORKBENCH_DATA="$SANDBOX_ROOT_WIN"
UVICORN_LOG="$SANDBOX_ROOT/uvicorn.log"
echo "[SANDBOX] $SANDBOX_ROOT (WORKBENCH_DATA=$WORKBENCH_DATA)"

mkdir -p "$SANDBOX_ROOT/users"
cp -r "$REPO_ROOT/data/users/example" "$SANDBOX_ROOT/users/$U"

UVICORN_PID=""
cleanup() {
  [ -n "${UVICORN_PID:-}" ] && kill "$UVICORN_PID" 2>/dev/null && wait "$UVICORN_PID" 2>/dev/null || true
  [ -n "${SANDBOX_ROOT:-}" ] && [ -d "$SANDBOX_ROOT" ] && rm -rf "$SANDBOX_ROOT"
}
trap cleanup EXIT

start_server() {
  if curlx -o /dev/null --max-time 2 "$BASE/health" >/dev/null 2>&1; then
    echo "[FATAL] 端口 $PORT 已被占用，请先释放后重跑"
    netstat -ano | grep ":$PORT " || true
    return 1
  fi
  ( cd "$REPO_ROOT/backend" && exec "$PY" -m uvicorn app.main:app \
      --host 127.0.0.1 --port "$PORT" ) > "$UVICORN_LOG" 2>&1 &
  UVICORN_PID=$!
  local i code
  for i in $(seq 1 60); do
    code=$(curlx -o /dev/null -w '%{http_code}' --max-time 2 "$BASE/health" 2>/dev/null || true)
    [ "$code" = "200" ] && return 0
    sleep 1
  done
  echo "[FATAL] uvicorn 60 秒内未就绪，日志尾 20 行："
  tail -20 "$UVICORN_LOG" 2>/dev/null || echo "  （日志为空）"
  return 1
}
start_server
echo "[SERVER] uvicorn pid=$UVICORN_PID port=$PORT"

# ------------------------------------------------------------ me/ 只读冒烟
# me/ 只读冒烟：T2 迁移后真实备忘在 memos/（冷备份 .backup/ 不参与）
"$PY" -c "
from pathlib import Path
import frontmatter
me = Path(r'$REPO_ROOT_WIN/data/users/me/memos')
n = 0
for p in me.glob('*.md'):
    frontmatter.load(p); n += 1
print('[me 冒烟 OK] data/users/me/memos 下 %d 篇备忘均可 frontmatter 解析（只读未改）' % n)"

# ------------------------------------------------------------ 1) 图片上传
"$PY" -c "
import base64, pathlib
png = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk'
    '+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')
pathlib.Path(r'$SANDBOX_ROOT_WIN/tiny.png').write_bytes(png)"

ASSET_NAME=$(curlx -X POST "$BASE/memos/assets?user=$U" \
  -F "file=@$SANDBOX_ROOT_WIN/tiny.png;type=image/png" | "$PY" -c "
import sys, json, re
r = json.load(sys.stdin)
assert r['ok'], r
d = r['data']
assert re.match(r'^\d{8}-\d{6}-[0-9a-f]{8}\.png$', d['name']), d
assert d['path'] == 'assets/' + d['name'] and d['size'] > 0, d
assert d['content_type'] == 'image/png', d
print(d['name'])" | tr -d '\r')
export ASSET_NAME
echo "[1a OK] 图片上传 name=$ASSET_NAME"

# 落盘字节与源一致
"$PY" -c "
import pathlib, os
p = pathlib.Path(r'$SANDBOX_ROOT_WIN/users/$U/memos/assets') / os.environ['ASSET_NAME']
assert p.is_file() and p.read_bytes() == pathlib.Path(r'$SANDBOX_ROOT_WIN/tiny.png').read_bytes()
print('[1b OK] 图片落盘 memos/assets/，字节与上传一致')"

# GET 回读 200 + content-type + 字节一致
CT=$(curlx -o "$SANDBOX_ROOT_WIN/back.png" -w '%{http_code} %{content_type}' \
  "$BASE/memos/assets/$ASSET_NAME?user=$U")
[ "${CT%% *}" = "200" ] || { echo "[FATAL] 取图非 200: $CT"; exit 1; }
[ "${CT#* }" = "image/png" ] || { echo "[FATAL] content-type 异常: $CT"; exit 1; }
"$PY" -c "
import pathlib
a = pathlib.Path(r'$SANDBOX_ROOT_WIN/tiny.png').read_bytes()
b = pathlib.Path(r'$SANDBOX_ROOT_WIN/back.png').read_bytes()
assert a == b, '取图字节不一致'
print('[1c OK] GET 取图 200 image/png，字节一致')"

# 非法类型 / 伪装内容 → 422
SVG_CODE=$(curlx -o /dev/null -w '%{http_code}' -X POST "$BASE/memos/assets?user=$U" \
  -F "file=@$SANDBOX_ROOT_WIN/tiny.png;filename=x.svg;type=image/svg+xml")
[ "$SVG_CODE" = "422" ] || { echo "[FATAL] svg 应 422，实际 $SVG_CODE"; exit 1; }
"$PY" -c "import pathlib; pathlib.Path(r'$SANDBOX_ROOT_WIN/fake.png').write_bytes(b'not an image')"
FAKE_CODE=$(curlx -o /dev/null -w '%{http_code}' -X POST "$BASE/memos/assets?user=$U" \
  -F "file=@$SANDBOX_ROOT_WIN/fake.png;type=image/png")
[ "$FAKE_CODE" = "422" ] || { echo "[FATAL] 伪装图片应 422，实际 $FAKE_CODE"; exit 1; }
echo "[1d OK] svg 与伪装内容均 422"

# ------------------------------------------------------------ 2) 富文本正文往返
MEMO=$(curlx -X POST "$BASE/memos?user=$U" -H 'Content-Type: application/json' -d @- <<JSON | "$PY" -c "
import sys, json
from urllib.parse import quote
m = json.load(sys.stdin)['data']
assert m['content'].startswith('# 富文本验收'), m
assert m['id'].split('-')[1] == 'memo', 'T1：id 前缀应为 memo'
print(m['id'] + ' ' + quote(m['id'], safe=''))" | tr -d '\r'
{"title":"富文本验收","content":"# 富文本验收\n\n**粗** *斜*\n\n## 小节\n\n### 中标题\n\n#### 小标题\n\n- 无序一\n- 无序二\n\n1. 有序一\n2. 有序二\n\n| 列1 | 列2 |\n| --- | --- |\n| 1 | 2 |\n\n![](assets/$ASSET_NAME)\n","tags":["验收"]}
JSON
)
export MEMO_ID=${MEMO% *}; export MEMO_ENC=${MEMO#* }
echo "[2a OK] 建富文本备忘 id=$MEMO_ID"

# GET 回来逐字保留（strip 后比较——读侧既有行为）
curlx "$BASE/memos/$MEMO_ENC?user=$U" | "$PY" -c "
import sys, json, os
n = json.load(sys.stdin)
c = n['content']
for token in ['**粗**', '*斜*', '## 小节', '### 中标题', '#### 小标题',
              '- 无序一', '1. 有序一', '| 列1 | 列2 |', '| --- | --- |',
              '![](assets/' + os.environ['ASSET_NAME'] + ')']:
    assert token in c, '缺标记: ' + token
assert c.count('# 富文本验收') == 1, 'H1 数量异常'
print('[2b OK] GET 正文逐字保留粗/斜/H2-4/列表/表格/图片语法，H1=1')"

# GET→PUT 幂等：原样回传不产生双 H1（python 组 payload 落文件，curl -d @ 发送，
# 中文走 stdin/文件字节，避免命令行 GBK 转码）
curlx "$BASE/memos/$MEMO_ENC?user=$U" > "$SANDBOX_ROOT/memo.json"
"$PY" -c "
import json, pathlib
m = json.loads(pathlib.Path(r'$SANDBOX_ROOT_WIN/memo.json').read_text(encoding='utf-8'))
payload = {'title': m['title'], 'content': m['content'],
           'tags': m['tags'], 'related': m['related']}
pathlib.Path(r'$SANDBOX_ROOT_WIN/put.json').write_text(
    json.dumps(payload, ensure_ascii=False), encoding='utf-8')"
curlx -X PUT "$BASE/memos/$MEMO_ENC?user=$U" -H 'Content-Type: application/json' \
  -d @"$SANDBOX_ROOT_WIN/put.json" | "$PY" -c "
import sys, json
c = json.load(sys.stdin)['data']['content']
assert c.count('# 富文本验收') == 1, 'GET→PUT 产生双 H1'
print('[2c OK] GET→PUT 幂等，仍只有一个 H1')"

# ------------------------------------------------------------ 3) 数据主权：磁盘 .md 记事本可读
"$PY" -c "
import pathlib, os, frontmatter
memos = pathlib.Path(r'$SANDBOX_ROOT_WIN/users/$U/memos')
md = next(p for p in memos.glob('*.md') if '富文本' in p.name)
raw = md.read_text(encoding='utf-8')
post = frontmatter.load(md)
assert set(('id','tags','related')) <= set(post.keys()), 'frontmatter 契约键缺失'
assert '| 列1 | 列2 |' in raw and '![](assets/' + os.environ['ASSET_NAME'] + ')' in raw
print('[3 OK] 磁盘 .md 为纯文本标准 Markdown（frontmatter 契约不变，记事本/Obsidian 可开）:', md.name)"

# ------------------------------------------------------------ 4) assets/ 不进列表
curlx "$BASE/memos?user=$U" | "$PY" -c "
import sys, json
d = json.load(sys.stdin)
assert all('assets' not in m['filename'] for m in d['items']), 'assets 混入备忘列表'
print('[4 OK] assets/ 目录不进备忘列表 count=%d' % d['count'])"

# ------------------------------------------------------------ 5) 前端构建 + 后端全量测试
if command -v npm >/dev/null 2>&1; then
  ( cd "$REPO_ROOT/frontend" && npm run build ) >/dev/null \
    && echo "[5a OK] 前端 vue-tsc 类型检查 + vite build 通过"
else
  echo "[5a 跳过] 无 npm"
fi
( cd "$REPO_ROOT/backend" && "$PY" -m pytest tests/ -q ) >/dev/null \
  && echo "[5b OK] pytest 全量绿"

echo ""
echo "[备忘富文本验收通过] /api/memos 列表/表格/粗斜体/标题字号/图片全链路 OK；me/ 未被修改；沙箱将由 trap 清理"
