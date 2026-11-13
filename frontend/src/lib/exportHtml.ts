// 笔记导出：单篇 Markdown → 自包含 HTML（图片以 base64 data URI 内嵌）。
//
// 纯前端实现：Markdown 渲染复用 lib/markdown（与预览同一套规则），
// 图片经资产接口同源 GET 取回后内嵌，导出文件离线/换机可独立打开。
// - 只内嵌「同源」图片（即正文里相对 assets/ 的本地图片，已被改写为
//   /api/{模块}/assets/<名>）；外链（跨域 http(s)）与 data:/blob: 原样保留。
// - 导出是只读派生物：不写 data/、不改数据契约。
// - 图片取回失败（已删除/404）时保留原链接，并在结果里计数回报，不吞错。
import { renderMarkdown } from "./markdown";

export interface ExportOptions {
  title: string;
  /** 完整 Markdown 源（含标题 H1，与预览源一致） */
  markdown: string;
  /** 数据目录参数（me/example…） */
  user?: string;
  /** 资产 HTTP 基址（笔记传 /api/notes/assets） */
  imageBase?: string;
}

export interface ExportResult {
  fileName: string;
  /** 成功内嵌的图片张数（同一张图复用只算一次请求，但按标签数计） */
  inlined: number;
  /** 取图失败、保留原链接的图片 src 列表 */
  failed: string[];
}

export interface BuiltExport extends ExportResult {
  /** 完整的自包含 HTML 文本（与下载内容一致，便于测试/复用） */
  htmlText: string;
}

/**
 * 导出页样式：与 app.css 中 .md-body 块保持一致。
 * 导出页会脱离应用独立打开，不能继承全局样式，故变量与规则在此自带；
 * 改 md-body 视觉时需同步这里（这是唯一允许的样式副本，避免引入构建期
 * CSS 抽取依赖）。深浅双主题：深色 token 与 app.css 的
 * :root[data-theme="dark"]（磁青）一致，按读者系统偏好生效；打印强制浅色。
 */
const EXPORT_CSS = `
:root {
  color-scheme: light dark;
  --paper: #f3f4f1;
  --surface: #fdfdfc;
  --ink: #222624;
  --muted: #6e726c;
  --line: #dbddd6;
  --line-strong: #c6c9c0;
  --accent: #36557f;
  --stone-soft: #ecebe6;
  --font-serif: "Noto Serif SC", "Source Han Serif SC", "Songti SC", "STSong",
    "SimSun", Georgia, serif;
  --font-sans: "Noto Sans SC", "PingFang SC", "Microsoft YaHei", system-ui,
    -apple-system, "Segoe UI", sans-serif;
  --font-mono: ui-monospace, "Cascadia Mono", Consolas, "Courier New", monospace;
  --r-control: 3px;
}
/* 深色「磁青」：跟随读者系统偏好；取值与 app.css :root[data-theme="dark"] 一致 */
@media (prefers-color-scheme: dark) {
  :root {
    --paper: #191d25;
    --surface: #21262e;
    --ink: #d8dad3;
    --muted: #8b9189;
    --line: #2a303a;
    --line-strong: #3b4250;
    --accent: #91b0d6;
    --stone-soft: #262b34;
  }
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--paper);
  color: var(--ink);
  font-family: var(--font-sans);
  padding: 48px 16px 72px;
  -webkit-font-smoothing: antialiased;
}
.export-page {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 6px;
  max-width: 820px;
  margin: 0 auto;
  padding: 40px 48px 56px;
}
.md-body { font-size: 13.5px; line-height: 1.85; color: var(--ink); word-break: break-word; }
.md-body :first-child { margin-top: 0; }
.md-body :last-child { margin-bottom: 0; }
.md-body h1 { font-family: var(--font-serif); font-size: 21px; font-weight: 600; margin: 14px 0 8px; }
.md-body h2 { font-family: var(--font-serif); font-size: 18px; font-weight: 600; margin: 16px 0 8px; }
.md-body h3 { font-family: var(--font-serif); font-size: 15.5px; font-weight: 600; margin: 14px 0 6px; }
.md-body h4 { font-size: 13.5px; font-weight: 600; margin: 12px 0 6px; }
.md-body p { margin: 6px 0; }
.md-body ul { list-style: disc; padding-left: 1.5em; margin: 6px 0; }
.md-body ol { list-style: decimal; padding-left: 1.5em; margin: 6px 0; }
.md-body li { margin: 2px 0; }
.md-body li > ul, .md-body li > ol { margin: 2px 0; }
.md-body a { color: var(--accent); text-decoration: none; }
.md-body a:hover { text-decoration: underline; }
.md-body strong { font-weight: 700; }
.md-body em { font-style: italic; }
.md-body blockquote {
  border-left: 3px solid var(--line-strong); padding-left: 10px; margin: 8px 0;
  color: var(--muted);
}
.md-body code {
  background: var(--stone-soft); border-radius: 2px; padding: 1px 5px;
  font-family: var(--font-mono); font-size: 12px;
}
.md-body pre {
  background: var(--stone-soft); border: 1px solid var(--line); border-radius: var(--r-control);
  padding: 10px 12px; overflow-x: auto; margin: 8px 0;
}
.md-body pre code { background: none; padding: 0; }
.md-body table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 12.5px; }
.md-body th, .md-body td { border: 1px solid var(--line); padding: 5px 10px; text-align: left; }
.md-body th { background: var(--stone-soft); font-weight: 600; }
.md-body img { max-width: 100%; height: auto; border-radius: var(--r-control); border: 1px solid var(--line); margin: 8px 0; }
.md-body hr { border: 0; border-top: 1px solid var(--line); margin: 14px 0; }
@media (max-width: 640px) {
  body { padding: 16px 0 32px; }
  .export-page { border-radius: 0; border-left: 0; border-right: 0; padding: 24px 18px 32px; }
}
@media print {
  /* 打印强制浅色纸墨：深色系统下避免白纸配浅灰字 */
  :root {
    --paper: #f3f4f1;
    --surface: #fdfdfc;
    --ink: #222624;
    --muted: #6e726c;
    --line: #dbddd6;
    --line-strong: #c6c9c0;
    --accent: #36557f;
    --stone-soft: #ecebe6;
  }
  body { background: #fff; padding: 0; }
  .export-page { border: 0; padding: 0; max-width: none; }
}
`;

