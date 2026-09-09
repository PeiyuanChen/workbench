import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { getJson } from "../api/client";
import type { Todo } from "../types";

interface TodosResp {
  count: number;
  items: Todo[];
}

export const useTodosStore = defineStore("todos", () => {
  const items = ref<Todo[]>([]);
  const loading = ref(false);
  const error = ref("");

  async function load(user: string) {
    loading.value = true;
    error.value = "";
    try {
      const resp = await getJson<TodosResp>("todos", { user });
      items.value = resp.items;
    } catch (e) {
      error.value = String(e);
      items.value = [];
    } finally {
      loading.value = false;
    }
  }

  // 四象限视图：按象限分桶（同一批数据的现场计算视图）
  const byQuadrant = computed(() => {
    const buckets: Record<string, Todo[]> = { q1: [], q2: [], q3: [], q4: [] };
    for (const t of items.value) buckets[t.quadrant]?.push(t);
    return buckets;
  });

  // 待办视图：未排期·最近要做 / 已排期·近期
  const unscheduled = computed(() => items.value.filter((t) => t.has_time === "unscheduled"));
  const scheduled = computed(() =>
    items.value.filter((t) => t.has_time !== "unscheduled").sort((a, b) => {
      const ka = a.due || a.dtstart || "";
      const kb = b.due || b.dtstart || "";
      return ka.localeCompare(kb);
    }),
  );

  return { items, loading, error, load, byQuadrant, unscheduled, scheduled };
});
