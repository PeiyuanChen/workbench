<script setup lang="ts">
// 事件新建/编辑表单（SPEC-M2 决策 #8：入口在日历页；快速记录框不建事件）。
//
// ⚠ 全天日期的排他语义转换（SPEC-M2 §2.2，专项测试覆盖）：
//   API/ics 的 DTEND 恒为 RFC 5545 排他日语义（不含当天）；
//   本表单呈现为"含首尾"——提交时 结束日 +1 天，回显时 结束日 -1 天。
// 定时事件用 开始/结束 datetime-local（naive，不拼时区，后端按 Asia/Shanghai 解释）；
// dtend 与 duration_minutes 二选一，本表单统一走 dtend（duration 仅 API 层支持）。
import { computed, onMounted, ref } from "vue";
import BaseModal from "./BaseModal.vue";
import { useEventsStore } from "../stores/events";
import { useUiStore } from "../stores/ui";
import type { EventDetail } from "../types";

const props = defineProps<{ uid?: string; initialDate?: string }>();
const emit = defineEmits<{ close: [] }>();

const ev = useEventsStore();
const ui = useUiStore();

const isEdit = computed(() => Boolean(props.uid));
const detail = ref<EventDetail | null>(null);
const loadError = ref("");
const busy = ref(false);
const formError = ref("");
const showMore = ref(false);
const confirmDelete = ref(false);

// 表单态（UI 语义：全天结束日 = 含尾）
const summary = ref("");
const allDay = ref(false);
const startVal = ref(""); // date 或 datetime-local 值
const endVal = ref(""); // UI 含尾；提交时全天 +1 天转排他
const location = ref("");
const description = ref("");

