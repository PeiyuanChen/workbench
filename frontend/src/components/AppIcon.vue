<script setup lang="ts">
// 导航线性图标（16px，currentColor 描边）：替代 emoji，保证跨平台渲染一致。
// 只用在左侧导航；风格统一为 1.4 描边、圆头、无填充。
defineProps<{
  name: "quadrant" | "todos" | "calendar" | "timeline" | "memos" | "notes";
}>();
</script>

<template>
  <svg
    viewBox="0 0 16 16"
    width="16"
    height="16"
    fill="none"
    stroke="currentColor"
    stroke-width="1.4"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <!-- 四象限：2×2 矩阵 -->
    <template v-if="name === 'quadrant'">
      <rect x="1.5" y="1.5" width="5.4" height="5.4" />
      <rect x="9.1" y="1.5" width="5.4" height="5.4" />
      <rect x="1.5" y="9.1" width="5.4" height="5.4" />
      <rect x="9.1" y="9.1" width="5.4" height="5.4" />
    </template>
    <!-- 待办：勾选清单 -->
    <template v-else-if="name === 'todos'">
      <circle cx="3.1" cy="3.6" r="1.5" />
      <path d="M2.45 3.6l.45.45.95-1.05" />
      <path d="M6.6 3.6h7" />
      <circle cx="3.1" cy="8" r="1.5" />
      <path d="M2.45 8l.45.45.95-1.05" />
      <path d="M6.6 8h7" />
      <circle cx="3.1" cy="12.4" r="1.5" />
      <path d="M6.6 12.4h7" />
    </template>
    <!-- 日历：月历本 -->
    <template v-else-if="name === 'calendar'">
      <rect x="1.8" y="3.2" width="12.4" height="11.2" rx="1" />
      <path d="M1.8 6.6h12.4M5.2 1.8v2.6M10.8 1.8v2.6" />
      <path d="M4.6 9.4h1.6M7.2 9.4h1.6M9.8 9.4h1.6M4.6 12h1.6M7.2 12h1.6" />
    </template>
    <!-- 时间线：节点轴 -->
    <template v-else-if="name === 'timeline'">
      <path d="M2 8h12" />
      <circle cx="4" cy="8" r="1.4" />
      <circle cx="8" cy="8" r="1.4" />
      <circle cx="12" cy="8" r="1.4" />
    </template>
    <!-- 备忘：折角文稿 -->
    <template v-else-if="name === 'memos'">
      <path d="M4 1.8h5.2L12.5 5v9.2H4z" />
      <path d="M9.2 1.8v3.2h3.3" />
      <path d="M6 8.4h4.2M6 10.8h4.2" />
    </template>
    <!-- 笔记：装订本 -->
    <template v-else>
      <path d="M3 2.2h8.6a1 1 0 011 1v10.6l-2.4-1.4-2.2 1.4-2.2-1.4L3.4 13.8V3.2a1 1 0 011-1z" />
      <path d="M8 2.6v10.8M5.2 5.6h1.6M5.2 8.2h1.6" />
    </template>
  </svg>
</template>
