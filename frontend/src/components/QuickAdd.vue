<script setup lang="ts">
// ＋快速记录框（SPEC-M2 决策 #5/#6；仅四象限/待办/备忘三视图显示，由路由 meta.quickadd 控制）
// - todo 模式：输入框 + 重要/紧急两个 toggle（默认都 FALSE）+ 回车即创建未排期待办；
//   不做文本符号解析（无 !/?/#tag 魔法语法），分类标签 M2 不在此输入。
// - note 模式：输入标题回车 → 创建 md（服务端生成 id/文件名）→ 打开正文编辑。
// 失败行内显示后端中文 detail（不做乐观更新）。
import { ref } from "vue";
import { useNotesStore } from "../stores/notes";
import { useTodosStore } from "../stores/todos";
import { useUiStore } from "../stores/ui";

const props = defineProps<{ mode: "todo" | "note" }>();

const todos = useTodosStore();
const notes = useNotesStore();
const ui = useUiStore();

const text = ref("");
const important = ref(false);
const urgent = ref(false);
const submitting = ref(false);
const inlineError = ref("");

async function submit() {
  const value = text.value.trim();
  if (!value || submitting.value) return;
  submitting.value = true;
  inlineError.value = "";
  try {
    if (props.mode === "todo") {
      await todos.create(
        { summary: value, important: important.value, urgent: urgent.value },
        ui.user,
      );
      text.value = "";
      important.value = false;
      urgent.value = false;
    } else {
      // create 内部 await load 重拉列表，停留在列表页（不跳详情）
      await notes.create({ title: value }, ui.user);
      text.value = "";
    }
  } catch (e) {
    inlineError.value = e instanceof Error ? e.message : String(e);
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="quickadd live">
    <div class="qa-row">
      <input
        v-model="text"
        class="qa-input"
        type="text"
        maxlength="200"
        :placeholder="
          mode === 'note'
            ? '＋ 快速记一条备忘…（随手写想法/决策，回车新建一篇）'
            : '＋ 快速记录一件最近要做的事…（先不设时间也可以，回车进入待办）'
        "
        :disabled="submitting"
        @keydown.enter.prevent="submit"
      />
      <template v-if="mode === 'todo'">
        <button
          type="button"
          class="qa-toggle"
          :class="{ 'on-imp': important }"
          title="重要（艾森豪威尔 IMPORTANT 标签）"
          @click="important = !important"
        >
          重要
        </button>
        <button
          type="button"
          class="qa-toggle"
          :class="{ 'on-urg': urgent }"
          title="紧急（艾森豪威尔 URGENT 标签）"
          @click="urgent = !urgent"
        >
          紧急
        </button>
      </template>
      <button type="button" class="qa-add" :disabled="submitting || !text.trim()" @click="submit">
        {{ submitting ? "…" : "添加" }}
      </button>
    </div>
    <div v-if="inlineError" class="qa-error">⚠ {{ inlineError }}</div>
    <div v-if="ui.user === 'example'" class="qa-example-hint">正在写入示例数据（data/users/example/）</div>
  </div>
</template>
