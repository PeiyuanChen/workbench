import { defineStore } from "pinia";
import { ref } from "vue";
import { delJson, getJson, postForm, postJson, putJson } from "../api/client";
import type { AssetUpload, Memo, MemoCreate, MemoUpdate } from "../types";

interface MemosResp {
  count: number;
  items: Memo[];
}

export const useMemosStore = defineStore("memos", () => {
  const items = ref<Memo[]>([]);
  const current = ref<Memo | null>(null); // 详情（含 content），编辑态数据源
  const loading = ref(false);
  const error = ref("");

  async function load(user: string) {
    loading.value = true;
    error.value = "";
    try {
      const resp = await getJson<MemosResp>("memos", { user });
      items.value = resp.items;
    } catch (e) {
      error.value = String(e);
      items.value = [];
    } finally {
      loading.value = false;
    }
  }

  async function open(id: string, user: string) {
    current.value = await getJson<Memo>(`memos/${encodeURIComponent(id)}`, { user });
  }

  function close() {
    current.value = null;
  }

  /** POST /api/memos：建备忘（id/文件名服务端生成），写后重拉列表、不跳详情 */
  async function create(payload: MemoCreate, user: string): Promise<Memo> {
    const memo = await postJson<Memo>("memos", payload, { user });
    await load(user);
    return memo;
  }

  /** PUT /api/memos/{id}：全文更新（标题变更时服务端重命名文件，id 不变） */
  async function update(id: string, payload: MemoUpdate, user: string): Promise<Memo> {
    const memo = await putJson<Memo>(`memos/${encodeURIComponent(id)}`, payload, { user });
    const i = items.value.findIndex((m) => m.id === id);
    if (i >= 0) items.value[i] = memo;
    if (current.value?.id === id) current.value = memo;
    return memo;
  }

  /** POST /api/memos/assets：multipart 上传图片，返回服务端生成的资产信息 */
  async function uploadAsset(file: File, user: string): Promise<AssetUpload> {
    const form = new FormData();
    form.append("file", file);
    return postForm<AssetUpload>("memos/assets", form, { user });
  }

  /** DELETE /api/memos/{id}：物理删除（服务端删除前已备份到 memos/.backup/） */
  async function remove(id: string, user: string) {
    await delJson<{ id: string }>(`memos/${encodeURIComponent(id)}`, { user });
    items.value = items.value.filter((m) => m.id !== id);
    if (current.value?.id === id) current.value = null;
  }

  return { items, current, loading, error, load, open, close, create, update, uploadAsset, remove };
});
