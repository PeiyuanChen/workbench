<script setup lang="ts">
// 备忘视图：列表 ↔ 详情编辑（同视图切换，沿用 M1 范式）。
// M2：详情可编辑（标题/标签/正文 textarea），保存 = PUT 全文更新；
// 不引入 markdown 渲染库（数据即纯文本，正文以 "# 标题" H1 开头由服务端维护）。
// T1：链路命名 notes → memos（UI 中文文案仍为「备忘」）。
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useMemosStore } from "../stores/memos";
import { useUiStore } from "../stores/ui";
import MarkdownView from "../components/MarkdownView.vue";
import {
  insertBlock,
  stripLeadH1,
  TABLE_TEMPLATE,
  toggleLinePrefix,
  wrapInline,
  type EditState,
  type PrefixKind,
} from "../lib/mdedit";

const memos = useMemosStore();
const ui = useUiStore();

// 编辑表单态：从 current 复制，保存时整体提交（PUT 全文更新语义）
const editTitle = ref("");
const editTags = ref("");
const editContent = ref("");
const saving = ref(false);
const saveError = ref("");
const confirmDelete = ref(false);
const deleteError = ref("");

// 编辑器/图片
const editorRef = ref<HTMLTextAreaElement | null>(null);
const fileInputRef = ref<HTMLInputElement | null>(null);
const uploading = ref(false);
const uploadError = ref("");

// 右栏预览源：标题以 H1 合成（仅渲染，从不入库）；编辑区不出现 H1
const previewSource = computed(() => {
  const t = editTitle.value.trim() || "未命名";
  return `# ${t}\n\n${editContent.value}`;
});

onMounted(() => {
  if (!memos.items.length && !memos.loading) memos.load(ui.user);
});
watch(() => ui.user, () => {
  memos.close();
  memos.load(ui.user);
});
// 打开/切换备忘时回填表单
watch(
  () => memos.current,
  (m) => {
    if (m) {
      editTitle.value = m.title;
      editTags.value = m.tags.join(", ");
      // 服务端把标题维护为正文首行 H1（三源一致）；编辑区剥掉它，由标题框承载
      editContent.value = stripLeadH1(m.content ?? "");
      saveError.value = "";
      confirmDelete.value = false;
      deleteError.value = "";
    }
  },
);

function open(id: string) {
  memos.open(id, ui.user).catch(() => {
    /* 详情加载失败保持列表 */
  });
}

async function save() {
  if (!memos.current || saving.value) return;
  saving.value = true;
  saveError.value = "";
  try {
    // 统一由前端合成首行 H1：恒命中服务端 _compose_body 的"首行匹配"分支，
    // GET→PUT 幂等，杜绝双 H1（正文本身已剥离 H1）
    const body = editContent.value.trim();
    const content = body ? `# ${editTitle.value}\n\n${body}` : `# ${editTitle.value}\n`;
    await memos.update(
      memos.current.id,
      {
        title: editTitle.value,
        content,
        tags: editTags.value
          .split(/[,，]/)
          .map((s) => s.trim())
          .filter(Boolean),
        related: memos.current.related,
      },
      ui.user,
    );
    memos.close();
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : String(e);
  } finally {
    saving.value = false;
  }
}

/** 物理删除（两段式确认；服务端删除前已备份到 memos/.backup/） */
async function doDelete() {
  if (!memos.current || saving.value) return;
  if (!confirmDelete.value) {
    confirmDelete.value = true;
    return;
  }
  saving.value = true;
  deleteError.value = "";
  try {
    await memos.remove(memos.current.id, ui.user);
  } catch (e) {
    deleteError.value = e instanceof Error ? e.message : String(e);
    confirmDelete.value = false;
  } finally {
    saving.value = false;
  }
}

// ------------------------------------------------- 工具栏：选区 Markdown 操作

/** 从 textarea 实时取 {文本, 选区} */
function currentEdit(): EditState {
  const el = editorRef.value;
  return {
    value: editContent.value,
    selStart: el?.selectionStart ?? editContent.value.length,
    selEnd: el?.selectionEnd ?? editContent.value.length,
  };
}

/** 应用一次编辑结果并在 nextTick 后恢复光标/选区 */
function applyEdit(next: EditState) {
  editContent.value = next.value;
  void nextTick(() => {
    const el = editorRef.value;
    if (!el) return;
    el.focus();
    el.setSelectionRange(next.selStart, next.selEnd);
  });
}

function onWrap(marker: "**" | "*") {
  applyEdit(wrapInline(currentEdit(), marker));
}

function onPrefix(kind: PrefixKind) {
  applyEdit(toggleLinePrefix(currentEdit(), kind));
}

function onTable() {
  // 光标落在数据行第一个空单元格（两个空格之间）
  const pos = TABLE_TEMPLATE.indexOf("\n|  ") + 3;
  applyEdit(insertBlock(currentEdit(), TABLE_TEMPLATE, [pos, pos]));
}

// ------------------------------------------------------------- 图片：三种入口

function pickImage() {
  uploadError.value = "";
  fileInputRef.value?.click();
}

async function onFilePicked(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  if (file) await uploadAndInsert(file);
  input.value = ""; // 允许重复选同一文件
}

