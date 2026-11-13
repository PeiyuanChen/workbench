<script setup lang="ts">
// 笔记视图（#5）：左文件夹树 + 右列表/详情。
//
// 后端只给扁平 folders + 带 folder 字段的 items（ADR-0002：视图 ≠ 数据），
// 树与过滤都在本视图现算。文件夹 = 真实子目录：新建/同父重命名/空删除；
// 笔记移动 = 详情里改文件夹下拉，保存时 PUT 带 folder，服务端只换目录并
// 按新深度改写正文图片链接（移动后不裂图）。
// QuickAdd 不接入笔记（路由 meta 无 quickadd），新建走本视图按钮 + 弹层。
import { computed, onMounted, ref, watch } from "vue";
import { useNotesStore } from "../stores/notes";
import { useUiStore } from "../stores/ui";
import BaseModal from "../components/BaseModal.vue";
import MarkdownEditor from "../components/MarkdownEditor.vue";
import type { EditorMode } from "../components/MarkdownEditor.vue";
import { isInFolder, replaceFolderPrefix } from "../lib/folders";
import { composeDocBody, composePreview, parseTagsInput, stripLeadH1 } from "../lib/mdedit";
import { exportNoteHtml } from "../lib/exportHtml";
import { errMsg } from "../lib/format";
import type { FolderNode } from "../lib/folders";
import type { NoteFolder } from "../types";

const notes = useNotesStore();
const ui = useUiStore();

// 树选择：null = 全部笔记；"" = 根层散放；其余 = 文件夹 path（含其子树）
const selectedFolder = ref<string | null>(null);

// 编辑表单态：从 current 复制，保存时整体提交（PUT 全文更新语义）
const editTitle = ref("");
const editTags = ref("");
const editContent = ref("");
const editFolder = ref("");
const saving = ref(false);
const saveError = ref("");
const confirmDelete = ref(false);
const deleteError = ref("");
// 导出 HTML：导出中标记 + 成功摘要 / 失败提示
const exporting = ref(false);
const exportMsg = ref("");
const exportError = ref("");

// 右栏预览源：标题以 H1 合成（仅渲染，从不入库）；编辑区不出现 H1
const previewSource = computed(() => composePreview(editTitle.value, editContent.value));

onMounted(() => {
  if (!notes.items.length && !notes.loading) notes.load(ui.user);
});
watch(
  () => ui.user,
  () => {
    notes.close();
    selectedFolder.value = null;
    notes.load(ui.user);
  },
);
// 打开/切换笔记时回填表单
watch(
  () => notes.current,
  (n) => {
    if (n) {
      editTitle.value = n.title;
      editTags.value = n.tags.join(", ");
      editContent.value = stripLeadH1(n.content ?? "");
      editFolder.value = n.folder;
      saveError.value = "";
      confirmDelete.value = false;
      deleteError.value = "";
      exportMsg.value = "";
      exportError.value = "";
    }
  },
);

// 树拍平（默认全展开；数据量为个人笔记规模，无需折叠态）
const flatTree = computed<FolderNode[]>(() => {
  const out: FolderNode[] = [];
  const walk = (nodes: FolderNode[]) => {
    for (const n of nodes) {
      out.push(n);
      walk(n.children);
    }
  };
  walk(notes.folderTree);
  return out;
});

const visibleNotes = computed(() => {
  if (selectedFolder.value === null) return notes.items;
  return notes.items.filter((n) => isInFolder(n.folder, selectedFolder.value as string));
});

const selectedLabel = computed(() => {
  if (selectedFolder.value === null) return "全部笔记";
  if (selectedFolder.value === "") return "根层散放";
  return selectedFolder.value;
});

function open(id: string) {
  notes.open(id, ui.user).catch(() => {
    /* 详情加载失败保持列表 */
  });
}

async function save() {
  if (!notes.current || saving.value) return;
  saving.value = true;
  saveError.value = "";
  try {
    // folder 恒传：未改时服务端 no-op 幂等；改了即触发移动并按新深度改写资产链接
    await notes.update(
      notes.current.id,
      {
        title: editTitle.value,
        content: composeDocBody(editTitle.value, editContent.value),
        tags: parseTagsInput(editTags.value),
        related: notes.current.related,
        folder: editFolder.value,
      },
      ui.user,
    );
    notes.close();
  } catch (e) {
    saveError.value = errMsg(e);
  } finally {
    saving.value = false;
  }
}

/** 物理删除（两段式确认；服务端删除前已备份到 notes/.backup/） */
async function doDelete() {
  if (!notes.current || saving.value) return;
  if (!confirmDelete.value) {
    confirmDelete.value = true;
    return;
  }
  saving.value = true;
  deleteError.value = "";
  try {
    await notes.remove(notes.current.id, ui.user);
  } catch (e) {
    deleteError.value = errMsg(e);
    confirmDelete.value = false;
  } finally {
    saving.value = false;
  }
}

