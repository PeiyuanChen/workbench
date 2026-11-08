#!/usr/bin/env bash
# ============================================================
# 笔记模块端到端验收脚本（T5，issue #6；里程碑 #1 收尾证据）
#
# 覆盖：
#   - 笔记 API 全链：列表形状、笔记 CRUD、改标题身份不变、跨文件夹移动、
#     删除 404 与 .backup 前缀备份；
#   - 真实文件夹：多层中文文件夹新建/同父重命名/跨父拒绝/保留名拒绝/
#     非空拒绝/不存在 404/空文件夹删除；
#   - 图片资产：根层与中文文件夹上传（扁平前缀名 + 深度相对 path）、
#     GET 字节回读、svg/伪装内容 422、含图笔记移动后链接按深度自动改写；
#   - 数据主权：磁盘 .md 记事本可读、frontmatter 固定四键且无 folder 字段、
#     data-samples/validate.py 契约闸门；
#   - T2 迁移 CLI 沙箱复演：迷你 notes 布局 → notes→memos、id 重写、
#     冷备份不动、仓库外 zip、二次执行预检拒绝（exit 1）；
#   - 后端 pytest 全绿、前端 vue-tsc + vite build（有 npm 时）。
#
# 纪律与 scripts/accept-m2.sh、accept-memos-rich.sh 完全一致（勿改回，坑均实测）：
#   - 沙箱化：mktemp 临时目录 + WORKBENCH_DATA，基底从 data/users/example
#     复制为 users/notesaccept；全部请求打 ?user=notesaccept，不碰 me/；
#   - 直启 backend/.venv 的 python -m uvicorn（绕过 uv shim，kill 不留孤儿）；
#   - 端口 8767 启动前探活，占用即 FATAL；curl 一律 --noproxy '*'；
#   - trap EXIT 杀 uvicorn + 删整个沙箱（含失败路径），零残留；
#   - 零 uv / 零网络依赖，代理/断网环境可跑。
#
# Windows 编码/路径八坑（accept-m2 头注四坑 + 2026-11-08 实测四坑，勿改回）：
#   1) export PYTHONUTF8=1 —— python 管道默认 gbk 会把 UTF-8 响应解码成 mojibake；
#   2) 中文 JSON payload 不落 curl 命令行（原生 curl.exe 按 GBK 转码）：
#      本脚本统一用 python 把 payload 写成 UTF-8 .json，再 curl --data-binary @文件；
#      git-bash 中文 heredoc 偶发被吞（delimited by end-of-file），故不依赖 heredoc 传业务数据；
#   3) 多行 python 输出经 bash 捕获带 \r，统一 tr -d '\r'；
#      嵌入 python 源码的路径用 cygpath -m 的 Windows 形式（D:/...），
#      MSYS /d/... 会被 Windows Python 当成 UNC；
#   4) 传给原生可执行文件（python.exe/curl.exe）的路径一律 Windows 形式；
#   5) curl -F 的文件 @路径不认 MSYS /tmp，必须 C:/... 形式；
#   6) multipart 中文普通字段（folder=中文）同样被 GBK 转码：
#      把 UTF-8 值写临时文件，用 curl「字段=<文件」语法；
#   7) URL path/query 里的中文（note id 含中文、folder path 参数）先百分号编码
#      （python urllib.parse.quote）再拼 URL；
#   8) 中文允许出现在 python -c 源码里（PYTHONUTF8=1 按 UTF-8 解码），
#      现有验收脚本已广泛依赖此事实；禁止出现在 curl 裸参数里。
#
# 平台：仅 Windows git-bash 实测；POSIX 路径写法有兼容回退但未 CI 验证。
# ============================================================
set -euo pipefail
export PYTHONUTF8=1
# 双保险：即使有工具绕过 curlx 走系统代理，也对回环地址直连
export NO_PROXY="127.0.0.1,localhost"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# 后端 venv 解释器探测（平台自适应）
if [ -x "$REPO_ROOT/backend/.venv/Scripts/python.exe" ]; then
  PY="$REPO_ROOT/backend/.venv/Scripts/python.exe"
  PY_WIN=1
elif [ -x "$REPO_ROOT/backend/.venv/bin/python" ]; then
  PY="$REPO_ROOT/backend/.venv/bin/python"
  PY_WIN=0
