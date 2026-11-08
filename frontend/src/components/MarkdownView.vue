<script setup lang="ts">
// Markdown 只读渲染组件（备忘正文 / 时间线复用）。
//
// 安全：markdown-it 配置 html:false —— 原始 HTML 一律转义为文本，
// href/src 经其 validateLink 过滤 javascript:/vbscript: 等协议，
// 故 v-html 安全，无需 DOMPurify。
// 红线：将来若打开 html:true，必须同时引入 HTML 消毒（DOMPurify）。
import { computed } from "vue";
import MarkdownIt, { type RendererRule } from "markdown-it";

const props = withDefaults(
  defineProps<{
    source: string;
    /** 数据目录参数（me/example…），拼到图片请求 query 上 */
    user?: string;
    /** 相对 assets/ 图片的 HTTP 前缀；null = 不改写（时间线 M3 前无图片） */
    imageBase?: string | null;
  }>(),
  { user: "", imageBase: "/api/memos/assets" },
);

const md = new MarkdownIt({ html: false, breaks: false, linkify: true });

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
function rewriteAssetSrc(src: string): string | null {
  if (props.imageBase === null) return null;
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
  const encoded = parts.map(encodeURIComponent).join("/");
  const qs = props.user ? `?user=${encodeURIComponent(props.user)}` : "";
  return `${props.imageBase}/${encoded}${qs}`;
}

// 图片：仅替换相对资产 src，随后回退默认渲染规则（保留转义/协议校验）
const defaultImageRule: RendererRule = md.renderer.rules.image!;
const imageRule: RendererRule = (tokens, idx, options, env, self) => {
  const token = tokens[idx];
  const src = token.attrGet("src");
  if (typeof src === "string") {
    const rewritten = rewriteAssetSrc(src);
    if (rewritten) token.attrSet("src", rewritten);
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

const html = computed(() => md.render(props.source ?? ""));
</script>

<template>
  <div class="md-body" v-html="html"></div>
</template>