async function uploadAndInsert(file: File) {
  if (!file.type.startsWith("image/")) {
    uploadError.value = "仅支持 png/jpg/jpeg/gif/webp 图片";
    return;
  }
  uploading.value = true;
  uploadError.value = "";
  try {
    const asset = await memos.uploadAsset(file, ui.user);
    const block = `\n![](assets/${asset.name})\n`;
    const alt = block.indexOf("[]") + 1; // 光标落在 ![ ] 的说明位
    applyEdit(insertBlock(currentEdit(), block, [alt, alt]));
  } catch (e) {
    uploadError.value = e instanceof Error ? e.message : String(e);
  } finally {
    uploading.value = false;
  }
}

/** 粘贴：剪贴板里是图片才拦截（截图直接粘贴）；文本粘贴保持默认 */
function onPaste(e: ClipboardEvent) {
  const file = Array.from(e.clipboardData?.files ?? []).find((f) => f.type.startsWith("image/"));
  if (file) {
    e.preventDefault();
    void uploadAndInsert(file);
  }
}

/** 拖放：拖入图片才拦截 */
function onDrop(e: DragEvent) {
  const file = Array.from(e.dataTransfer?.files ?? []).find((f) => f.type.startsWith("image/"));
  if (file) {
    e.preventDefault();
    void uploadAndInsert(file);
  }
}
</script>

<template>
  <!-- 详情（可编辑） -->
  <div v-if="memos.current" class="note-detail">
    <button type="button" class="btn-ghost back" @click="memos.close()">‹ 返回备忘列表</button>
    <input v-model="editTitle" class="note-title-input" type="text" maxlength="200" placeholder="标题" />
    <div class="meta" style="margin-top: 8px; font-size: 11px; color: var(--slate)">
      {{ memos.current.date }} · {{ memos.current.filename }}
      <span v-if="ui.user === 'example'" class="tag t-amber" style="margin-left: 6px">示例数据</span>
    </div>
    <div class="note-tags-row">
      <label>标签（逗号分隔）</label>
      <input v-model="editTags" type="text" placeholder="如：工作, 复盘" />
    </div>
    <!-- Markdown 工具栏（mousedown.prevent 防点击时 textarea 失焦） -->
    <div class="md-toolbar">
      <button type="button" title="粗体" @mousedown.prevent @click="onWrap('**')"><b>B</b></button>
      <button type="button" title="斜体" @mousedown.prevent @click="onWrap('*')"><i>I</i></button>
      <span class="md-sep"></span>
      <button type="button" title="小标题（大）" @mousedown.prevent @click="onPrefix('h2')">H2</button>
      <button type="button" title="小标题（中）" @mousedown.prevent @click="onPrefix('h3')">H3</button>
      <button type="button" title="小标题（小）" @mousedown.prevent @click="onPrefix('h4')">H4</button>
      <span class="md-sep"></span>
      <button type="button" title="无序列表" @mousedown.prevent @click="onPrefix('ul')">• 列表</button>
      <button type="button" title="有序列表" @mousedown.prevent @click="onPrefix('ol')">1. 列表</button>
      <button type="button" title="表格" @mousedown.prevent @click="onTable">表格</button>
      <button type="button" title="插入图片（也可直接粘贴/拖入）" :disabled="uploading" @mousedown.prevent @click="pickImage">
        {{ uploading ? "上传中…" : "🖼 图片" }}
      </button>
      <input
        ref="fileInputRef"
        type="file"
        accept="image/png,image/jpeg,image/gif,image/webp"
        hidden
        @change="onFilePicked"
      />
      <span v-if="uploadError" class="qa-error">⚠ {{ uploadError }}</span>
    </div>

    <!-- 分屏：左 Markdown 写作，右实时预览 -->
    <div class="note-edit-split">
      <textarea
        ref="editorRef"
        v-model="editContent"
        class="note-editor"
        rows="20"
        placeholder="正文用 Markdown 书写：**粗体**、*斜体*、- 列表、表格；图片可点工具栏或直接粘贴/拖入"
        @paste="onPaste"
        @dragover.prevent
        @drop="onDrop"
      ></textarea>
      <div class="note-preview">
        <MarkdownView :source="previewSource" :user="ui.user" />
      </div>
    </div>
    <div class="note-actions">
      <button class="btn-primary" :disabled="saving || !editTitle.trim()" @click="save">
        {{ saving ? "处理中…" : "保存" }}
      </button>
      <button v-if="!confirmDelete" class="btn-danger-ghost" :disabled="saving" @click="doDelete">🗑 删除</button>
      <template v-else>
        <button class="btn-danger" :disabled="saving" @click="doDelete">确认物理删除（.backup/ 有备份）</button>
        <button class="btn-ghost" :disabled="saving" @click="confirmDelete = false">取消</button>
      </template>
      <span v-if="saveError || deleteError" class="qa-error">⚠ {{ saveError || deleteError }}</span>
    </div>
  </div>

  <!-- 列表 -->
  <template v-else>
    <div v-if="memos.error" class="empty">加载失败：{{ memos.error }}</div>
    <div v-else-if="!memos.items.length" class="empty">暂无备忘（用上方快速记录框新建一篇）</div>
    <div v-else class="notes">
      <div v-for="m in memos.items" :key="m.id" class="note" @click="open(m.id)">
        <h4>{{ m.title }}</h4>
        <p>{{ m.excerpt }}</p>
        <div class="meta">
          {{ m.date }}
          <template v-for="t in m.tags" :key="t"> · #{{ t }}</template>
        </div>
      </div>
    </div>
  </template>
</template>
