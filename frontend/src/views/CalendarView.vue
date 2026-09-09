<script setup lang="ts">
import { computed, onMounted, watch } from "vue";
import { useEventsStore } from "../stores/events";
import { useUiStore } from "../stores/ui";
import type { CalendarItem } from "../types";

const ev = useEventsStore();
const ui = useUiStore();

onMounted(() => {
  if (!ev.items.length && !ev.loading) ev.load(ui.user);
});
watch(() => ui.user, () => ev.load(ui.user));

function pad(n: number) {
  return String(n).padStart(2, "0");
}
function iso(y: number, m: number, d: number) {
  return `${y}-${pad(m)}-${pad(d)}`;
}

// 生成 6×7 月历格子：前置空白 + 当月日期 + 后置补齐
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
</script>

<template>
  <div v-if="ev.error" class="empty">加载失败：{{ ev.error }}</div>
  <div v-else class="cal">
    <div class="cal-head">
      <button @click="prev">‹</button>
      <span>{{ ev.year }} 年 {{ ev.month }} 月</span>
      <button @click="next">›</button>
    </div>
    <div class="cal-grid">
      <div v-for="d in ['日', '一', '二', '三', '四', '五', '六']" :key="d" class="dow">{{ d }}</div>
      <template v-for="(c, i) in grid" :key="i">
        <div v-if="c" class="day" :class="{ today: c.date === todayIso }">
          <span class="n">{{ c.n }}</span>
          <template v-for="it in itemsOn(c.date)" :key="it.uid + it.type">
            <span v-if="it.type === 'due'" class="deadline">⚑ {{ it.summary }}</span>
            <span v-else-if="it.type === 'block' && isMultiday(it)" class="ev multiday">▣ {{ it.summary }}</span>
            <span v-else-if="it.type === 'block'" class="ev block">▸ {{ label(it) }}</span>
            <span v-else class="ev green">● {{ label(it) }}</span>
          </template>
        </div>
        <div v-else class="day" style="border-color: transparent"></div>
      </template>
    </div>
  </div>
  <p style="font-size: 11px; color: var(--muted); margin-top: 8px">
    图例：<b>▸ 色块</b>=执行时间块（DTSTART+DURATION，可跨小时/多天）　<b>⚑ 红旗</b>=截止日（DUE，不占时间）　●=普通事件
  </p>
</template>
