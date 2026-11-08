<script setup lang="ts">
// 备忘视图：列表 ↔ 详情编辑（同视图切换，沿用 M1 范式）。
// M2：详情可编辑（标题/标签/正文），保存 = PUT 全文更新；
// 正文以 "# 标题" H1 开头由服务端维护，编辑区剥掉 H1、标题框承载。
// T1：链路命名 notes → memos（UI 中文文案仍为「备忘」）。
// #5：工具栏/预览/三模式/图片三入口迁入共享 MarkdownEditor，本视图只留业务编排，
// 默认分屏（split）保持迁移前行为零回退。
import { computed, onMounted, ref, watch } from "vue";
import { useMemosStore } from "../stores/memos";
import { useUiStore } from "../stores/ui";
import MarkdownEditor from "../components/MarkdownEditor.vue";
import { composeDocBody, composePreview, parseTagsInput, stripLeadH1 } from "../lib/mdedit";
import { errMsg } from "../lib/format";

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

// 预览源：标题以 H1 合成（仅渲染，从不入库）；编辑区不出现 H1
const previewSource = computed(() => composePreview(editTitle.value, editContent.value));

/** 图片上传走备忘资产端点；返回 path 恒为 assets/<名>，由共享编辑器插入正文 */
function uploadImage(file: File) {
  return memos.uploadAsset(file, ui.user);
}

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
    await memos.update(
      memos.current.id,
      {
        title: editTitle.value,
        content: composeDocBody(editTitle.value, editContent.value),
        tags: parseTagsInput(editTags.value),
        related: memos.current.related,
      },
      ui.user,
    );
    memos.close();
  } catch (e) {
    saveError.value = errMsg(e);
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
    deleteError.value = errMsg(e);
    confirmDelete.value = false;
  } finally {
    saving.value = false;
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
    <!-- 共享编辑器：默认分屏（迁移前即此行为），资产基址走备忘端点 -->
    <MarkdownEditor
      v-model="editContent"
      :preview-source="previewSource"
      :user="ui.user"
      image-base="/api/memos/assets"
      default-mode="split"
      :upload-image="uploadImage"
    />
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
