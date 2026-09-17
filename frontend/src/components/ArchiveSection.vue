<script setup lang="ts">
// "已完成"归档区（SPEC-M2 决策 #9）：默认隐藏完成/放弃项，可展开查看；
// COMPLETED 删除线绿勾 / CANCELLED 灰化 +"已放弃"徽标（视觉区分）；均可恢复（reopen）。
// 数据源 = GET /api/todos?scope=archived（决策 A），展开时才拉取。
import { ref } from "vue";
import { useTodosStore } from "../stores/todos";
import { useUiStore } from "../stores/ui";

const emit = defineEmits<{ edit: [uid: string] }>();

const todos = useTodosStore();
const ui = useUiStore();
const open = ref(false);
const busyUid = ref("");
const error = ref("");

async function toggle() {
  open.value = !open.value;
  if (open.value && !todos.archivedLoaded) await refresh();
}

async function refresh() {
  error.value = "";
  try {
    await todos.loadArchived(ui.user);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

async function restore(uid: string) {
  if (busyUid.value) return;
  busyUid.value = uid;
  error.value = "";
  try {
    await todos.reopen(uid, ui.user);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    busyUid.value = "";
  }
}
</script>

<template>
  <div class="archive">
    <div class="archive-head" @click="toggle">
      {{ open ? "▾" : "▸" }} 已完成 / 已放弃<template v-if="todos.archivedLoaded">（{{ todos.archived.length }}）</template>
    </div>
    <div v-if="open" class="archive-body">
      <div v-if="error" class="qa-error">⚠ {{ error }}</div>
      <div v-if="!todos.archived.length && !error" class="archive-empty">暂无已完成或已放弃的待办</div>
      <div
        v-for="t in todos.archived"
        :key="t.uid"
        class="row archive-row"
        :class="{ cancelled: t.status === 'CANCELLED' }"
      >
        <div class="line">
          <div class="left">
            <span class="chk done" :class="{ gray: t.status === 'CANCELLED' }"></span>
            <span class="archive-sum" title="点击打开编辑面板" @click="emit('edit', t.uid)">{{ t.summary }}</span>
            <span v-if="t.status === 'CANCELLED'" class="tag t-slate">已放弃</span>
            <span v-else class="tag t-green">已完成</span>
          </div>
          <button type="button" class="link-btn" :disabled="busyUid === t.uid" @click="restore(t.uid)">
            {{ busyUid === t.uid ? "…" : "恢复" }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
