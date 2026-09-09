<script setup lang="ts">
import { onMounted, watch } from "vue";
import { useNotesStore } from "../stores/notes";
import { useUiStore } from "../stores/ui";

const notes = useNotesStore();
const ui = useUiStore();

onMounted(() => {
  if (!notes.items.length && !notes.loading) notes.load(ui.user);
});
watch(() => ui.user, () => {
  notes.close();
  notes.load(ui.user);
});

function open(id: string) {
  notes.open(id, ui.user).catch(() => {
    /* 详情加载失败保持列表 */
  });
}
</script>

<template>
  <!-- 详情 -->
  <div v-if="notes.current" class="note-detail">
    <span class="back" @click="notes.close()">‹ 返回备忘列表</span>
    <h2 style="font-size: 18px">{{ notes.current.title }}</h2>
    <div class="meta" style="margin-top: 8px; font-size: 11px; color: var(--slate)">
      {{ notes.current.date }}
      <template v-for="t in notes.current.tags" :key="t"> · #{{ t }}</template>
    </div>
    <div class="content">{{ notes.current.content }}</div>
  </div>

  <!-- 列表 -->
  <template v-else>
    <div v-if="notes.error" class="empty">加载失败：{{ notes.error }}</div>
    <div v-else-if="!notes.items.length" class="empty">暂无备忘（M2 起可新增）</div>
    <div v-else class="notes">
      <div v-for="n in notes.items" :key="n.id" class="note" @click="open(n.id)">
        <h4>{{ n.title }}</h4>
        <p>{{ n.excerpt }}</p>
        <div class="meta">
          {{ n.date }}
          <template v-for="t in n.tags" :key="t"> · #{{ t }}</template>
        </div>
      </div>
    </div>
  </template>
</template>
