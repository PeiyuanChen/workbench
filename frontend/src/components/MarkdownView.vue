<script setup lang="ts">
// Markdown 只读渲染组件（备忘正文 / 笔记预览 / 时间线复用）。
// 渲染内核与资产 URL 改写集中在 lib/markdown（HTML 导出共用同一套规则，
// 保证「预览所见 = 导出所得」），本组件只做 props → HTML 的薄壳。
import { computed } from "vue";
import { renderMarkdown } from "../lib/markdown";

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

const html = computed(() =>
  renderMarkdown(props.source ?? "", { user: props.user, imageBase: props.imageBase }),
);
</script>

<template>
  <div class="md-body" v-html="html"></div>
</template>
