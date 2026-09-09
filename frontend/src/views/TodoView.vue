<script setup lang="ts">
import { onMounted } from "vue";
import { useTodosStore } from "../stores/todos";
import { useUiStore } from "../stores/ui";
import { blockText, dueText } from "../lib/format";
import type { Todo } from "../types";

const todos = useTodosStore();
const ui = useUiStore();
onMounted(() => {
  if (!todos.items.length && !todos.loading) todos.load(ui.user);
});

function done(t: Todo) {
  return t.status === "COMPLETED";
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
    <!-- 未排期分区：不出现"收件箱"字样 -->
    <div class="section-title">📥 未排期 · 最近要做（先记下来，还没归类/定时间）</div>
    <div v-if="!todos.unscheduled.length" class="empty">没有未排期待办</div>
    <div v-for="t in todos.unscheduled" :key="t.uid" class="row">
      <div class="line">
        <div class="left">
          <div class="chk" :class="{ done: done(t) }" title="M2 起可勾选完成"></div>
          <div>
            <strong v-if="t.children_total">{{ t.summary }}</strong>
            <template v-else>{{ t.summary }}</template>
            <template v-if="t.children_total">（含 {{ t.children_total }} 个子任务）</template>
          </div>
        </div>
        <span class="tag" :class="t.important ? 't-blue' : 't-slate'">
          {{ t.important ? "重要" : "不重要" }}{{ t.urgent ? " · 紧急" : "" }}
        </span>
      </div>
      <!-- 子任务展开（未排期父任务同样展示） -->
      <div v-if="t.children_total" class="subtask">
        <div v-for="c in t.children" :key="c.uid" class="st" :class="{ done: done(c) }">
          <span class="chk" :class="{ done: done(c) }"></span> {{ c.summary }}
        </div>
      </div>
      <div v-if="t.progress != null" class="progress">
        <i :style="{ width: `${Math.round(t.progress * 100)}%` }"></i>
      </div>
    </div>

    <div class="section-title">📌 已排期 · 近期（含可展开的复杂事项/子任务）</div>
    <div v-if="!todos.scheduled.length" class="empty">没有已排期待办</div>
    <div v-for="t in todos.scheduled" :key="t.uid" class="row">
      <div class="line">
        <div class="left">
          <div class="chk" :class="{ done: done(t) }" title="M2 起可勾选完成"></div>
          <div>
            <strong v-if="t.children_total">{{ t.summary }}</strong>
            <template v-else>{{ t.summary }}</template>
            <template v-if="t.children_total">（含 {{ t.children_total }} 个子任务）</template>
          </div>
        </div>
        <span class="due" :class="{ overdue: t.overdue }">{{ timeText(t) || "—" }}</span>
      </div>

      <!-- 子任务展开（默认两级） -->
      <div v-if="t.children_total" class="subtask">
        <div v-for="c in t.children" :key="c.uid" class="st" :class="{ done: done(c) }">
          <span class="chk" :class="{ done: done(c) }"></span> {{ c.summary }}
          <span v-if="c.due" class="due" :class="{ overdue: c.overdue }">{{ dueText(c.due) }}</span>
        </div>
      </div>
      <div v-if="t.progress != null" class="progress">
        <i :style="{ width: `${Math.round(t.progress * 100)}%` }"></i>
      </div>
    </div>
  </div>
</template>