else
  echo "[FATAL] 找不到 venv python，请先在 backend/ 执行 uv sync"
  echo "        Windows: backend/.venv/Scripts/python.exe"
  echo "        POSIX:   backend/.venv/bin/python"
  exit 1
fi
echo "[PLATFORM] PY_WIN=$PY_WIN（$PY）"

if [ "$PY_WIN" = "1" ] && command -v cygpath >/dev/null 2>&1; then
  REPO_ROOT_WIN="$(cygpath -m "$REPO_ROOT")"
else
  REPO_ROOT_WIN="$REPO_ROOT"
fi

PORT=8767
BASE="http://127.0.0.1:$PORT/api"
U=notesaccept
curlx() { curl -s --noproxy '*' --max-time 10 "$@"; }

# ------------------------------------------------------------ 沙箱/服务生命周期
SANDBOX_ROOT="$(mktemp -d)"
if [ "$PY_WIN" = "1" ] && command -v cygpath >/dev/null 2>&1; then
  SANDBOX_ROOT_WIN="$(cygpath -m "$SANDBOX_ROOT")"
else
  SANDBOX_ROOT_WIN="$SANDBOX_ROOT"
fi
export WORKBENCH_DATA="$SANDBOX_ROOT_WIN"
UVICORN_LOG="$SANDBOX_ROOT/uvicorn.log"   # 仅供 bash 重定向/tail（MSYS 工具）
echo "[SANDBOX] $SANDBOX_ROOT (WORKBENCH_DATA=$WORKBENCH_DATA)"

# 复制 example 用户作为 notesaccept 基底（含 notes 根层 + k8s/ 两篇样例）
mkdir -p "$SANDBOX_ROOT/users"
cp -r "$REPO_ROOT/data/users/example" "$SANDBOX_ROOT/users/$U"

UVICORN_PID=""
cleanup() {
  [ -n "${UVICORN_PID:-}" ] && kill "$UVICORN_PID" 2>/dev/null && wait "$UVICORN_PID" 2>/dev/null || true
  [ -n "${SANDBOX_ROOT:-}" ] && [ -d "$SANDBOX_ROOT" ] && rm -rf "$SANDBOX_ROOT"
}
trap cleanup EXIT

start_server() {
  # 启动前端口检查：8767 已被占用直接 FATAL，绝不在别人的服务上假跑
  if curlx -o /dev/null --max-time 2 "$BASE/health" >/dev/null 2>&1; then
    echo "[FATAL] 端口 $PORT 已被占用，请先释放后重跑（可能是上次验收残留的 uvicorn）："
    netstat -ano | grep ":$PORT " || echo "  （netstat 未找到监听行）"
    return 1
  fi

  # 子 shell + exec：$! 即真实 python 进程 PID（kill 直达，不留孤儿）
  ( cd "$REPO_ROOT/backend" && exec "$PY" -m uvicorn app.main:app \
      --host 127.0.0.1 --port "$PORT" ) > "$UVICORN_LOG" 2>&1 &
  UVICORN_PID=$!

  # 探活：仅 HTTP 200 算就绪；60 次 × 1s
  local i code
  for i in $(seq 1 60); do
    code=$(curlx -o /dev/null -w '%{http_code}' --max-time 2 "$BASE/health" 2>/dev/null || true)
    [ "$code" = "200" ] && return 0
    sleep 1
  done
  echo "[FATAL] uvicorn 60 秒内未就绪（端口 $PORT，pid=$UVICORN_PID），日志尾 20 行："
  tail -20 "$UVICORN_LOG" 2>/dev/null || echo "  （日志为空或不存在）"
  return 1
}
start_server
echo "[SERVER] uvicorn pid=$UVICORN_PID port=$PORT（venv python 直启，无 uv shim）"

# ------------------------------------------------------------ 工具函数
# 中文 payload 一律先落 UTF-8 文件再 curl --data-binary @文件（坑 2/8）：
# dict 字面量内联在 python 源码里（PYTHONUTF8=1 按 UTF-8 解码，现有验收脚本已验证
# 此路径可靠），避免中文经过 curl 命令行/multipart 被 GBK 转码。
# $1=沙箱内文件名，$2=python dict 字面量（字符串一律用单引号，避免与 bash 双引号冲突）
write_json() {
  "$PY" -c "import json, os, pathlib
pathlib.Path(r'$SANDBOX_ROOT_WIN/$1').write_text(
    json.dumps($2, ensure_ascii=False), encoding='utf-8')"
}

