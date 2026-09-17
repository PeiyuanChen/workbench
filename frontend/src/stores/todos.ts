import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { delJson, getJson, patchJson, postJson } from "../api/client";
import type { Todo, TodoCreate, TodoPatch } from "../types";

interface TodosResp {
  count: number;
  items: Todo[];
}

interface DeleteResp {
  deleted: string[];
}

type StatusAction = "complete" | "reopen" | "abandon";

function enc(uid: string): string {
  return encodeURIComponent(uid);
}

export const useTodosStore = defineStore("todos", () => {
  const items = ref<Todo[]>([]); // 主列表（scope=active 顶层树；完成/放弃默认消失）
  const archived = ref<Todo[]>([]); // 归档区（scope=archived：完成 + 放弃顶层）
  const archivedLoaded = ref(false);
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

  /** 归档区数据源（决策 A：scope=archived，含放弃项） */
  async function loadArchived(user: string) {
    const resp = await getJson<TodosResp>("todos", { user, scope: "archived" });
    archived.value = resp.items;
    archivedLoaded.value = true;
  }

  /** 编辑面板数据源：GET /api/todos/{uid}（树节点，含 children） */
  async function fetchOne(uid: string, user: string): Promise<Todo> {
    return getJson<Todo>(`todos/${enc(uid)}`, { user });
  }

  // 所有写 action：await 服务端响应后全量重拉（与 events.ts 范式一致）。
  // 不做乐观更新（M2 正确性优先）。
  // 归档区仅在已展开时同步重拉（archivedLoaded 守卫）。

  async function create(payload: TodoCreate, user: string): Promise<Todo> {
    const node = await postJson<Todo>("todos", payload, { user });
    await load(user);
    if (archivedLoaded.value) await loadArchived(user);
    return node;
  }

  async function patch(uid: string, payload: TodoPatch, user: string): Promise<Todo> {
    const node = await patchJson<Todo>(`todos/${enc(uid)}`, payload, { user });
    await load(user);
    if (archivedLoaded.value) await loadArchived(user);
    return node;
  }

  async function act(uid: string, action: StatusAction, user: string): Promise<Todo> {
    const node = await postJson<Todo>(`todos/${enc(uid)}/${action}`, {}, { user });
    await load(user);
    if (archivedLoaded.value) await loadArchived(user);
    return node;
  }

  const complete = (uid: string, user: string) => act(uid, "complete", user);
  const reopen = (uid: string, user: string) => act(uid, "reopen", user);
  const abandon = (uid: string, user: string) => act(uid, "abandon", user);

  /** 物理删除（决策 C：服务端级联删子任务）→ 返回被删 uid 数组 */
  async function remove(uid: string, user: string): Promise<string[]> {
    const data = await delJson<DeleteResp>(`todos/${enc(uid)}`, { user });
    await load(user);
    if (archivedLoaded.value) await loadArchived(user);
    return data.deleted;
  }

  // 四象限视图：按象限分桶，桶内按 created 倒序（新建在前）
  const byQuadrant = computed(() => {
    const buckets: Record<string, Todo[]> = { q1: [], q2: [], q3: [], q4: [] };
    for (const t of items.value) buckets[t.quadrant]?.push(t);
    for (const key of Object.keys(buckets)) {
      buckets[key].sort((a, b) => (b.created ?? "").localeCompare(a.created ?? ""));
    }
    return buckets;
  });

  // 待办视图：未排期按 created 倒序（新建在前）；已排期按 due/dtstart 升序
  const unscheduled = computed(() =>
    items.value
      .filter((t) => t.has_time === "unscheduled")
      .sort((a, b) => (b.created ?? "").localeCompare(a.created ?? "")),
  );
  const scheduled = computed(() =>
    items.value.filter((t) => t.has_time !== "unscheduled").sort((a, b) => {
      const ka = a.due || a.dtstart || "";
      const kb = b.due || b.dtstart || "";
      return ka.localeCompare(kb);
    }),
  );

  return {
    items, archived, archivedLoaded, loading, error,
    load, loadArchived, fetchOne,
    create, patch, act, complete, reopen, abandon, remove,
    byQuadrant, unscheduled, scheduled,
  };
});
