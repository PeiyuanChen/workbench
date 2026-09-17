import { defineStore } from "pinia";
import { ref } from "vue";
import { delJson, getJson, postJson, putJson } from "../api/client";
import type { Note, NoteCreate, NoteUpdate } from "../types";

interface NotesResp {
  count: number;
  items: Note[];
}

export const useNotesStore = defineStore("notes", () => {
  const items = ref<Note[]>([]);
  const current = ref<Note | null>(null); // 详情（含 content），编辑态数据源
  const loading = ref(false);
  const error = ref("");

  async function load(user: string) {
    loading.value = true;
    error.value = "";
    try {
      const resp = await getJson<NotesResp>("notes", { user });
      items.value = resp.items;
    } catch (e) {
      error.value = String(e);
      items.value = [];
    } finally {
      loading.value = false;
    }
  }

  async function open(id: string, user: string) {
    current.value = await getJson<Note>(`notes/${encodeURIComponent(id)}`, { user });
  }

  function close() {
    current.value = null;
  }

  /** POST /api/notes：建笔记（id/文件名服务端生成），写后重拉列表、不跳详情 */
  async function create(payload: NoteCreate, user: string): Promise<Note> {
    const note = await postJson<Note>("notes", payload, { user });
    await load(user);
    return note;
  }

  /** PUT /api/notes/{id}：全文更新（标题变更时服务端重命名文件，id 不变） */
  async function update(id: string, payload: NoteUpdate, user: string): Promise<Note> {
    const note = await putJson<Note>(`notes/${encodeURIComponent(id)}`, payload, { user });
    const i = items.value.findIndex((n) => n.id === id);
    if (i >= 0) items.value[i] = note;
    if (current.value?.id === id) current.value = note;
    return note;
  }

  /** DELETE /api/notes/{id}：物理删除（服务端删除前已备份到 notes/.backup/） */
  async function remove(id: string, user: string) {
    await delJson<{ id: string }>(`notes/${encodeURIComponent(id)}`, { user });
    items.value = items.value.filter((n) => n.id !== id);
    if (current.value?.id === id) current.value = null;
  }

  return { items, current, loading, error, load, open, close, create, update, remove };
});