/** 图片上传闭包：归属当前编辑中选择的文件夹（保存时服务端再按最终深度定幂等归一） */
async function uploadImage(file: File) {
  return notes.uploadAsset(file, editFolder.value, ui.user);
}

/**
 * 导出当前笔记为单个自包含 HTML（图片 base64 内嵌，离线可看）。
 * 以编辑区当前内容为准（含未保存修改）——导出所见即所得；导出不写 data/。
 */
async function exportHtml() {
  if (!notes.current || exporting.value) return;
  exporting.value = true;
  exportMsg.value = "";
  exportError.value = "";
  try {
    const res = await exportNoteHtml({
      title: editTitle.value,
      markdown: previewSource.value,
      user: ui.user,
      imageBase: "/api/notes/assets",
    });
    const failedNote = res.failed.length ? `，${res.failed.length} 张图片内嵌失败` : "";
    exportMsg.value = `已导出 ${res.fileName}（内嵌 ${res.inlined} 张图${failedNote}）`;
  } catch (e) {
    exportError.value = errMsg(e);
  } finally {
    exporting.value = false;
  }
}

// ------------------------------------------------------------- 弹层：新建笔记

const showCreateNote = ref(false);
const newTitle = ref("");
const newFolder = ref("");
const createNoteError = ref("");
const creating = ref(false);

function openCreateNote() {
  newTitle.value = "";
  // 默认建在当前浏览的文件夹（"全部"视图下默认根层）
  newFolder.value = selectedFolder.value ?? "";
  createNoteError.value = "";
  showCreateNote.value = true;
}

async function submitCreateNote() {
  const title = newTitle.value.trim();
  if (!title || creating.value) return;
  creating.value = true;
  createNoteError.value = "";
  try {
    const note = await notes.create({ title, folder: newFolder.value }, ui.user);
    showCreateNote.value = false;
    await notes.open(note.id, ui.user);
  } catch (e) {
    createNoteError.value = errMsg(e);
  } finally {
    creating.value = false;
  }
}

// ------------------------------------------------------------- 弹层：文件夹

const showCreateFolder = ref(false);
const folderInput = ref("");
const folderError = ref("");
const folderBusy = ref(false);

const showRename = ref(false);
const renamePath = ref("");
const renameInput = ref("");
const renameError = ref("");

const showDeleteFolder = ref(false);
const deleteFolderPath = ref("");
const deleteFolderError = ref("");

function openCreateFolder() {
  // 在某文件夹内点新建 → 预填父路径前缀，用户补末段名（也可写 a/b 一次建多层）
  folderInput.value = selectedFolder.value ? `${selectedFolder.value}/` : "";
  folderError.value = "";
  showCreateFolder.value = true;
}

async function submitCreateFolder() {
  const path = folderInput.value.trim();
  if (!path || folderBusy.value) return;
  folderBusy.value = true;
  folderError.value = "";
  try {
    const folder = await notes.createFolder(path, ui.user);
    showCreateFolder.value = false;
    selectedFolder.value = folder.path;
  } catch (e) {
    folderError.value = errMsg(e);
  } finally {
    folderBusy.value = false;
  }
}

function openRename(f: NoteFolder) {
  renamePath.value = f.path;
  renameInput.value = f.path;
  renameError.value = "";
  showRename.value = true;
}

async function submitRename() {
  const next = renameInput.value.trim();
  if (!next || folderBusy.value) return;
  folderBusy.value = true;
  renameError.value = "";
  try {
    const folder = await notes.renameFolder(renamePath.value, next, ui.user);
    showRename.value = false;
    // 选中态跟随新路径（选中的正是被改名文件夹或其子树时）
    if (selectedFolder.value !== null && isInFolder(selectedFolder.value, renamePath.value)) {
      selectedFolder.value = replaceFolderPrefix(selectedFolder.value, renamePath.value, folder.path);
    }
  } catch (e) {
    renameError.value = errMsg(e);
  } finally {
    folderBusy.value = false;
  }
}

function openDeleteFolder(f: NoteFolder) {
  deleteFolderPath.value = f.path;
  deleteFolderError.value = "";
  showDeleteFolder.value = true;
}

async function submitDeleteFolder() {
  if (folderBusy.value) return;
  folderBusy.value = true;
  deleteFolderError.value = "";
  try {
    await notes.deleteFolder(deleteFolderPath.value, ui.user);
    showDeleteFolder.value = false;
    if (selectedFolder.value !== null && isInFolder(selectedFolder.value, deleteFolderPath.value)) {
      selectedFolder.value = null;
    }
  } catch (e) {
    // 非空 422 等后端中文契约：留在弹层内展示，不吞错
    deleteFolderError.value = errMsg(e);
  } finally {
    folderBusy.value = false;
  }
}

