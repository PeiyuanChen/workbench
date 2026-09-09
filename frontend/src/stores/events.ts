import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { getJson } from "../api/client";
import type { CalendarItem } from "../types";

interface EventsResp {
  month: string;
  items: CalendarItem[];
}

export const useEventsStore = defineStore("events", () => {
  const now = new Date();
  const year = ref(now.getFullYear());
  const month = ref(now.getMonth() + 1);
  const items = ref<CalendarItem[]>([]);
  const loading = ref(false);
  const error = ref("");

  const monthKey = computed(() => `${year.value}-${String(month.value).padStart(2, "0")}`);

  // 按日期分桶：days_in_month 中每一天都挂一份（跨天条目逐日出现，同原型 ▣ 横跨画法）
  const byDay = computed(() => {
    const map = new Map<string, CalendarItem[]>();
    for (const it of items.value) {
      for (const d of it.days_in_month) {
        const list = map.get(d) ?? [];
        list.push(it);
        map.set(d, list);
      }
    }
    return map;
  });

  async function load(user: string) {
    loading.value = true;
    error.value = "";
    try {
      const resp = await getJson<EventsResp>("events", { month: monthKey.value, user });
      items.value = resp.items;
    } catch (e) {
      error.value = String(e);
      items.value = [];
    } finally {
      loading.value = false;
    }
  }

  function shift(delta: number) {
    let m = month.value + delta;
    let y = year.value;
    if (m < 1) {
      m = 12;
      y -= 1;
    } else if (m > 12) {
      m = 1;
      y += 1;
    }
    year.value = y;
    month.value = m;
  }

  return { year, month, monthKey, items, loading, error, byDay, load, shift };
});
