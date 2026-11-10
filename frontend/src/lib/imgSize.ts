// 图片尺寸 alt 约定（渲染层纯函数，MarkdownView 专用）。
//
// 写法（指令写在标准 Markdown 图片的 alt 字段里）：
//   ![w=300](a.png)        宽 300px，高度等比
//   ![w=50%](b.png)        宽为正文区的 50%
//   ![w=300 架构图](c.png) 宽 300px，剥除指令后真实 alt 为「架构图」
//
// 数据主权：指令只是 alt 文本，.md 文件仍是标准 Markdown。不识别该约定的
// 工具（记事本/Obsidian/GitHub 等）把它当普通图片显示原图，绝不裂图。
// 缺省单位按 px；窄屏溢出由 CSS 的 max-width:100% 兜底。

export interface ImageSize {
  /** 渲染到 img 的 style 值，如 width:300px / width:50% */
  style: string;
  /** 剥除尺寸指令后的真实 alt（可能为空串） */
  alt: string;
}

/**
 * 解析 alt 里的尺寸指令。仅当整个 alt 是「w=数字[px|%] [剩余说明]」形态时命中，
 * 普通 alt（如「架构图」「截图 w=300」）一律返回 null，避免误伤。
 */
export function parseImageSizeAlt(alt: string): ImageSize | null {
  const m = /^w=(\d+(?:\.\d+)?)(px|%)?(?:\s+(.*))?$/.exec(alt.trim());
  if (!m) return null;
  const num = Number(m[1]);
  if (!Number.isFinite(num) || num <= 0) return null;
  const style = `width:${num}${m[2] === "%" ? "%" : "px"}`;
  return { style, alt: (m[3] ?? "").trim() };
}