// 详情编辑器默认纯编辑（备忘才默认分屏）；类型仅用于模板可读性
const editorDefaultMode: EditorMode = "edit";
</script>

<template>
  <!-- ============================ 详情（可编辑） ============================ -->
  <div v-if="notes.current" class="note-detail">
    <button type="button" class="btn-ghost back" @click="notes.close()">‹ 返回笔记列表</button>
    <input v-model="editTitle" class="note-title-input" type="text" maxlength="200" placeholder="标题" />
    <div class="meta" style="margin-top: 8px; font-size: 11px; color: var(--muted)">
      {{ notes.current.date }}
      <span class="mono-path">{{ notes.current.filename || "根层" }}</span>
      <span v-if="notes.current.folder" class="tag t-blue">{{ notes.current.folder }}</span>
      <span v-else class="tag t-slate">根层散放</span>
      <span v-if="ui.user === 'example'" class="tag t-amber" style="margin-left: 6px">示例数据</span>
    </div>
    <div class="note-tags-row">
      <label>标签（逗号分隔）</label>
      <input v-model="editTags" type="text" placeholder="如：k8s, 网络" />
    </div>
    <!-- 移动控件：换文件夹 = 保存时 PUT 带 folder，服务端只换目录并改写图片链接 -->
    <div class="note-tags-row">
      <label>所属文件夹</label>
      <select v-model="editFolder" class="folder-select">
        <option value="">（根层散放）</option>
        <option v-for="f in flatTree" :key="f.path" :value="f.path">
          {{ "　".repeat(f.depth - 1) }}{{ f.name }}
        </option>
      </select>
    </div>

    <MarkdownEditor
      v-model="editContent"
      :preview-source="previewSource"
      :user="ui.user"
      image-base="/api/notes/assets"
      :default-mode="editorDefaultMode"
      :upload-image="uploadImage"
    />

    <div class="note-actions">
      <button class="btn-primary" :disabled="saving || !editTitle.trim()" @click="save">
        {{ saving ? "处理中…" : "保存" }}
      </button>
      <button v-if="!confirmDelete" class="btn-danger-ghost" :disabled="saving" @click="doDelete">删除</button>
      <template v-else>
        <button class="btn-danger" :disabled="saving" @click="doDelete">确认物理删除（.backup/ 有备份）</button>
        <button class="btn-ghost" :disabled="saving" @click="confirmDelete = false">取消</button>
      </template>
      <button
        type="button"
        class="btn-ghost"
        :disabled="exporting || saving"
        title="导出为单个 HTML 文件（图片以 base64 内嵌，离线可打开）"
        @click="exportHtml"
      >
        {{ exporting ? "导出中…" : "导出 HTML" }}
      </button>
      <span v-if="saveError || deleteError || exportError" class="qa-error">{{ saveError || deleteError || exportError }}</span>
      <span v-if="exportMsg" class="export-msg">{{ exportMsg }}</span>
    </div>
  </div>

  <!-- ============================ 树 + 列表 ============================ -->
  <div v-else class="notes-view">
    <aside class="notes-tree-panel">
      <div class="tree-head">
        <span>文件夹</span>
        <button type="button" class="link-btn" title="新建文件夹（可填 a/b 一次建多层）" @click="openCreateFolder">＋ 新建</button>
      </div>
      <div
        class="tree-node"
        :class="{ on: selectedFolder === null }"
        @click="selectedFolder = null"
      >
        <span class="tree-label">全部笔记</span>
        <span class="tree-count">{{ notes.items.length }}</span>
      </div>
      <div
        class="tree-node"
        :class="{ on: selectedFolder === '' }"
        @click="selectedFolder = ''"
      >
        <span class="tree-label">根层散放</span>
        <span class="tree-count">{{ notes.items.filter((n) => n.folder === '').length }}</span>
      </div>
      <template v-for="node in flatTree" :key="node.path">
        <div
          class="tree-node"
          :class="{ on: selectedFolder === node.path }"
          :style="{ paddingLeft: `${10 + node.depth * 14}px` }"
          @click="selectedFolder = node.path"
        >
          <span class="tree-label">{{ node.name }}</span>
          <span class="tree-actions">
            <button
              type="button"
              class="tree-act"
              title="重命名（同父目录）"
              @mousedown.prevent
              @click.stop="openRename(node)"
            >改名</button>
            <button
              type="button"
              class="tree-act tree-act-danger"
              title="删除空文件夹"
              @mousedown.prevent
              @click.stop="openDeleteFolder(node)"
            >删除</button>
          </span>
        </div>
      </template>
      <div v-if="!flatTree.length" class="tree-empty">还没有文件夹</div>
    </aside>

    <section class="notes-main">
      <div class="notes-list-head">
        <div class="notes-list-title">
          {{ selectedLabel }}
          <span class="tree-count">{{ visibleNotes.length }}</span>
        </div>
        <button type="button" class="btn-primary" @click="openCreateNote">＋ 新建笔记</button>
      </div>

      <div v-if="notes.error" class="empty">加载失败：{{ notes.error }}</div>
      <div v-else-if="!visibleNotes.length" class="empty">
        {{ notes.items.length ? "该文件夹下暂无笔记" : "暂无笔记（点右上角「新建笔记」开始）" }}
      </div>
      <div v-else class="notes">
        <div v-for="n in visibleNotes" :key="n.id" class="note" @click="open(n.id)">
          <h4>
            {{ n.title }}
            <span v-if="n.folder" class="tag t-blue folder-badge">{{ n.folder }}</span>
          </h4>
          <p>{{ n.excerpt }}</p>
          <div class="meta">
            {{ n.date }}<template v-for="t in n.tags" :key="t"> #{{ t }}</template>
          </div>
        </div>
      </div>
    </section>
  </div>

  <!-- ============================ 弹层 ============================ -->
  <BaseModal v-if="showCreateNote" @close="showCreateNote = false">
    <template #title>新建笔记</template>
    <div class="ep-form">
      <label class="ep-label">标题</label>
      <input
        v-model="newTitle"
        class="ep-input"
        type="text"
        maxlength="200"
        placeholder="笔记标题（回车新建）"
        @keydown.enter.prevent="submitCreateNote"
      />
      <label class="ep-label">所属文件夹</label>
      <select v-model="newFolder" class="folder-select">
        <option value="">（根层散放）</option>
        <option v-for="f in flatTree" :key="f.path" :value="f.path">
          {{ "　".repeat(f.depth - 1) }}{{ f.name }}
        </option>
      </select>
      <div v-if="createNoteError" class="qa-error">{{ createNoteError }}</div>
    </div>
    <template #foot>
      <button class="btn-ghost" @click="showCreateNote = false">取消</button>
      <button class="btn-primary" :disabled="creating || !newTitle.trim()" @click="submitCreateNote">
        {{ creating ? "处理中…" : "新建" }}
      </button>
    </template>
  </BaseModal>

  <BaseModal v-if="showCreateFolder" @close="showCreateFolder = false">
    <template #title>新建文件夹</template>
    <div class="ep-form">
      <label class="ep-label">文件夹路径（相对 notes/，斜杠分隔可一次建多层）</label>
      <input
        v-model="folderInput"
        class="ep-input"
        type="text"
        placeholder="如：读书/2026（保留名 .backup、assets 不可用）"
        @keydown.enter.prevent="submitCreateFolder"
      />
      <div v-if="folderError" class="qa-error">{{ folderError }}</div>
    </div>
    <template #foot>
      <button class="btn-ghost" @click="showCreateFolder = false">取消</button>
      <button class="btn-primary" :disabled="folderBusy || !folderInput.trim()" @click="submitCreateFolder">
        {{ folderBusy ? "处理中…" : "新建" }}
      </button>
    </template>
  </BaseModal>

  <BaseModal v-if="showRename" @close="showRename = false">
    <template #title>重命名文件夹</template>
    <div class="ep-form">
      <label class="ep-label">新路径（仅允许同父目录改名，跨目录移动会被后端拒绝）</label>
      <input
        v-model="renameInput"
        class="ep-input"
        type="text"
        @keydown.enter.prevent="submitRename"
      />
      <div class="ep-hint">原路径：{{ renamePath }}</div>
      <div v-if="renameError" class="qa-error">{{ renameError }}</div>
    </div>
    <template #foot>
      <button class="btn-ghost" @click="showRename = false">取消</button>
      <button class="btn-primary" :disabled="folderBusy || !renameInput.trim()" @click="submitRename">
        {{ folderBusy ? "处理中…" : "保存" }}
      </button>
    </template>
  </BaseModal>

  <BaseModal v-if="showDeleteFolder" @close="showDeleteFolder = false">
    <template #title>删除文件夹</template>
    <div class="ep-form">
      <p style="font-size: 13px; line-height: 1.8">
        确认删除空文件夹 <b>{{ deleteFolderPath }}</b>？<br />
        文件夹内仍有笔记或子文件夹时，后端会拒绝并给出中文提示。
      </p>
      <div v-if="deleteFolderError" class="qa-error">{{ deleteFolderError }}</div>
    </div>
    <template #foot>
      <button class="btn-ghost" @click="showDeleteFolder = false">取消</button>
      <button class="btn-danger" :disabled="folderBusy" @click="submitDeleteFolder">
        {{ folderBusy ? "处理中…" : "确认删除" }}
      </button>
    </template>
  </BaseModal>
</template>