/** YYYY-MM-DD ± n 天（本地构造，避免 UTC 解析偏移一天） */
function addDays(dateStr: string, n: number): string {
  const d = new Date(`${dateStr}T00:00:00`);
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

onMounted(async () => {
  if (props.uid) {
    try {
      const e = await ev.fetchOne(props.uid, ui.user);
      detail.value = e;
      summary.value = e.summary;
      allDay.value = e.all_day;
      location.value = e.location ?? "";
      description.value = e.description ?? "";
      if (e.all_day) {
        startVal.value = (e.dtstart ?? "").slice(0, 10);
        // 回显：排他 DTEND -1 天 = 用户视角的最后一天
        endVal.value = e.dtend ? addDays(e.dtend.slice(0, 10), -1) : startVal.value;
      } else {
        startVal.value = (e.dtstart ?? "").slice(0, 16);
        endVal.value = (e.dtend ?? "").slice(0, 16);
      }
    } catch (e) {
      loadError.value = e instanceof Error ? e.message : String(e);
    }
  } else {
    // 新建：预填点击的日期（全天默认开，符合"点某天建当天事件"直觉）
    allDay.value = true;
    startVal.value = props.initialDate ?? "";
    endVal.value = props.initialDate ?? "";
  }
});

/** 组装提交用的 dtstart/dtend（API 语义：dtend 排他；naive 由后端按上海解释） */
function buildTimes(): { dtstart: string; dtend: string | null } | null {
  if (!startVal.value) {
    formError.value = "开始时间不能为空";
    return null;
  }
  if (allDay.value) {
    if (endVal.value && endVal.value < startVal.value) {
      formError.value = "结束日不能早于开始日（呈现为含首尾）";
      return null;
    }
    // 提交：含尾结束日 +1 天 → RFC 排他 DTEND；未填结束日交给后端缺省（次日）
    return {
      dtstart: startVal.value,
      dtend: endVal.value ? addDays(endVal.value, 1) : null,
    };
  }
  if (endVal.value && endVal.value <= startVal.value) {
    formError.value = "结束时间必须晚于开始时间";
    return null;
  }
  return { dtstart: startVal.value, dtend: endVal.value || null };
}

async function save() {
  if (busy.value) return;
  formError.value = "";
  if (!summary.value.trim()) {
    formError.value = "summary 不能为空";
    return;
  }
  const times = buildTimes();
  if (!times) return;
  busy.value = true;
  try {
    const payload = {
      summary: summary.value.trim(),
      all_day: allDay.value,
      location: location.value,
      description: description.value,
      ...times,
    };
    if (isEdit.value && props.uid) await ev.patch(props.uid, payload, ui.user);
    else await ev.create(payload, ui.user);
    emit("close");
  } catch (e) {
    formError.value = e instanceof Error ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}

/** 物理删除（两段式确认；.backup/ 有备份） */
async function doDelete() {
  if (!props.uid || busy.value) return;
  if (!confirmDelete.value) {
    confirmDelete.value = true;
    return;
  }
  busy.value = true;
  formError.value = "";
  try {
    await ev.remove(props.uid, ui.user);
    emit("close");
  } catch (e) {
    formError.value = e instanceof Error ? e.message : String(e);
    confirmDelete.value = false;
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <BaseModal @close="emit('close')">
    <template #title>{{ isEdit ? "编辑事件" : "新建事件" }}</template>

    <div v-if="loadError" class="qa-error">⚠ {{ loadError }}</div>
    <form v-else class="ep-form" @submit.prevent="save">
      <label class="ep-label">标题</label>
      <input v-model="summary" class="ep-input" type="text" maxlength="200" placeholder="事件标题" />

      <div class="ep-toggles" style="margin-top: 10px">
        <label class="ep-allday"><input v-model="allDay" type="checkbox" /> 全天事件</label>
        <span v-if="allDay" class="ep-hint">结束日按"含首尾"呈现，落盘为 RFC 排他 DTEND（+1 天）</span>
      </div>

      <label class="ep-label">开始</label>
      <input v-model="startVal" class="ep-input" :type="allDay ? 'date' : 'datetime-local'" />

      <label class="ep-label">结束{{ allDay ? "（含当天）" : "" }}</label>
      <input v-model="endVal" class="ep-input" :type="allDay ? 'date' : 'datetime-local'" />
      <div v-if="!allDay" class="ep-hint">留空 = 开始后 30 分钟（服务端缺省）</div>

      <label class="ep-label">地点</label>
      <input v-model="location" class="ep-input" type="text" placeholder="可选" />

      <label class="ep-label">描述</label>
      <textarea v-model="description" class="ep-textarea" rows="2" placeholder="可选"></textarea>

      <div v-if="isEdit" class="ep-actions">
        <button type="button" class="btn-ghost" @click="showMore = !showMore">
          {{ showMore ? "▾ 收起更多" : "… 更多" }}
        </button>
      </div>
      <div v-if="isEdit && showMore" class="ep-more">
        <template v-if="!confirmDelete">
          <button type="button" class="btn-danger" :disabled="busy" @click="doDelete">🗑 删除事件（物理移除）</button>
        </template>
        <template v-else>
          <div class="ep-confirm">
            <div>确认物理删除该事件？不可恢复（.backup/ 内有备份）。</div>
            <div class="ep-confirm-btns">
              <button type="button" class="btn-danger" :disabled="busy" @click="doDelete">确认删除</button>
              <button type="button" class="btn-ghost" @click="confirmDelete = false">取消</button>
            </div>
          </div>
        </template>
      </div>

      <div v-if="formError" class="qa-error">⚠ {{ formError }}</div>
      <div v-if="ui.user === 'example'" class="qa-example-hint">正在写入示例数据（data/users/example/）</div>
    </form>

    <template #foot>
      <button type="button" class="btn-ghost" @click="emit('close')">取消</button>
      <button type="button" class="btn-primary" :disabled="busy" @click="save">
        {{ busy ? "保存中…" : "保存" }}
      </button>
    </template>
  </BaseModal>
</template>
