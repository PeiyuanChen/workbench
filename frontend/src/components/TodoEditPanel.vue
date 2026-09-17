<script setup lang="ts">
// 待办编辑面板（SPEC-M2 决策 #10）：改时间（DUE / DTSTART+DURATION / 全天）、
// 象限两标签、描述、父子关系；完成/放弃/恢复动作；删除仅在"更多"里，二次确认
// （父任务的确认文案列出将被级联删除的子任务——决策 C）。
// 数据源 = GET /api/todos/{uid}（任何视图可开）；写成功后 store 以响应顶层节点替换。
// 时间输入为 naive（datetime-local/date 原生值），由后端按 Asia/Shanghai 解释——
// 前端严禁自行拼时区偏移。
import { computed, onMounted, ref, watch } from "vue";
import BaseModal from "./BaseModal.vue";
import { useTodosStore } from "../stores/todos";
import { useUiStore } from "../stores/ui";
import type { Todo, TodoPatch } from "../types";

const props = defineProps<{ uid: string }>();
const emit = defineEmits<{ close: []; changed: [] }>();

const todos = useTodosStore();
const ui = useUiStore();

const node = ref<Todo | null>(null);
const loadError = ref("");
const busy = ref(false);
const actionError = ref("");

// 表单态（从 node 复制；保存时整体组 TodoPatch，显式 null = 清除）
const summary = ref("");
const description = ref("");
const important = ref(false);
const urgent = ref(false);
const allDay = ref(false);
const due = ref("");
const dtstart = ref("");
const duration = ref<number | null>(null);
const parentUid = ref<string | null>(null);
const showMore = ref(false);
const confirmDelete = ref(false);

/** 后端 ISO → 输入控件值：date 输入取前 10 位；datetime-local 取到分钟（naive） */
function toInput(iso: string | null, isAllDay: boolean): string {
  if (!iso) return "";
  if (iso.length === 10) return isAllDay ? iso : `${iso}T00:00`;
  return iso.slice(0, 16);
}

onMounted(async () => {
  try {
    const n = await todos.fetchOne(props.uid, ui.user);
    node.value = n;
    summary.value = n.summary;
    description.value = n.description ?? "";
    important.value = n.important;
    urgent.value = n.urgent;
    allDay.value = n.all_day;
    due.value = toInput(n.due, n.all_day);
    dtstart.value = toInput(n.dtstart, n.all_day);
    duration.value = n.duration_minutes;
    parentUid.value = n.parent_uid;
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e);
  }
});

// 全天 ↔ 定时切换：截断/补齐输入值（后端保存时还会做权威截断）
watch(allDay, (v) => {
  if (v) {
    due.value = due.value.slice(0, 10);
    dtstart.value = dtstart.value.slice(0, 10);
  } else {
    if (due.value.length === 10) due.value = `${due.value}T09:00`;
    if (dtstart.value.length === 10) dtstart.value = `${dtstart.value}T09:00`;
  }
});

const hasChildren = computed(() => (node.value?.children?.length ?? 0) > 0);

// 父任务候选 = 主列表活跃顶层项（排除自己）。两级违例前端先挡：
// 本待办有子任务 → 不能再挂为别人的子任务（后端 422 兜底）。
const parentOptions = computed(() => {
  if (!node.value) return [];
  const opts = todos.items
    .filter((t) => t.uid !== node.value!.uid)
    .map((t) => ({ uid: t.uid, label: t.summary }));
  const cur = node.value.parent_uid;
  if (cur && !opts.some((o) => o.uid === cur)) {
    opts.unshift({ uid: cur, label: `当前父任务（${cur.slice(0, 20)}…）` });
  }
  return opts;
});

const statusText = computed(() => {
  const map: Record<string, string> = {
    "NEEDS-ACTION": "进行中",
    "IN-PROCESS": "进行中",
    COMPLETED: "已完成",
    CANCELLED: "已放弃",
  };
  return node.value ? (map[node.value.status] ?? node.value.status) : "";
});

/** 写响应是"受影响的顶层节点"：编辑子任务时返回父节点 → 从 children 找回自己 */
async function refreshSelf(updated: Todo) {
  if (updated.uid === props.uid) {
    node.value = updated;
    return;
  }
  const me = updated.children?.find((c) => c.uid === props.uid);
  node.value = me ?? (await todos.fetchOne(props.uid, ui.user));
}

