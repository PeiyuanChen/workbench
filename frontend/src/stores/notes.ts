import { defineStore } from "pinia";
import { ref } from "vue";
import { getJson } from "../api/client";
import type { Note } from "../types";

interface NotesResp {
  count: number;
  items: Note[];
}

export const useNotesStore = defineStore("notes", () => {
  const items = ref<Note[]>([]);
  const current = ref<Note | null>(null); // 详情（含 content）
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

  return { items, current, loading, error, load, open, close };
});
