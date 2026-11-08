// Markdown 编辑器（textarea）选区操作纯函数。
//
// 统一以 { value, selStart, selEnd } 为入参/出参；组件在调用后 nextTick 把
// selStart/selEnd 写回 textarea。所有函数不依赖 DOM，便于理解与单测。

export interface EditState {
  value: string;
  selStart: number;
  selEnd: number;
}

export type PrefixKind = "h2" | "h3" | "h4" | "ul" | "ol";

/** 表格模板：前导空行（markdown-it 要求表头前必须有空行才成表） */
export const TABLE_TEMPLATE = "\n| 列1 | 列2 | 列3 |\n| --- | --- | --- |\n|  |  |  |\n";

const H_PREFIX: Record<string, string> = { h2: "## ", h3: "### ", h4: "#### " };

/** 剥离正文首行 H1（标题由独立标题框承载，编辑区不出现 H1）；无 H1 则原样返回 */
export function stripLeadH1(content: string): string {
  const m = /^#[ \t]+\S.*\n?/.exec(content);
  if (!m || !/^#[ \t]+/.test(m[0])) return content;
  return content.slice(m[0].length).replace(/^\n+/, "");
}

/** 行内包裹：**粗体** / *斜体*；有选区包选区并选中文内文字，无选区插空对 */
export function wrapInline(s: EditState, marker: "**" | "*"): EditState {
  const { value, selStart, selEnd } = s;
  const selected = value.slice(selStart, selEnd);
  const next = value.slice(0, selStart) + marker + selected + marker + value.slice(selEnd);
  if (selStart === selEnd) {
    const caret = selStart + marker.length;
    return { value: next, selStart: caret, selEnd: caret };
  }
  return { value: next, selStart: selStart + marker.length, selEnd: selEnd + marker.length };
}

function prefixOf(line: string): { kind: PrefixKind | null; body: string } {
  if (/^#{1,6}\s/.test(line)) {
    const level = line.match(/^#+/)![0].length;
    const kind = (H_PREFIX[`h${level}`] ? `h${level}` : null) as PrefixKind | null;
    return { kind, body: kind ? line.replace(/^#+\s+/, "") : line };
  }
  if (/^[-*+]\s/.test(line)) return { kind: "ul", body: line.replace(/^[-*+]\s+/, "") };
  if (/^\d+\.\s/.test(line)) return { kind: "ol", body: line.replace(/^\d+\.\s+/, "") };
  return { kind: null, body: line };
}

/** 行前缀切换：H2/H3/H4、无序/有序列表；跨行选区逐行处理，已是同类则摘除 */
export function toggleLinePrefix(s: EditState, kind: PrefixKind): EditState {
  const { value, selStart, selEnd } = s;
  const lineStart = value.lastIndexOf("\n", selStart - 1) + 1;
  let lineEnd = value.indexOf("\n", selEnd);
  if (lineEnd === -1) lineEnd = value.length;

  const block = value.slice(lineStart, lineEnd);
  const lines = block.split("\n");
  const wantHead = H_PREFIX[kind] ?? (kind === "ul" ? "- " : "1. ");
  const isHeading = kind.startsWith("h");

  const out = lines.map((line, i) => {
    if (line.trim() === "") return line; // 空行不加前缀
    const cur = prefixOf(line);
    // 已是同级 → 摘除；是别的前缀 → 替换；无前缀 → 加上
    const head = isHeading
      ? wantHead
      : kind === "ul"
        ? "- "
        : `${i + 1}. `;
    if (cur.kind === kind) return cur.body;
    if (cur.kind !== null) {
      if (kind === "ol") return `${i + 1}. ${cur.body}`;
      return `${head}${cur.body}`;
    }
    return `${head}${line}`;
  });

  const nextBlock = out.join("\n");
  const next = value.slice(0, lineStart) + nextBlock + value.slice(lineEnd);
  return { value: next, selStart: lineStart, selEnd: lineStart + nextBlock.length };
}

/**
 * 在光标处插入块级文本（图片/表格）：保证与前文之间有空行。
 * focus [起, 止] 为相对插入内容开头的最终选区（如表格首个空格）。
 */
export function insertBlock(s: EditState, block: string, focus: [number, number]): EditState {
  const { value, selStart } = s;
  let insert = block;
  let at = selStart;
  const before = value.slice(0, at);
  // 插入位置不在行首 → 先换行；前文紧邻非空行 → 补一个空行
  if (at > 0 && !before.endsWith("\n")) {
    insert = `\n${insert}`;
  }
  const prevLine = before.split("\n").at(-1) ?? "";
  if (prevLine.trim() !== "") {
    insert = `\n${insert}`;
  }
  const next = value.slice(0, at) + insert + value.slice(at);
  const base = at + insert.indexOf(block); // block 在 insert 内的起点
  return { value: next, selStart: base + focus[0], selEnd: base + focus[1] };
}

// ------------------------------------------------- 备忘/笔记共享的文档级纯函数

/** 标签输入框 → 标签数组（中英文逗号分隔，去空白与空项） */
export function parseTagsInput(input: string): string[] {
  return input
    .split(/[,，]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** 预览源：标题以 H1 合成（仅渲染，从不入库；编辑区不出现 H1） */
export function composePreview(title: string, body: string): string {
  return `# ${title.trim() || "未命名"}\n\n${body}`;
}

/**
 * 保存正文：统一由前端合成首行 H1，恒命中服务端 _compose_body 的"首行匹配"分支，
 * GET→PUT 幂等、杜绝双 H1；正文为空时只保留 H1 行。
 */
export function composeDocBody(title: string, body: string): string {
  const trimmed = body.trim();
  return trimmed ? `# ${title}\n\n${trimmed}` : `# ${title}\n`;
}
