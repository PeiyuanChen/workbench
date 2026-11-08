import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { delJson, getJson, postForm, postJson, putJson } from "../api/client";
import { buildFolderTree, type FolderNode } from "../lib/folders";
import type { AssetUpload, Note, NoteCreate, NoteFolder, NoteUpdate, NotesResp } from "../types";

// 笔记 store（#5）：与 memos store 同构，额外持有扁平 folders 与文件夹三操作。
// 文件夹路径含斜杠与中文，统一走 query/请求体，不进 URL path（后端路由注释约定）。
export const useNotesStore = defineStore("notes", () => {
  const items = ref<Note[]>([]);
  const folders = ref<NoteFolder[]>([]);
  const current = ref<Note | null>(null); // 详情（含 content、folder），编辑态数据源
  const loading = ref(false);
  const error = ref("");

  /** 视图层直接可用的文件夹树（后端只给扁平列表） */
  const folderTree = computed<FolderNode[]>(() => buildFolderTree(folders.value));

  async function load(user: string) {
    loading.value = true;
    error.value = "";
    try {
      const resp = await getJson<NotesResp>("notes", { user });
      items.value = resp.items;
      folders.value = resp.folders;
    } catch (e) {
      error.value = String(e);
      items.value = [];
      folders.value = [];
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

  /** POST /api/notes：建笔记（id/文件名服务端生成），写后重拉列表 */
  async function create(payload: NoteCreate, user: string): Promise<Note> {
    const note = await postJson<Note>("notes", payload, { user });
    await load(user);
    return note;
  }

  /** PUT /api/notes/{id}：全文更新；payload 含 folder 时服务端移动并改写资产链接。
   *  文件夹列表只可能被文件夹端点改变（各自写后已 load 同步），这里不额外请求。 */
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

  // ------------------------------------------------------------- 文件夹三操作

  /** POST /api/notes/folders：支持多层嵌套（中间层一并创建） */
  async function createFolder(path: string, user: string): Promise<NoteFolder> {
    const folder = await postJson<NoteFolder>("notes/folders", { path }, { user });
    await load(user);
    return folder;
  }

  /** PUT /api/notes/folders：同父目录重命名（跨父移动后端 422，中文 detail 原样抛出） */
  async function renameFolder(path: string, newPath: string, user: string): Promise<NoteFolder> {
    const folder = await putJson<NoteFolder>("notes/folders", { path, new_path: newPath }, { user });
    await load(user);
    return folder;
  }

  /** DELETE /api/notes/folders：仅空文件夹可删，非空后端 422 中文提示 */
  async function deleteFolder(path: string, user: string) {
    await delJson<{ path: string }>("notes/folders", { path, user });
    await load(user);
  }

  /** POST /api/notes/assets：multipart 带 folder 字段，返回的 path 已按深度算好相对链接 */
  async function uploadAsset(file: File, folder: string, user: string): Promise<AssetUpload> {
    const form = new FormData();
    form.append("file", file);
    form.append("folder", folder);
    return postForm<AssetUpload>("notes/assets", form, { user });
  }

  return {
    items,
    folders,
    current,
    loading,
    error,
    folderTree,
    load,
    open,
    close,
    create,
    update,
    remove,
    createFolder,
    renameFolder,
    deleteFolder,
    uploadAsset,
  };
});
