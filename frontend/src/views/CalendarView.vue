<script setup lang="ts">
// 日历月视图（M2）：事件新建/编辑/删除入口在日历页（决策 #8）。
// - 日期格空白点击 → 新建事件（预填该日，默认全天）；「＋事件」按钮同；
// - ● 普通事件点击 → EventForm 编辑；
// - ⚑ 截止 / ▸▣ 执行块点击 → 打开对应待办的编辑面板（它们本质是待办的视图投影）；
// - 日历页无快速记录框（frontend/CLAUDE.md 界面基准）。
import { computed, onMounted, ref, watch } from "vue";
import EventForm from "../components/EventForm.vue";
import TodoEditPanel from "../components/TodoEditPanel.vue";
import { useEventsStore } from "../stores/events";
import { useUiStore } from "../stores/ui";
import type { CalendarItem } from "../types";

const ev = useEventsStore();
const ui = useUiStore();

// 弹层状态：新建（预填日期）/ 编辑事件 / 编辑待办（⚑▸▣ 点击）
const creatingDate = ref<string | null>(null);
const editingEventUid = ref<string | null>(null);
const editingTodoUid = ref<string | null>(null);

// Bug B 修复：去掉 `!ev.items.length` 守卫——Pinia store 单例让旧快照跨路由存活，
// "有数据"不等于"数据新鲜"。聚合 GET 很轻（本地文件读），每次挂载无条件重拉。
onMounted(() => {
  ev.load(ui.user);
});
watch(() => ui.user, () => ev.load(ui.user));

function pad(n: number) {
  return String(n).padStart(2, "0");
}
function iso(y: number, m: number, d: number) {
  return `${y}-${pad(m)}-${pad(d)}`;
}

// 生成月历格子：前置空白 + 当月日期 + 后置补齐到整周
const grid = computed(() => {
  const y = ev.year;
  const m = ev.month;
  const firstDow = new Date(y, m - 1, 1).getDay(); // 0=周日
  const days = new Date(y, m, 0).getDate();
  const cells: ({ date: string; n: number } | null)[] = [];
  for (let i = 0; i < firstDow; i++) cells.push(null);
  for (let d = 1; d <= days; d++) cells.push({ date: iso(y, m, d), n: d });
  while (cells.length % 7) cells.push(null);
  return cells;
});

const todayIso = iso(new Date().getFullYear(), new Date().getMonth() + 1, new Date().getDate());

function itemsOn(date: string): CalendarItem[] {
  return ev.byDay.get(date) ?? [];
}
function label(it: CalendarItem): string {
  const time = it.start_time && it.end_time ? ` ${it.start_time}–${it.end_time}` : it.start_time ? ` ${it.start_time}` : "";
  return `${it.summary}${time}`;
}
function isMultiday(it: CalendarItem): boolean {
  return it.start_date !== it.end_date;
}
function prev() {
  ev.shift(-1);
  ev.load(ui.user);
}
function next() {
  ev.shift(1);
  ev.load(ui.user);
}

/** 日期格空白点击：新建事件（预填该日） */
function onDayClick(cell: { date: string }) {
  creatingDate.value = cell.date;
}

/** 「＋事件」：预填今天（在当前月内）或当月 1 日 */
function onAddEvent() {
  creatingDate.value = todayIso.startsWith(ev.monthKey) ? todayIso : iso(ev.year, ev.month, 1);
}

/** 条目点击：● 事件 → 事件表单；⚑ 截止 / ▸▣ 执行块 → 待办编辑面板 */
function onItemClick(it: CalendarItem) {
  if (it.type === "event") editingEventUid.value = it.uid;
  else editingTodoUid.value = it.uid;
}
</script>

<template>
  <div v-if="ev.error" class="empty">加载失败：{{ ev.error }}</div>
  <div v-else class="cal">
    <div class="cal-head">
      <button @click="prev">‹</button>
      <span>{{ ev.year }} 年 {{ ev.month }} 月</span>
      <span class="cal-head-right">
        <button class="cal-add" title="新建事件（也可以直接点某天）" @click="onAddEvent">＋事件</button>
        <button @click="next">›</button>
      </span>
    </div>
    <div class="cal-grid">
      <div v-for="d in ['日', '一', '二', '三', '四', '五', '六']" :key="d" class="dow">{{ d }}</div>
      <template v-for="(c, i) in grid" :key="i">
        <div
          v-if="c"
          class="day clickable"
          :class="{ today: c.date === todayIso }"
          title="点击新建该日事件"
          @click="onDayClick(c)"
        >
          <span class="n">{{ c.n }}</span>
          <template v-for="it in itemsOn(c.date)" :key="it.uid + it.type">
            <span
              v-if="it.type === 'due'"
              class="deadline item-click"
              title="点击编辑对应待办"
              @click.stop="onItemClick(it)"
            >⚑ {{ it.summary }}</span>
            <span
              v-else-if="it.type === 'block' && isMultiday(it)"
              class="ev multiday item-click"
              title="点击编辑对应待办"
              @click.stop="onItemClick(it)"
            >▣ {{ it.summary }}</span>
            <span
              v-else-if="it.type === 'block'"
              class="ev block item-click"
              title="点击编辑对应待办"
              @click.stop="onItemClick(it)"
            >▸ {{ label(it) }}</span>
            <span
              v-else
              class="ev green item-click"
              title="点击编辑事件"
              @click.stop="onItemClick(it)"
            >● {{ label(it) }}</span>
          </template>
        </div>
        <div v-else class="day" style="border-color: transparent"></div>
      </template>
    </div>
  </div>
  <p style="font-size: 11px; color: var(--muted); margin-top: 8px">
    图例：<b>▸ 色块</b>=执行时间块（DTSTART+DURATION，可跨小时/多天）　<b>⚑ 红旗</b>=截止日（DUE，不占时间）　●=普通事件
    　·　点某天空白新建事件；点 ⚑/▸/▣ 编辑对应待办
  </p>

  <!-- 弹层：新建（预填日期）/ 编辑事件 / 编辑待办 -->
  <EventForm v-if="creatingDate" :initial-date="creatingDate" @close="creatingDate = null" />
  <EventForm v-else-if="editingEventUid" :uid="editingEventUid" @close="editingEventUid = null" />
  <TodoEditPanel v-if="editingTodoUid" :uid="editingTodoUid"
    @close="editingTodoUid = null"
    @changed="ev.load(ui.user)" />
</template>
