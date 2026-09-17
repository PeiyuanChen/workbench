<script setup lang="ts">
// 四象限视图（M2）：卡片点击开编辑面板；子任务勾选真实可用。
// 象限 = important×urgent 现场计算的视图（与待办同一份数据，视图≠数据）。
import { onMounted, ref } from "vue";
import TodoEditPanel from "../components/TodoEditPanel.vue";
import { blockText, dueText } from "../lib/format";
import { useTodosStore } from "../stores/todos";
import { useUiStore } from "../stores/ui";
import type { Todo } from "../types";

const todos = useTodosStore();
const ui = useUiStore();

const editingUid = ref<string | null>(null);
const writeError = ref("");
const writeBusy = ref("");

onMounted(() => {
  if (!todos.items.length && !todos.loading) todos.load(ui.user);
});

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

// 四象限 = important×urgent 现场计算的视图（与待办同一份数据）
const cells = [
  { key: "q1", cls: "q1", tag: "t-red", title: "🔴 重要且紧急 · 立即做", hint: "优先级视图 · 同一份待办按重要/紧急归位" },
  { key: "q2", cls: "q2", tag: "t-blue", title: "🔵 重要不紧急 · 计划做", hint: "长期价值" },
  { key: "q3", cls: "q3", tag: "t-amber", title: "🟠 紧急不重要 · 快做/委托", hint: "占时间、价值低" },
  { key: "q4", cls: "q4", tag: "t-slate", title: "⚪ 不重要不紧急 · 有空再做", hint: "想法/以后再说" },
] as const;

function timeSpans(t: Todo): { cls: string; text: string }[] {
  const spans: { cls: string; text: string }[] = [];
  if (t.due) spans.push({ cls: t.overdue ? "due overdue" : "due", text: dueText(t.due) });
  if (t.dtstart && t.duration_minutes != null) {
    spans.push({ cls: "due", text: blockText(t.dtstart, t.duration_minutes, t.all_day) });
  }
  if (t.has_time === "unscheduled") spans.push({ cls: "nosched", text: "● 未排期" });
  return spans;
}
</script>

<template>
  <div v-if="todos.error" class="empty">加载失败：{{ todos.error }}</div>
  <div v-else class="quad-page">
    <div v-if="writeError" class="qa-error" style="margin-bottom: 8px">⚠ {{ writeError }}</div>
    <div class="quad">
      <div v-for="cell in cells" :key="cell.key" class="qcell" :class="cell.cls">
        <h3>{{ cell.title }}</h3>
        <div class="hint">{{ cell.hint }}</div>
        <div class="qcell-body">
          <div v-if="!todos.byQuadrant[cell.key].length" class="hint">（空）</div>
          <div
            v-for="t in todos.byQuadrant[cell.key]"
            :key="t.uid"
            class="todo-item clickable"
            title="点击编辑"
            @click="editingUid = t.uid"
          >
            <div class="t">
              {{ t.summary }}
              <span v-if="t.children_total" class="sub-count">
                ▸ 子任务 {{ t.children_done }}/{{ t.children_total }}
              </span>
              <button type="button" class="complete-btn"
                      :class="{ 'is-done': t.status === 'COMPLETED' }"
                      :disabled="writeBusy === t.uid"
                      @click.stop="toggleDone(t)">
                {{ t.status === 'COMPLETED' ? '✓ 恢复' : '◎ 完成' }}
              </button>
            </div>
            <span v-for="c in t.categories.slice(0, 2)" :key="c" class="tag" :class="cell.tag">{{ c }}</span>
            <span v-for="(s, i) in timeSpans(t)" :key="i" :class="s.cls" class="mr-1">{{ s.text }}</span>
            <!-- 子任务展开：可独立勾选（联动父进度） -->
            <div v-if="t.children_total" class="subtask">
              <div v-for="ch in t.children" :key="ch.uid" class="st" :class="{ cancelled: ch.status === 'CANCELLED' }">
                <span class="st-sum" title="点击编辑" @click.stop="editingUid = ch.uid">{{ ch.summary }}</span>
                <button type="button" class="complete-btn"
                        :class="{ 'is-done': ch.status === 'COMPLETED' }"
                        :disabled="writeBusy === ch.uid"
                        @click.stop="toggleDone(ch)">
                  {{ ch.status === 'COMPLETED' ? '✓ 恢复' : '◎ 完成' }}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <TodoEditPanel v-if="editingUid" :uid="editingUid" @close="editingUid = null" />
</template>
