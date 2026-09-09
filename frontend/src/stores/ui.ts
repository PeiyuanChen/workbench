import { defineStore } from "pinia";
import { ref } from "vue";

// 全局轻量状态：数据目录用户（me=真实 / example=示例数据）
export const useUiStore = defineStore("ui", () => {
  const user = ref("example"); // M1 演示期默认 example（有示例数据）
  return { user };
});
