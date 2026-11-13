// Markdown 渲染内核（备忘正文 / 笔记预览 / 时间线 / HTML 导出共用）。
//
// 安全：markdown-it 配置 html:false —— 原始 HTML 一律转义为文本，
// href/src 经其 validateLink 过滤 javascript:/vbscript: 等协议，
// 故 v-html 安全，无需 DOMPurify。
// 红线：将来若打开 html:true，必须同时引入 HTML 消毒（DOMPurify）。
import MarkdownIt, { type RendererRule } from "markdown-it";
import { parseImageSizeAlt } from "./imgSize";

export interface MarkdownRenderOptions {
  /** 数据目录参数（me/example…），拼到图片请求 query 上 */
  user?: string;
  /** 相对 assets/ 图片的 HTTP 前缀；null = 不改写（时间线 M3 前无图片） */
  imageBase?: string | null;
}

/** 备忘的资产基址（组件历史默认值）；笔记传 /api/notes/assets */
export const DEFAULT_IMAGE_BASE = "/api/memos/assets";

const PROTO_RE = /^[a-z][a-z0-9+.-]*:/i;

/**
 * 把正文中的相对 assets/ 图片改写到后端图片接口。
 * 必须改写：hash 路由页面 URL 是 /#/memos，相对 "assets/x.png" 会被浏览器
 * 解析成 /assets/x.png（不在 /api 代理下，404）。
 * 三种相对前缀都认（与后端 _ASSET_LINK_RE 对齐）：
 *   备忘/根层笔记 assets/x.png；./assets/x.png；
 *   多层文件夹笔记 ../../assets/x.png（深度前缀只用于文件系统导航，
 *   HTTP 端点仍是平铺的 /api/{模块}/assets/<名>，改写时整段丢弃）。
 * 注意 imageBase 已含末尾 /assets，正文里的 assets/ 段是磁盘目录名、
 * 不是 URL 段，拼 URL 时必须剥掉（否则双 assets 段 → 404）。
 * 返回 null 表示不动（外链/绝对路径/异常路径）。
 */
export function rewriteAssetSrc(
  src: string,
  imageBase: string | null,
  user = "",
): string | null {
  if (imageBase === null) return null;
  let s = src.trim();
  if (!s) return null;
  if (PROTO_RE.test(s) || s.startsWith("//") || s.startsWith("/") || s.startsWith("#")) {
    return null;
  }
  if (s.startsWith("./")) s = s.slice(2);
  // 仅允许「任意层 ../ 前缀 + assets/ + 余下名字」，捕获组 2 即去掉 assets/ 段后的名字
  const m = /^((?:\.\.\/)*)assets\/(.+)$/.exec(s);
  if (!m) return null;
  const parts = m[2].split("/");
  if (parts.some((p) => p === ".." || p === "")) return null;
  // markdown-it 的 normalizeLink 已对非 ASCII 做过一次 percent-encode，
  // 这里先 decode 再 encode 做幂等归一：纯 ASCII 名不受影响，中文资产名
  // （笔记文件夹扁平前缀可含中文）避免被二次编码成 %25E8… 而 404。
  const encoded = parts
    .map((p) => {
      try {
        return encodeURIComponent(decodeURIComponent(p));
      } catch {
        return encodeURIComponent(p); // 畸形 % 序列兜底，不吞图
      }
    })
    .join("/");
  const qs = user ? `?user=${encodeURIComponent(user)}` : "";
  return `${imageBase}/${encoded}${qs}`;
}

// 实例类型：markdown-it 的类型声明只导出构造器值，实例接口用 ReturnType 取
type MarkdownItInstance = ReturnType<typeof MarkdownIt>;

// 按 (imageBase, user) 缓存实例：渲染规则闭包只依赖这两个参数，渲染本身无状态
const instances = new Map<string, MarkdownItInstance>();

function getInstance(imageBase: string | null, user: string): MarkdownItInstance {
  const key = `${imageBase ?? "\u0000null"}\u0000${user}`;
  const hit = instances.get(key);
  if (hit) return hit;

  // breaks: true —— GFM 风格软换行：段落内单个换行渲染为 <br>。
  // 严格 CommonMark 下单换行只是空格，但本工作台的备忘/笔记书写习惯是
  // 「Enter 即换行」（与 Obsidian 默认行为一致），故采用 GFM 扩展。
  // 仅影响渲染，不改动 .md 数据本身；空行分段、列表、标题语义不受影响。
  const md = new MarkdownIt({ html: false, breaks: true, linkify: true });

  // 图片：仅替换相对资产 src，随后回退默认渲染规则（保留转义/协议校验）
  const defaultImageRule: RendererRule = md.renderer.rules.image!;
  const imageRule: RendererRule = (tokens, idx, options, env, self) => {
    const token = tokens[idx];
    const src = token.attrGet("src");
    if (typeof src === "string") {
      const rewritten = rewriteAssetSrc(src, imageBase, user);
      if (rewritten) token.attrSet("src", rewritten);
    }
    // alt 尺寸约定（![w=300](...) / ![w=50%](...)）：原始 alt 在 token.content；
    // 默认 render_image 会用 children 文本强制回填 alt，故命中后自行设好
    // alt 并直接 renderToken 绕开回填（默认规则末步本就是 renderToken）
    const sized = parseImageSizeAlt(token.content);
    if (sized) {
      token.attrSet("style", sized.style);
      token.attrSet("alt", sized.alt);
      return self.renderToken(tokens, idx, options);
    }
    return defaultImageRule(tokens, idx, options, env, self);
  };
  md.renderer.rules.image = imageRule;

  // 链接统一新标签页打开
  const defaultLinkOpen = md.renderer.rules.link_open;
  const linkOpenRule: RendererRule = (tokens, idx, options, env, self) => {
    tokens[idx].attrSet("target", "_blank");
    tokens[idx].attrSet("rel", "noopener noreferrer");
    return defaultLinkOpen
      ? defaultLinkOpen(tokens, idx, options, env, self)
      : self.renderToken(tokens, idx, options);
  };
  md.renderer.rules.link_open = linkOpenRule;

  instances.set(key, md);
  return md;
}

/** 渲染 Markdown 为 HTML 字符串（参数缺省时与备忘预览的历史行为一致） */
export function renderMarkdown(
  source: string,
  opts: MarkdownRenderOptions = {},
): string {
  const imageBase = opts.imageBase === undefined ? DEFAULT_IMAGE_BASE : opts.imageBase;
  return getInstance(imageBase, opts.user ?? "").render(source ?? "");
}