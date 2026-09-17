import { defineStore } from "pinia";
import { ref } from "vue";

// 全局轻量状态：数据目录用户（me=真实 / example=示例数据）
export const useUiStore = defineStore("ui", () => {
  // M2 起默认走真实数据路径 data/users/me/（验收纪律）；example 仍可切换，
  // 切换后所有写入口标"示例数据"提示
  const user = ref("me");
  return { user };
});