async function save() {
  if (!node.value || busy.value) return;
  actionError.value = "";
  if (!summary.value.trim()) {
    actionError.value = "summary 不能为空";
    return;
  }
  // v-model.number 清空输入得到空串，统一归一为正整数或 null
  const dur =
    typeof duration.value === "number" && Number.isFinite(duration.value) && duration.value > 0
      ? Math.round(duration.value)
      : null;
  if (!dtstart.value && dur != null) {
    actionError.value = "执行块需要先填开始时间（duration 与 dtstart 成对）";
    return;
  }
  busy.value = true;
  try {
    const patch: TodoPatch = {
      summary: summary.value.trim(),
      description: description.value,
      important: important.value,
      urgent: urgent.value,
      all_day: allDay.value,
      due: due.value || null,
      dtstart: dtstart.value || null,
      duration_minutes: dtstart.value ? dur : null,
      parent_uid: parentUid.value || null,
    };
    await refreshSelf(await todos.patch(node.value.uid, patch, ui.user));
    // 表单态与落盘对齐（时间值以后端归一结果为准）
    if (node.value) {
      due.value = toInput(node.value.due, node.value.all_day);
      dtstart.value = toInput(node.value.dtstart, node.value.all_day);
      duration.value = node.value.duration_minutes;
    }
    emit("changed");
    emit("close");
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}

async function doAction(action: "complete" | "reopen" | "abandon") {
  if (!node.value || busy.value) return;
  busy.value = true;
  actionError.value = "";
  try {
    await refreshSelf(await todos.act(node.value.uid, action, ui.user));
    emit("changed");
    emit("close");
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}

/** 删除 = 物理移除（不可恢复；.backup/ 有备份）。两段式确认。 */
async function doDelete() {
  if (!node.value || busy.value) return;
  if (!confirmDelete.value) {
    confirmDelete.value = true;
    return;
  }
  busy.value = true;
  actionError.value = "";
  try {
    await todos.remove(node.value.uid, ui.user);
    emit("changed");
    emit("close");
  } catch (e) {
    actionError.value = e instanceof Error ? e.message : String(e);
    confirmDelete.value = false;
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <BaseModal @close="emit('close')">
    <template #title>
      <span v-if="node">编辑待办 · <em class="ep-status" :class="node.status.toLowerCase()">{{ statusText }}</em></span>
      <span v-else>编辑待办</span>
    </template>

    <div v-if="loadError" class="qa-error">⚠ {{ loadError }}</div>
    <form v-else-if="node" class="ep-form" @submit.prevent="save">
      <label class="ep-label">标题</label>
      <input v-model="summary" class="ep-input" type="text" maxlength="200" />

      <label class="ep-label">象限标签</label>
      <div class="ep-toggles">
        <button type="button" class="qa-toggle" :class="{ 'on-imp': important }" @click="important = !important">重要</button>
        <button type="button" class="qa-toggle" :class="{ 'on-urg': urgent }" @click="urgent = !urgent">紧急</button>
        <label class="ep-allday"><input v-model="allDay" type="checkbox" /> 全天（VALUE=DATE）</label>
      </div>

      <label class="ep-label">截止时间（DUE · ⚑ 小旗）</label>
      <input v-model="due" class="ep-input" :type="allDay ? 'date' : 'datetime-local'" />

      <label class="ep-label">执行块（DTSTART + DURATION · ▸ 色块）</label>
      <div class="ep-block-row">
        <input v-model="dtstart" class="ep-input" :type="allDay ? 'date' : 'datetime-local'" title="开始时间" />
        <input
          v-model.number="duration"
          class="ep-input ep-duration"
          type="number"
          min="1"
          step="1"
          placeholder="分钟"
          title="时长（分钟）；全天按 1440=1 天"
        />
      </div>

      <label class="ep-label">描述</label>
      <textarea v-model="description" class="ep-textarea" rows="3"></textarea>

      <label class="ep-label">父任务（默认两级）</label>
      <select v-model="parentUid" class="ep-input" :disabled="hasChildren">
        <option :value="null">（无 · 顶层任务）</option>
        <option v-for="o in parentOptions" :key="o.uid" :value="o.uid">{{ o.label }}</option>
      </select>
      <div v-if="hasChildren" class="ep-hint">该待办名下已有子任务，不能再挂为别人的子任务（默认两级）</div>

      <!-- 状态动作（决策 #1/#9：完成与放弃可互相恢复） -->
      <div class="ep-actions">
        <template v-if="node.status === 'COMPLETED' || node.status === 'CANCELLED'">
          <button type="button" class="btn-ghost" :disabled="busy" @click="doAction('reopen')">↩ 恢复为进行中</button>
        </template>
        <template v-else>
          <button type="button" class="btn-ghost ok" :disabled="busy" @click="doAction('complete')">✓ 完成</button>
          <button type="button" class="btn-ghost warn" :disabled="busy" @click="doAction('abandon')">✕ 放弃</button>
        </template>
        <button type="button" class="btn-ghost" @click="showMore = !showMore">{{ showMore ? "▾ 收起更多" : "… 更多" }}</button>
      </div>

      <!-- 更多：物理删除（仅此入口，两段式确认） -->
      <div v-if="showMore" class="ep-more">
        <template v-if="!confirmDelete">
          <button type="button" class="btn-danger" :disabled="busy" @click="doDelete">🗑 删除（物理移除）</button>
        </template>
        <template v-else>
          <div class="ep-confirm">
            <div>确认物理删除？不可恢复（.backup/ 内有备份）。</div>
            <div v-if="hasChildren" class="ep-confirm-list">
              ⚠ 将级联删除 {{ node.children.length }} 个子任务：
              <ul><li v-for="c in node.children" :key="c.uid">{{ c.summary }}</li></ul>
            </div>
            <div class="ep-confirm-btns">
              <button type="button" class="btn-danger" :disabled="busy" @click="doDelete">确认删除</button>
              <button type="button" class="btn-ghost" @click="confirmDelete = false">取消</button>
            </div>
          </div>
        </template>
      </div>

      <div v-if="actionError" class="qa-error">⚠ {{ actionError }}</div>
    </form>

    <template #foot>
      <button type="button" class="btn-ghost" @click="emit('close')">关闭</button>
      <button type="button" class="btn-primary" :disabled="busy || !node" @click="save">{{ busy ? "处理中…" : "保存" }}</button>
    </template>
  </BaseModal>
</template>