/** 文件名清洗：去 Windows 非法字符、尾部点/空格，限长，兜底「未命名笔记」 */
export function sanitizeExportFilename(title: string): string {
  const cleaned = title
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 80)
    .replace(/[. ]+$/, "");
  return cleaned || "未命名笔记";
}

function escapeHtml(s: string): string {
  const map: Record<string, string> = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  };
  return s.replace(/[&<>"']/g, (c) => map[c]);
}

/** ArrayBuffer → base64（分块拼接，避免大图 spread 爆调用栈） */
function toBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

/** 仅同源 http(s) 资源可内嵌；外链/协议相对/data:/blob: 一律不动 */
function isInlinable(src: string): boolean {
  if (!src || src.startsWith("data:") || src.startsWith("blob:")) return false;
  try {
    return new URL(src, window.location.href).origin === window.location.origin;
  } catch {
    return false;
  }
}

async function fetchAsDataUri(src: string): Promise<string> {
  const res = await fetch(src);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const buf = await res.arrayBuffer();
  const mime =
    res.headers.get("content-type")?.split(";")[0]?.trim() || "application/octet-stream";
  return `data:${mime};base64,${toBase64(buf)}`;
}

/**
 * 构建自包含 HTML 文本（不下载），返回文件名与内嵌统计。
 * 以 detached document 收集图片再替换，不把中间片段插入页面，避免误触发图片请求。
 */
export async function buildExportHtml(opts: ExportOptions): Promise<BuiltExport> {
  const title = opts.title.trim() || "未命名";
  const bodyHtml = renderMarkdown(opts.markdown, {
    user: opts.user,
    imageBase: opts.imageBase ?? "/api/notes/assets",
  });

  const doc = new DOMParser().parseFromString(bodyHtml, "text/html");
  const imgs = Array.from(doc.querySelectorAll("img"));
  const cache = new Map<string, string>(); // src → data URI（同图只取一次）
  const failed: string[] = [];
  let inlined = 0;

  for (const img of imgs) {
    const src = img.getAttribute("src");
    if (!src || !isInlinable(src)) continue;
    let dataUri = cache.get(src);
    if (dataUri === undefined) {
      try {
        dataUri = await fetchAsDataUri(src);
        cache.set(src, dataUri);
      } catch {
        failed.push(src);
        continue;
      }
    }
    img.setAttribute("src", dataUri);
    inlined += 1;
  }

  const htmlText = `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)}</title>
<style>${EXPORT_CSS}</style>
</head>
<body>
<main class="export-page">
<article class="md-body">${doc.body.innerHTML}</article>
</main>
</body>
</html>
`;

  return {
    htmlText,
    fileName: `${sanitizeExportFilename(title)}.html`,
    inlined,
    failed,
  };
}

/** 生成并下载自包含 HTML（构建逻辑见 buildExportHtml，下载仅 Blob + <a download>） */
export async function exportNoteHtml(opts: ExportOptions): Promise<ExportResult> {
  const built = await buildExportHtml(opts);
  const url = URL.createObjectURL(
    new Blob([built.htmlText], { type: "text/html;charset=utf-8" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = built.fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return { fileName: built.fileName, inlined: built.inlined, failed: built.failed };
}