# 百分号编码中文 URL query/path 段（坑 7）；值经 stdin 进 python，不经命令行
urlenc() {
  printf '%s' "$1" | "$PY" -c "
import sys
from urllib.parse import quote
print(quote(sys.stdin.read(), safe=''))" | tr -d '\r'
}

# ============================================================
# 0) me/ 只读冒烟：T2 迁移后真实数据在 memos/，且不得残留 notes/
# ============================================================
echo "=== me/ 只读冒烟（不经过服务器，只读仓库真实数据，不修改）==="
"$PY" -c "
from pathlib import Path
import frontmatter
me = Path(r'$REPO_ROOT_WIN/data/users/me')
assert not (me / 'notes').exists(), '真实 me/ 不应残留 notes/（T2 已迁移）'
memos = me / 'memos'
n = 0
for p in memos.glob('*.md'):
    post = frontmatter.load(p)
    assert str(post['id']).split('-')[1] == 'memo', ('真实备忘 id 前缀异常: ' + p.name)
    n += 1
assert n >= 1, '真实 memos/ 为空'
print('[0 OK] me/ 无 notes/ 残留，memos/ 下 %d 篇备忘均可解析且 id 均为 memo- 前缀（只读未改）' % n)"

# ============================================================
# 1) 笔记列表基线：扁平 {count, folders, items}，列表不含全文
# ============================================================
curlx "$BASE/notes?user=$U" | "$PY" -c "
import sys, json
d = json.load(sys.stdin)
assert set(d) == {'count', 'folders', 'items'}, d
assert d['count'] == 2, d
assert {'path': 'k8s', 'name': 'k8s'} in d['folders'], d
assert all('content' not in i for i in d['items']), '列表项不得含全文 content'
assert all(i['id'].split('-')[1] == 'note' for i in d['items']), 'id 必须 note- 前缀'
folders_of = {i['folder'] for i in d['items']}
assert folders_of == {'', 'k8s'}, folders_of
print('[1 OK] 基线列表：2 篇笔记（根层 + k8s/）、folders 含 k8s、列表无全文、folder 字段正确')"

# ============================================================
# 2) 文件夹生命周期：多层中文新建 → 同父重命名 → 各守卫 → 清空后删除
# ============================================================
write_json p-folder-create.json "{'path': '验收目录/子目录'}"
curlx -X POST "$BASE/notes/folders?user=$U" -H 'Content-Type: application/json' \
  --data-binary @"$SANDBOX_ROOT_WIN/p-folder-create.json" | "$PY" -c "
import sys, json
d = json.load(sys.stdin)['data']
assert d == {'path': '验收目录/子目录', 'name': '子目录'}, d
print('[2a OK] 多层中文文件夹新建（中间层一并创建）')"

curlx "$BASE/notes?user=$U" | "$PY" -c "
import sys, json
paths = {f['path'] for f in json.load(sys.stdin)['folders']}
assert {'验收目录', '验收目录/子目录'} <= paths, paths
print('[2b OK] 列表递归出现父子两个真实文件夹')"

write_json p-folder-rename.json "{'path': '验收目录/子目录', 'new_path': '验收目录/改名目录'}"
curlx -X PUT "$BASE/notes/folders?user=$U" -H 'Content-Type: application/json' \
  --data-binary @"$SANDBOX_ROOT_WIN/p-folder-rename.json" | "$PY" -c "
import sys, json
d = json.load(sys.stdin)['data']
assert d['path'] == '验收目录/改名目录', d
print('[2c OK] 同父目录重命名（os.replace 原子改名）')"

# 跨父目录移动文件夹 → 422（移动单篇笔记走 PUT folder，文件夹端点不做跨父）
write_json p-folder-cross.json "{'path': '验收目录/改名目录', 'new_path': 'k8s/改名目录'}"
[ "$(curlx -o /dev/null -w '%{http_code}' -X PUT "$BASE/notes/folders?user=$U" \
    -H 'Content-Type: application/json' --data-binary @"$SANDBOX_ROOT_WIN/p-folder-cross.json")" = "422" ]
echo "[2d OK] 跨父目录重命名 422"

