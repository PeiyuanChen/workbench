<script setup lang="ts">
import { onMounted, watch } from "vue";
import { useTimelineStore } from "../stores/timeline";
import { useUiStore } from "../stores/ui";

const tl = useTimelineStore();
const ui = useUiStore();

onMounted(() => {
  if (!tl.loading) tl.load(ui.user);
});
watch(() => ui.user, () => tl.load(ui.user));

function shift(delta: number) {
  tl.shift(delta);
  tl.load(ui.user);
}
function pad(n: number) {
  return String(n).padStart(2, "0");
}
</script>

<template>
  <div class="tl-bar">
    <div class="range">
      <button class="on">月</button>
      <button disabled title="M3 起支持更大范围">季</button>
      <button disabled>半年</button>
      <button disabled>年</button>
      <button disabled>自定义…</button>
    </div>
    <span v-if="tl.data.exists" class="ai-badge">✨ 由 LLM 基于待办/日历/备忘生成 · 可重新生成（M3）</span>
  </div>

  <div class="tl-month">
    <span class="big">{{ tl.year }} / {{ pad(tl.month) }}</span>
    <span class="tl-nav" @click="shift(-1)">‹ 上一月</span>
    <span class="tl-nav" style="margin-left: 12px" @click="shift(1)">下一月 ›</span>
  </div>

  <div v-if="tl.error" class="empty" style="margin-top: 14px">加载失败：{{ tl.error }}</div>
  <div v-else-if="tl.data.exists" class="tl-body">{{ tl.data.body }}</div>
  <div v-else class="tl-empty">
    <div style="font-size: 24px">🕘</div>
    <p style="margin-top: 8px">{{ tl.data.message || "该月时间线尚未生成" }}</p>
    <p style="margin-top: 6px; font-size: 12px">M3 起：点"✨ 生成"由 LLM 汇总该月待办/事件/备忘，落盘为 timeline md。</p>
  </div>
</template>
