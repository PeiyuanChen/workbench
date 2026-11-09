<script setup lang="ts">
// 共享 Markdown 编辑器（#5：备忘 / 笔记复用，禁止两套近似实现）。
//
// 职责：textarea + 工具栏（粗斜体/标题/列表/表格/图片）+ 预览 + 三模式切换。
// - 三模式：edit 纯编辑 / split 分屏（左右）/ preview 纯预览；
//   模式是组件本地状态，不写入 md、不写入浏览器存储（验收硬要求），
//   组件随详情页 v-if 重新挂载时自然回到 defaultMode。
// - 正文经 v-model 双向绑定；预览源由父组件给（备忘/笔记都由标题框合成 H1，
//   编辑区不出现 H1），资产 URL 改写基址按模块参数化（imageBase）。
// - 图片三入口（按钮/粘贴/拖放）统一调父组件传入的 uploadImage，
//   插入服务端返回的 asset.path（笔记已按文件夹深度带 ../ 前缀）。
// 选区操作复用 lib/mdedit 纯函数，本组件不重写算法。
import { nextTick, ref } from "vue";
import MarkdownView from "./MarkdownView.vue";
import {
  insertBlock,
  TABLE_TEMPLATE,
  toggleLinePrefix,
  wrapInline,
  type EditState,
  type PrefixKind,
} from "../lib/mdedit";
import type { AssetUpload } from "../types";
import { errMsg } from "../lib/format";

export type EditorMode = "edit" | "split" | "preview";

const props = withDefaults(
  defineProps<{
    /** 正文（不含首行 H1，H1 由父组件标题框承载） */
    modelValue: string;
    /** 预览渲染源（父组件合成 H1 后的完整 Markdown） */
    previewSource: string;
    /** 数据目录参数（me/example…），拼到图片请求 query 上 */
    user?: string;
    /** 资产 HTTP 基址：备忘 /api/memos/assets，笔记 /api/notes/assets */
    imageBase: string;
    /** 初始模式：备忘默认分屏（现状零回退），笔记默认纯编辑 */
    defaultMode?: EditorMode;
    placeholder?: string;
    /** 图片上传由模块自己的 store 提供（笔记需带 folder 表单字段） */
    uploadImage: (file: File) => Promise<AssetUpload>;
  }>(),
  {
    user: "",
    defaultMode: "split",
    placeholder:
      "正文用 Markdown 书写：**粗体**、*斜体*、- 列表、表格；图片可点工具栏或直接粘贴/拖入",
  },
);

const emit = defineEmits<{ "update:modelValue": [value: string] }>();

// 本地模式态：仅 ref，不落 storage、不随文档保存
const mode = ref<EditorMode>(props.defaultMode);

const editorRef = ref<HTMLTextAreaElement | null>(null);
const fileInputRef = ref<HTMLInputElement | null>(null);
const uploading = ref(false);
const uploadError = ref("");

function onInput(e: Event) {
  emit("update:modelValue", (e.target as HTMLTextAreaElement).value);
}

// ------------------------------------------------- 工具栏：选区 Markdown 操作

/** 从 textarea 实时取 {文本, 选区} */
function currentEdit(): EditState {
  const el = editorRef.value;
  return {
    value: props.modelValue,
    selStart: el?.selectionStart ?? props.modelValue.length,
    selEnd: el?.selectionEnd ?? props.modelValue.length,
  };
}

/** 应用一次编辑结果并在 nextTick 后恢复光标/选区 */
function applyEdit(next: EditState) {
  emit("update:modelValue", next.value);
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
    // 用服务端返回的 path：备忘恒为 assets/<名>；笔记按文件夹深度带 ../ 前缀
    const asset = await props.uploadImage(file);
    const block = `\n![](${asset.path})\n`;
    const alt = block.indexOf("[]") + 1; // 光标落在 ![ ] 的说明位
    applyEdit(insertBlock(currentEdit(), block, [alt, alt]));
  } catch (e) {
    uploadError.value = errMsg(e);
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
  <div class="md-editor">
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
      <span class="md-sep"></span>
      <!-- 三模式切换：纯编辑 / 分屏 / 纯预览（本地态，不持久化） -->
      <div class="md-mode-switch" role="group" title="编辑模式（仅本次有效，不保存偏好）">
        <button type="button" :class="{ on: mode === 'edit' }" @click="mode = 'edit'">编辑</button>
        <button type="button" :class="{ on: mode === 'split' }" @click="mode = 'split'">分屏</button>
        <button type="button" :class="{ on: mode === 'preview' }" @click="mode = 'preview'">预览</button>
      </div>
      <span v-if="uploadError" class="qa-error">{{ uploadError }}</span>
    </div>

    <!-- v-show 而非 v-if：模式切换不销毁 textarea，保留撤销历史与选区 -->
    <div class="md-editor-body" :class="`is-${mode}`">
      <textarea
        v-show="mode !== 'preview'"
        ref="editorRef"
        :value="modelValue"
        class="note-editor"
        rows="20"
        :placeholder="placeholder"
        @input="onInput"
        @paste="onPaste"
        @dragover.prevent
        @drop="onDrop"
      ></textarea>
      <div v-show="mode !== 'edit'" class="note-preview">
        <MarkdownView :source="previewSource" :user="user" :image-base="imageBase" />
      </div>
    </div>
  </div>
</template>
