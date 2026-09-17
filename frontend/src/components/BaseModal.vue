<script setup lang="ts">
// 基础弹层基元（M2 首个 modal）：遮罩点击/Esc 关闭；title 与 foot 具名插槽。
import { onBeforeUnmount, onMounted } from "vue";

const emit = defineEmits<{ close: [] }>();

function onKey(e: KeyboardEvent) {
  if (e.key === "Escape") emit("close");
}

onMounted(() => window.addEventListener("keydown", onKey));
onBeforeUnmount(() => window.removeEventListener("keydown", onKey));
</script>

<template>
  <div class="modal-mask" @click.self="emit('close')">
    <div class="modal-panel" role="dialog" aria-modal="true">
      <div class="modal-head">
        <slot name="title" />
        <button type="button" class="modal-x" title="关闭（Esc）" @click="emit('close')">×</button>
      </div>
      <div class="modal-body"><slot /></div>
      <div v-if="$slots.foot" class="modal-foot"><slot name="foot" /></div>
    </div>
  </div>
</template>