# 保留名守卫：assets / .backup 均 422（ASCII payload 可内联）
[ "$(curlx -o /dev/null -w '%{http_code}' -X POST "$BASE/notes/folders?user=$U" \
    -H 'Content-Type: application/json' -d '{"path":"assets"}')" = "422" ]
[ "$(curlx -o /dev/null -w '%{http_code}' -X POST "$BASE/notes/folders?user=$U" \
    -H 'Content-Type: application/json' -d '{"path":".backup"}')" = "422" ]
echo "[2e OK] 保留名 assets/.backup 422"

# 非空文件夹拒绝删除（k8s 内有 example 样例笔记）→ 422；不存在 → 404
K8S_ENC=$(urlenc 'k8s')
[ "$(curlx -o /dev/null -w '%{http_code}' -X DELETE \
    "$BASE/notes/folders?user=$U&path=$K8S_ENC")" = "422" ]
GHOST_ENC=$(urlenc '不存在目录')
[ "$(curlx -o /dev/null -w '%{http_code}' -X DELETE \
    "$BASE/notes/folders?user=$U&path=$GHOST_ENC")" = "404" ]
echo "[2f OK] 非空文件夹 422、不存在文件夹 404（中文 query 已百分号编码）"

# ============================================================
# 3) 笔记 CRUD + 跨文件夹移动（身份不变、只换目录）
# ============================================================
write_json p-note-create.json "{'title': 'T5验收根层笔记', 'content': '根层正文初版', 'tags': ['验收'], 'related': []}"
NOTE=$(curlx -X POST "$BASE/notes?user=$U" -H 'Content-Type: application/json' \
  --data-binary @"$SANDBOX_ROOT_WIN/p-note-create.json" | "$PY" -c "
import sys, json
from urllib.parse import quote
n = json.load(sys.stdin)['data']
assert n['id'].split('-')[1] == 'note' and n['folder'] == '', n
assert n['content'].startswith('# T5验收根层笔记'), n
assert n['filename'].endswith('.md'), n
print(n['id'] + ' ' + quote(n['id'], safe=''))" | tr -d '\r')
export NOTE_ID=${NOTE% *}; export NOTE_ENC=${NOTE#* }
echo "[3a OK] 根层新建笔记 id=$NOTE_ID"

curlx "$BASE/notes/$NOTE_ENC?user=$U" | "$PY" -c "
import sys, json, os
n = json.load(sys.stdin)
assert n['id'] == os.environ['NOTE_ID'] and n['folder'] == '', n
assert '根层正文初版' in n['content'], n
print('[3b OK] GET 单篇含正文与 folder')"

export CREATED_BEFORE=$(curlx "$BASE/notes/$NOTE_ENC?user=$U" | "$PY" -c "
import sys, json; print(json.load(sys.stdin)['created'])" | tr -d '\r')
write_json p-note-rename.json "{'title': 'T5验收根层笔记-改名', 'content': '正文修订版', 'tags': ['验收', '修订'], 'related': []}"
curlx -X PUT "$BASE/notes/$NOTE_ENC?user=$U" -H 'Content-Type: application/json' \
  --data-binary @"$SANDBOX_ROOT_WIN/p-note-rename.json" | "$PY" -c "
import sys, json, os
n = json.load(sys.stdin)['data']
assert n['id'] == os.environ['NOTE_ID'], '改标题 id 不得漂移'
assert n['created'] == os.environ['CREATED_BEFORE'], 'created 不得变化'
assert n['content'].startswith('# T5验收根层笔记-改名'), n
assert '改名' in n['filename'] and n['folder'] == '', n
print('[3c OK] PUT 改标题：id/created 不变，H1 与文件名同步更新')"

# 在 k8s 文件夹新建，再移回根层：移动只换目录、id 与日期前缀不变
write_json p-note-k8s.json "{'title': 'T5验收移动笔记', 'content': '待移动正文', 'tags': ['验收'], 'folder': 'k8s'}"
MOVE=$(curlx -X POST "$BASE/notes?user=$U" -H 'Content-Type: application/json' \
  --data-binary @"$SANDBOX_ROOT_WIN/p-note-k8s.json" | "$PY" -c "
import sys, json
from urllib.parse import quote
n = json.load(sys.stdin)['data']
assert n['folder'] == 'k8s', n
print(n['id'] + ' ' + quote(n['id'], safe=''))" | tr -d '\r')
export MOVE_ID=${MOVE% *}; export MOVE_ENC=${MOVE#* }
echo "[3d OK] k8s/ 内新建笔记 id=$MOVE_ID"

"$PY" -c "
from pathlib import Path
import os, frontmatter
coll = Path(r'$SANDBOX_ROOT_WIN/users/$U/notes')
hit = [x for x in (coll / 'k8s').glob('*.md') if frontmatter.load(x).get('id') == os.environ['MOVE_ID']]
assert len(hit) == 1, 'k8s 磁盘文件未落地'
print('[3e OK] 文件夹归属由物理相对路径表达（notes/k8s/ 下真实文件）:', hit[0].name)"

write_json p-note-move-root.json "{'title': 'T5验收移动笔记', 'content': '待移动正文', 'tags': ['验收'], 'folder': ''}"
curlx -X PUT "$BASE/notes/$MOVE_ENC?user=$U" -H 'Content-Type: application/json' \
  --data-binary @"$SANDBOX_ROOT_WIN/p-note-move-root.json" | "$PY" -c "
import sys, json, os
n = json.load(sys.stdin)['data']
assert n['id'] == os.environ['MOVE_ID'] and n['folder'] == '', n
print('[3f OK] PUT 显式 folder=\"\" 移回根层，id 不变')"

"$PY" -c "
from pathlib import Path
import os, frontmatter
coll = Path(r'$SANDBOX_ROOT_WIN/users/$U/notes')
root_hit = [x for x in coll.glob('*.md') if frontmatter.load(x).get('id') == os.environ['MOVE_ID']]
k8s_left = [x for x in (coll / 'k8s').glob('*.md') if frontmatter.load(x).get('id') == os.environ['MOVE_ID']]
assert len(root_hit) == 1 and not k8s_left, '移动后新旧目录状态异常'
print('[3g OK] 磁盘上只换目录：根层存在、k8s/ 旧文件已删除')"

curlx -X DELETE "$BASE/notes/$MOVE_ENC?user=$U" | "$PY" -c "
import sys, json
assert json.load(sys.stdin)['ok']
print('[3h OK] DELETE 笔记')"
[ "$(curlx -o /dev/null -w '%{http_code}' "$BASE/notes/$MOVE_ENC?user=$U")" = "404" ]
echo "[3i OK] 删除后 GET 404"

# 移动 + 删除都应在 notes/.backup 留扁平备份，且 k8s 旧路径备份带文件夹前缀
"$PY" -c "
from pathlib import Path
bak = Path(r'$SANDBOX_ROOT_WIN/users/$U/notes/.backup')
files = [p.name for p in bak.glob('*.md')]
assert files, '笔记写操作未产生 .backup 备份'
assert any(n.startswith('k8s__') for n in files), ('缺 k8s 文件夹前缀备份: ' + str(files))
print('[3j OK] notes/.backup 扁平备份存在，移动前旧路径备份带 k8s__ 前缀：%d 份' % len(files))"

# ============================================================
# 4) 图片资产：根层/中文文件夹上传、字节回读、安全闸门、移动改写链接
# ============================================================
"$PY" -c "
import base64, pathlib
png = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk'
    '+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')
pathlib.Path(r'$SANDBOX_ROOT_WIN/tiny.png').write_bytes(png)
pathlib.Path(r'$SANDBOX_ROOT_WIN/fake.png').write_bytes(b'not an image')"

ASSET_ROOT=$(curlx -X POST "$BASE/notes/assets?user=$U" \
  -F "file=@$SANDBOX_ROOT_WIN/tiny.png;type=image/png" | "$PY" -c "
import sys, json, re
d = json.load(sys.stdin)['data']
assert re.match(r'^\d{8}-\d{6}-[0-9a-f]{8}\.png$', d['name']), d
assert d['path'] == 'assets/' + d['name'] and d['size'] > 0, d
assert d['content_type'] == 'image/png', d
print(d['name'])" | tr -d '\r')
export ASSET_ROOT
echo "[4a OK] 根层资产上传 name=$ASSET_ROOT（无前缀，path=assets/...）"

# 中文文件夹的 multipart 普通字段：值写文件用「folder=<文件」（坑 6）
"$PY" -c "
import pathlib
pathlib.Path(r'$SANDBOX_ROOT_WIN/folder.txt').write_text('验收目录/改名目录', encoding='utf-8')"
ASSET_CN=$(curlx -X POST "$BASE/notes/assets?user=$U" \
  -F "folder=<$SANDBOX_ROOT_WIN/folder.txt" \
  -F "file=@$SANDBOX_ROOT_WIN/tiny.png;type=image/png" | "$PY" -c "
import sys, json, re
d = json.load(sys.stdin)['data']
assert re.match(r'^验收目录__改名目录__\d{8}-\d{6}-[0-9a-f]{8}\.png$', d['name']), d
assert d['path'] == '../../assets/' + d['name'], d
print(d['name'])" | tr -d '\r')
echo "[4b OK] 中文深度 2 文件夹资产：磁盘名带扁平前缀，path 自动带 ../../"

# GET 回读：200 + image/png + 字节一致
CT=$(curlx -o "$SANDBOX_ROOT_WIN/back.png" -w '%{http_code} %{content_type}' \
  "$BASE/notes/assets/$ASSET_ROOT?user=$U")
[ "${CT%% *}" = "200" ] || { echo "[FATAL] 取图非 200: $CT"; exit 1; }
[ "${CT#* }" = "image/png" ] || { echo "[FATAL] content-type 异常: $CT"; exit 1; }
"$PY" -c "
import pathlib
a = pathlib.Path(r'$SANDBOX_ROOT_WIN/tiny.png').read_bytes()
b = pathlib.Path(r'$SANDBOX_ROOT_WIN/back.png').read_bytes()
assert a == b, '取图字节不一致'
print('[4c OK] GET 取图 200 image/png，字节与上传一致')"

# 安全闸门：伪装 svg 扩展名 / 非图片 magic byte 均 422
[ "$(curlx -o /dev/null -w '%{http_code}' -X POST "$BASE/notes/assets?user=$U" \
  -F "file=@$SANDBOX_ROOT_WIN/tiny.png;filename=x.svg;type=image/svg+xml")" = "422" ]
[ "$(curlx -o /dev/null -w '%{http_code}' -X POST "$BASE/notes/assets?user=$U" \
  -F "file=@$SANDBOX_ROOT_WIN/fake.png;type=image/png")" = "422" ]
echo "[4d OK] svg 扩展名与伪装内容均 422（magic byte 嗅探 + 白名单）"

# 含图笔记：k8s（深度 1）创建时裸 assets/ 链接归一为 ../assets/，
# 再移回根层（深度 0），服务端按新深度自动改写为 assets/（移动不裂图）。
# 深度 2 的 path 规则已由 4b（验收目录/改名目录 → ../../assets/）覆盖。
write_json p-note-image.json "{'title': 'T5验收图片笔记', 'content': '![](assets/' + os.environ['ASSET_ROOT'] + ')', 'tags': [], 'folder': 'k8s'}"
IMG=$(curlx -X POST "$BASE/notes?user=$U" -H 'Content-Type: application/json' \
  --data-binary @"$SANDBOX_ROOT_WIN/p-note-image.json" | "$PY" -c "
import sys, json, os
from urllib.parse import quote
n = json.load(sys.stdin)['data']
assert n['folder'] == 'k8s', n
assert ('../assets/' + os.environ['ASSET_ROOT']) in n['content'], n
assert '../../' not in n['content'], '深度 1 只应有单层 ../'
print(n['id'] + ' ' + quote(n['id'], safe=''))" | tr -d '\r')
export IMG_ID=${IMG% *}; export IMG_ENC=${IMG#* }
echo "[4e OK] 深度 1 笔记正文链接自动归一为 ../assets/（深度 2 的 ../../ 规则见 4b）"

write_json p-note-image-move.json "{'title': 'T5验收图片笔记', 'content': '![](assets/' + os.environ['ASSET_ROOT'] + ')', 'tags': [], 'folder': ''}"
curlx -X PUT "$BASE/notes/$IMG_ENC?user=$U" -H 'Content-Type: application/json' \
  --data-binary @"$SANDBOX_ROOT_WIN/p-note-image-move.json" | "$PY" -c "
import sys, json, os
n = json.load(sys.stdin)['data']
assert n['folder'] == '', n
assert ('assets/' + os.environ['ASSET_ROOT']) in n['content'], n
assert '../' not in n['content'], '根层链接不得残留 ../'
print('[4f OK] 移回根层后图片链接按深度改写为 assets/（通用 Markdown 工具打开不裂图）')"

# 数据主权：磁盘 .md 是纯文本、frontmatter 固定四键且无 folder 字段
"$PY" -c "
from pathlib import Path
import os, frontmatter
coll = Path(r'$SANDBOX_ROOT_WIN/users/$U/notes')
hit = [p for p in coll.glob('*.md') if frontmatter.load(p).get('id') == os.environ['IMG_ID']]
assert len(hit) == 1
raw = hit[0].read_text(encoding='utf-8')
post = frontmatter.load(hit[0])
assert set(post.metadata.keys()) == {'id', 'created', 'tags', 'related'}, post.metadata.keys()
assert 'folder' not in raw.split('---', 2)[1], 'frontmatter 不得出现 folder 字段'
assert '# T5验收图片笔记' in raw and ('assets/' + os.environ['ASSET_ROOT']) in raw
print('[4g OK] 磁盘 .md 纯文本可读：frontmatter 固定四键、归属仅由路径表达，记事本/Obsidian 可开')"

curlx -X DELETE "$BASE/notes/$IMG_ENC?user=$U" | "$PY" -c "
import sys, json; assert json.load(sys.stdin)['ok']; print('[4h-1 OK] 图片笔记删除 ok')"
curlx -X DELETE "$BASE/notes/$NOTE_ENC?user=$U" | "$PY" -c "
import sys, json; assert json.load(sys.stdin)['ok']; print('[4h-2 OK] 改名笔记删除 ok')"
[ "$(curlx -o /dev/null -w '%{http_code}' "$BASE/notes/$IMG_ENC?user=$U")" = "404" ]
[ "$(curlx -o /dev/null -w '%{http_code}' "$BASE/notes/$NOTE_ENC?user=$U")" = "404" ]
echo "[4h OK] 清理两篇验收笔记，删除后均 404"

# ============================================================
# 5) 空文件夹收尾删除 + 列表回到基线
# ============================================================
CHILD_ENC=$(urlenc '验收目录/改名目录')
PARENT_ENC=$(urlenc '验收目录')
curlx -X DELETE "$BASE/notes/folders?user=$U&path=$CHILD_ENC" | "$PY" -c "
import sys, json; assert json.load(sys.stdin)['ok']; print('[5a OK] 空子文件夹删除成功')"
curlx -X DELETE "$BASE/notes/folders?user=$U&path=$PARENT_ENC" | "$PY" -c "
import sys, json; assert json.load(sys.stdin)['ok']; print('[5b OK] 空父文件夹删除成功')"

curlx "$BASE/notes?user=$U" | "$PY" -c "
import sys, json
d = json.load(sys.stdin)
assert d['count'] == 2, d
assert [f['path'] for f in d['folders']] == ['k8s'], d
assert all('T5' not in i['title'] for i in d['items']), '验收临时笔记残留'
print('[5c OK] 列表回到基线：2 篇 example 笔记、仅 k8s 文件夹、无验收残留')"

# ============================================================
# 6) 数据主权闸门：validate.py 契约校验（含 notes 递归 + memos + ics）
# ============================================================
"$PY" "$REPO_ROOT_WIN/data-samples/validate.py" "$SANDBOX_ROOT_WIN/users/$U" >/dev/null \
  && echo "[6 OK] validate.py 契约校验通过（ics + memos + notes 递归，保留子树排除）"

# ============================================================
# 7) T2 迁移 CLI 沙箱复演（独立迷你 notes 布局，不碰服务器与真实 me/）
# ============================================================
echo "=== T2 迁移 CLI 沙箱复演 ==="
"$PY" -c "
import pathlib
root = pathlib.Path(r'$SANDBOX_ROOT_WIN/mig/me')
notes = root / 'notes'
(notes / '.backup').mkdir(parents=True)
(notes / 'assets').mkdir(parents=True)
def md(doc_id, title):
    return ('---\nid: %s\ncreated: 2026-09-14\ntags: [测试]\nrelated: []\n---\n\n'
            '# %s\n\n正文内容，保持不变。\n' % (doc_id, title))
(notes / '2026-09-14-甲.md').write_text(md('20260914-note-甲', '甲'), encoding='utf-8')
(notes / '2026-09-15-乙.md').write_text(md('20260915-note-乙', '乙'), encoding='utf-8')
(notes / '.backup' / '2026-09-01-冷备份.md').write_text(
    md('20260901-note-cold', '冷备份'), encoding='utf-8')
(notes / 'assets' / 'pic.png').write_bytes(b'\x89PNG\r\n\x1a\n-binary-')
(root / 'calendar.ics').write_bytes(b'BEGIN:VCALENDAR\nEND:VCALENDAR\n')
print('[7a OK] 迷你 notes 布局夹具就绪（2 活跃 + 1 冷备份 + 1 资产 + calendar.ics）')"

MIG_USER_WIN="$SANDBOX_ROOT_WIN/mig/me"
MIG_BAK_WIN="$SANDBOX_ROOT_WIN/mig-backups"
MIG_LOG="$SANDBOX_ROOT/mig.out"
"$PY" "$REPO_ROOT_WIN/scripts/migrate-notes-to-memos.py" \
  --user-dir "$MIG_USER_WIN" --backup-dir "$MIG_BAK_WIN" | tee "$MIG_LOG"
[ "${PIPESTATUS[0]}" = "0" ] || { echo "[FATAL] 迁移 CLI 退出码非 0"; exit 1; }
grep -q '\[迁移完成\]' "$MIG_LOG"
echo "[7b OK] 迁移 CLI 退出码 0 且打印 [迁移完成] 证据"

"$PY" -c "
from pathlib import Path
import frontmatter, zipfile
root = Path(r'$MIG_USER_WIN')
assert not (root / 'notes').exists(), '旧 notes/ 应消失'
memos = root / 'memos'
assert memos.is_dir(), 'memos/ 应存在'
assert frontmatter.load(memos / '2026-09-14-甲.md')['id'] == '20260914-memo-甲'
assert frontmatter.load(memos / '2026-09-15-乙.md')['id'] == '20260915-memo-乙'
# 冷备份保持原样：id 不重写
cold = frontmatter.load(memos / '.backup' / '2026-09-01-冷备份.md')
assert cold['id'] == '20260901-note-cold', '冷备份不得重写'
# 资产与 calendar 字节不变
assert (memos / 'assets' / 'pic.png').read_bytes() == b'\x89PNG\r\n\x1a\n-binary-'
assert (root / 'calendar.ics').read_bytes() == b'BEGIN:VCALENDAR\nEND:VCALENDAR\n'
zips = list(Path(r'$MIG_BAK_WIN').glob('*.zip'))
assert len(zips) == 1, ('仓库外备份应恰好 1 个 zip: ' + str(zips))
with zipfile.ZipFile(zips[0]) as zf:
    assert 'me/notes/2026-09-14-甲.md' in zf.namelist()
print('[7c OK] 落盘核验：notes→memos、活跃 id 重写、冷备份原样、资产/ics 无损、仓库外 zip 备份')"

# 一次性闸门：对已迁移目录再跑必须被预检拒绝（exit 1），且不产生新备份
set +e
"$PY" "$REPO_ROOT_WIN/scripts/migrate-notes-to-memos.py" \
  --user-dir "$MIG_USER_WIN" --backup-dir "$SANDBOX_ROOT_WIN/mig-backups-2" \
  > "$SANDBOX_ROOT/mig2.out" 2> "$SANDBOX_ROOT/mig2.err"
RC2=$?
set -e
[ "$RC2" != "0" ] || { echo "[FATAL] 二次执行应被拒绝"; exit 1; }
grep -q '迁移失败' "$SANDBOX_ROOT/mig2.err"
[ ! -e "$SANDBOX_ROOT_WIN/mig-backups-2" ]
echo "[7d OK] 防重复执行预检：二次运行 exit $RC2、中文报错、无新备份产生"

# ============================================================
# 8) 后端全量测试 + 前端类型门/构建
# ============================================================
(cd "$REPO_ROOT/backend" && "$PY" -m pytest tests/ -q) >/dev/null \
  && echo "[8a OK] pytest 全量绿"
if command -v npm >/dev/null 2>&1; then
  ( cd "$REPO_ROOT/frontend" && npm run build ) >/dev/null \
    && echo "[8b OK] 前端 vue-tsc 类型检查 + vite build 通过"
else
  echo "[8b 跳过] 无 npm"
fi

echo ""
echo "[笔记模块验收通过] 笔记 API 链/文件夹/移动/资产/数据主权/迁移 CLI 全链路 OK；me/ 未被修改；沙箱将由 trap 清理"
