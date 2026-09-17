import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { delJson, getJson, patchJson, postJson } from "../api/client";
import type { CalendarItem, EventCreate, EventDetail, EventPatch } from "../types";

interface EventsResp {
  month: string;
  items: CalendarItem[];
}

interface DeleteResp {
  deleted: string[];
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

  /** 编辑表单数据源：GET /api/events/{uid}（含 dtend/description/alarms） */
  async function fetchOne(uid: string, user: string): Promise<EventDetail> {
    return getJson<EventDetail>(`events/${encodeURIComponent(uid)}`, { user });
  }

  // 写 action：成功后一律重拉当前 monthKey 聚合——月聚合是现场计算的视图
  // （视图 ≠ 数据），跨月编辑/删除也能得到正确的当月结果；失败抛给调用方。

  async function create(payload: EventCreate, user: string): Promise<EventDetail> {
    const e = await postJson<EventDetail>("events", payload, { user });
    await load(user);
    return e;
  }

  async function patch(uid: string, payload: EventPatch, user: string): Promise<EventDetail> {
    const e = await patchJson<EventDetail>(`events/${encodeURIComponent(uid)}`, payload, { user });
    await load(user);
    return e;
  }

  async function remove(uid: string, user: string): Promise<string[]> {
    const data = await delJson<DeleteResp>(`events/${encodeURIComponent(uid)}`, { user });
    await load(user);
    return data.deleted;
  }

  return { year, month, monthKey, items, loading, error, byDay, load, shift, fetchOne, create, patch, remove };
});
