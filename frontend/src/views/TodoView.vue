<script setup lang="ts">
// 待办视图（M2）：勾选真实可用（complete/reopen）、行点击开编辑面板、
// 底部"已完成"归档区（默认隐藏完成/放弃项——后端 scope=active 已滤）。
import { onMounted, ref } from "vue";
import ArchiveSection from "../components/ArchiveSection.vue";
import TodoEditPanel from "../components/TodoEditPanel.vue";
import { blockText, dueText } from "../lib/format";
import { useTodosStore } from "../stores/todos";
import { useUiStore } from "../stores/ui";
import type { Todo } from "../types";

const todos = useTodosStore();
const ui = useUiStore();

const editingUid = ref<string | null>(null);
const writeError = ref("");

onMounted(() => {
  if (!todos.items.length && !todos.loading) todos.load(ui.user);
});

const writeBusy = ref("");

function done(t: Todo) {
  return t.status === "COMPLETED";
}

/** 勾选：完成 ↔ 取消完成（响应 = 顶层节点，store 整体替换；子任务勾选联动父进度） */
async function toggleDone(t: Todo) {
  if (writeBusy.value) return;
  writeBusy.value = t.uid;
  writeError.value = "";
  try {
    if (t.status === "COMPLETED") await todos.reopen(t.uid, ui.user);
    else await todos.complete(t.uid, ui.user);
  } catch (e) {
    writeError.value = e instanceof Error ? e.message : String(e);
  } finally {
    writeBusy.value = "";
  }
}

function timeText(t: Todo): string {
  const parts: string[] = [];
  if (t.due) parts.push(dueText(t.due));
  if (t.dtstart && t.duration_minutes != null) {
    parts.push(blockText(t.dtstart, t.duration_minutes, t.all_day));
  }
  return parts.join(" · ");
}
</script>

<template>
  <div v-if="todos.error" class="empty">加载失败：{{ todos.error }}</div>
  <div v-else>
    <div v-if="writeError" class="qa-error" style="margin-bottom: 8px">⚠ {{ writeError }}</div>

    <!-- 已排期分区：近期 -->
    <div class="section-title">📌 已排期 · 近期（含可展开的复杂事项/子任务）</div>
    <div v-if="!todos.scheduled.length" class="empty">没有已排期待办</div>
    <div v-for="t in todos.scheduled" :key="t.uid" class="row clickable" @click="editingUid = t.uid">
      <div class="line">
        <div class="left">
          <div>
            <strong v-if="t.children_total">{{ t.summary }}</strong>
            <template v-else>{{ t.summary }}</template>
            <template v-if="t.children_total">（含 {{ t.children_total }} 个子任务）</template>
            <button type="button" class="complete-btn"
                    :class="{ 'is-done': done(t) }"
                    :disabled="writeBusy === t.uid"
                    @click.stop="toggleDone(t)">
              {{ done(t) ? '✓ 恢复' : '◎ 完成' }}
            </button>
          </div>
        </div>
        <span class="due" :class="{ overdue: t.overdue }">{{ timeText(t) || "—" }}</span>
      </div>

      <!-- 子任务展开（默认两级） -->
      <div v-if="t.children_total" class="subtask">
        <div v-for="c in t.children" :key="c.uid" class="st" :class="{ done: done(c), cancelled: c.status === 'CANCELLED' }">
          <span class="st-sum" @click.stop="editingUid = c.uid">{{ c.summary }}</span>
          <button type="button" class="complete-btn"
                  :class="{ 'is-done': done(c) }"
                  :disabled="writeBusy === c.uid"
                  @click.stop="toggleDone(c)">
            {{ done(c) ? '✓ 恢复' : '◎ 完成' }}
          </button>
          <span v-if="c.due" class="due" :class="{ overdue: c.overdue }">{{ dueText(c.due) }}</span>
        </div>
      </div>
      <div v-if="t.progress != null" class="progress">
        <i :style="{ width: `${Math.round(t.progress * 100)}%` }"></i>
      </div>
    </div>

    <!-- 未排期分区：不出现"收件箱"字样 -->
    <div class="section-title">📥 未排期 · 最近要做（先记下来，还没归类/定时间）</div>
    <div v-if="!todos.unscheduled.length" class="empty">没有未排期待办</div>
    <div v-for="t in todos.unscheduled" :key="t.uid" class="row clickable" @click="editingUid = t.uid">
      <div class="line">
        <div class="left">
          <div>
            <strong v-if="t.children_total">{{ t.summary }}</strong>
            <template v-else>{{ t.summary }}</template>
            <template v-if="t.children_total">（含 {{ t.children_total }} 个子任务）</template>
            <button type="button" class="complete-btn"
                    :class="{ 'is-done': done(t) }"
                    :disabled="writeBusy === t.uid"
                    @click.stop="toggleDone(t)">
              {{ done(t) ? '✓ 恢复' : '◎ 完成' }}
            </button>
          </div>
        </div>
        <span class="tag" :class="t.important ? 't-blue' : 't-slate'">
          {{ t.important ? "重要" : "不重要" }}{{ t.urgent ? " · 紧急" : "" }}
        </span>
      </div>
      <!-- 子任务展开（未排期父任务同样展示）；子任务是完整待办，可独立勾选/编辑 -->
      <div v-if="t.children_total" class="subtask">
        <div v-for="c in t.children" :key="c.uid" class="st" :class="{ done: done(c), cancelled: c.status === 'CANCELLED' }">
          <span class="st-sum" @click.stop="editingUid = c.uid">{{ c.summary }}</span>
          <button type="button" class="complete-btn"
                  :class="{ 'is-done': done(c) }"
                  :disabled="writeBusy === c.uid"
                  @click.stop="toggleDone(c)">
            {{ done(c) ? '✓ 恢复' : '◎ 完成' }}
          </button>
        </div>
      </div>
      <div v-if="t.progress != null" class="progress">
        <i :style="{ width: `${Math.round(t.progress * 100)}%` }"></i>
      </div>
    </div>

    <!-- 归档区：已完成/已放弃（含放弃项，视觉区分，可恢复） -->
    <ArchiveSection @edit="(uid) => (editingUid = uid)" />
  </div>

  <TodoEditPanel v-if="editingUid" :uid="editingUid" @close="editingUid = null" />
</template>
