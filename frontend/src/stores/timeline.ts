import { defineStore } from "pinia";
import { ref } from "vue";
import { getJson } from "../api/client";
import type { TimelineResp } from "../types";

export const useTimelineStore = defineStore("timeline", () => {
  const year = ref(2026);
  const month = ref(3); // 样例数据从 2026-03 起步
  const data = ref<TimelineResp>({ exists: false });
  const loading = ref(false);
  const error = ref("");

  async function load(user: string) {
    loading.value = true;
    error.value = "";
    try {
      data.value = await getJson<TimelineResp>(`timeline/${year.value}/${month.value}`, { user });
    } catch (e) {
      error.value = String(e);
      data.value = { exists: false };
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

  return { year, month, data, loading, error, load, shift };
});
