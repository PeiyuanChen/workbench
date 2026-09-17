<script setup lang="ts">
// 备忘视图：列表 ↔ 详情编辑（同视图切换，沿用 M1 范式）。
// M2：详情可编辑（标题/标签/正文 textarea），保存 = PUT 全文更新；
// 不引入 markdown 渲染库（数据即纯文本，正文以 "# 标题" H1 开头由服务端维护）。
import { onMounted, ref, watch } from "vue";
import { useNotesStore } from "../stores/notes";
import { useUiStore } from "../stores/ui";

const notes = useNotesStore();
const ui = useUiStore();

// 编辑表单态：从 current 复制，保存时整体提交（PUT 全文更新语义）
const editTitle = ref("");
const editTags = ref("");
const editContent = ref("");
const saving = ref(false);
const saveError = ref("");
const confirmDelete = ref(false);
const deleteError = ref("");

onMounted(() => {
  if (!notes.items.length && !notes.loading) notes.load(ui.user);
});
watch(() => ui.user, () => {
  notes.close();
  notes.load(ui.user);
});
// 打开/切换笔记时回填表单
watch(
  () => notes.current,
  (n) => {
    if (n) {
      editTitle.value = n.title;
      editTags.value = n.tags.join(", ");
      editContent.value = n.content ?? "";
      saveError.value = "";
      confirmDelete.value = false;
      deleteError.value = "";
    }
  },
);

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
    await notes.update(
      notes.current.id,
      {
        title: editTitle.value,
        content: editContent.value,
        tags: editTags.value
          .split(/[,，]/)
          .map((s) => s.trim())
          .filter(Boolean),
        related: notes.current.related,
      },
      ui.user,
    );
    notes.close();
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : String(e);
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
    deleteError.value = e instanceof Error ? e.message : String(e);
    confirmDelete.value = false;
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <!-- 详情（可编辑） -->
  <div v-if="notes.current" class="note-detail">
    <span class="back" @click="notes.close()">‹ 返回备忘列表</span>
    <input v-model="editTitle" class="note-title-input" type="text" maxlength="200" placeholder="标题" />
    <div class="meta" style="margin-top: 8px; font-size: 11px; color: var(--slate)">
      {{ notes.current.date }} · {{ notes.current.filename }}
      <span v-if="ui.user === 'example'" class="tag t-amber" style="margin-left: 6px">示例数据</span>
    </div>
    <div class="note-tags-row">
      <label>标签（逗号分隔）</label>
      <input v-model="editTags" type="text" placeholder="如：工作, 复盘" />
    </div>
    <textarea
      v-model="editContent"
      class="note-editor"
      rows="18"
      placeholder="正文（Markdown 纯文本；首行 # 标题 由服务端维护三源一致）"
    ></textarea>
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
    <div v-if="notes.error" class="empty">加载失败：{{ notes.error }}</div>
    <div v-else-if="!notes.items.length" class="empty">暂无备忘（用上方快速记录框新建一篇）</div>
    <div v-else class="notes">
      <div v-for="n in notes.items" :key="n.id" class="note" @click="open(n.id)">
        <h4>{{ n.title }}</h4>
        <p>{{ n.excerpt }}</p>
        <div class="meta">
          {{ n.date }}
          <template v-for="t in n.tags" :key="t"> · #{{ t }}</template>
        </div>
      </div>
    </div>
  </template>
</template>
