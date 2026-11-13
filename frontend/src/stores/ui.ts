import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";

/** 外观主题偏好：跟随系统 / 浅色 / 深色 */
export type ThemePref = "system" | "light" | "dark";

/** localStorage 键；须与 index.html 防闪白内联脚本保持一致 */
const THEME_STORAGE_KEY = "workbench.theme";

function readThemePref(): ThemePref {
  try {
    const v = localStorage.getItem(THEME_STORAGE_KEY);
    if (v === "system" || v === "light" || v === "dark") return v;
  } catch {
    /* localStorage 不可用（隐私模式等）时退回跟随系统 */
  }
  return "system";
}

// 全局轻量状态：数据目录用户（me=真实 / example=示例数据）+ 外观主题
export const useUiStore = defineStore("ui", () => {
  // M2 起默认走真实数据路径 data/users/me/（验收纪律）；example 仍可切换，
  // 切换后所有写入口标"示例数据"提示
  const user = ref("me");

  // ---- 外观主题：<html data-theme> 驱动 app.css 的「磁青」token 翻转 ----
  const theme = ref<ThemePref>(readThemePref());

  // 系统深浅偏好：system 态下实时跟随 OS 切换
  const darkMQ = window.matchMedia("(prefers-color-scheme: dark)");
  const systemDark = ref(darkMQ.matches);
  darkMQ.addEventListener("change", (e) => {
    systemDark.value = e.matches;
  });

  /** 实际生效的主题（system 态解析为 light/dark） */
  const resolvedTheme = computed<"light" | "dark">(() =>
    theme.value === "system" ? (systemDark.value ? "dark" : "light") : theme.value,
  );

  watch(
    resolvedTheme,
    (t) => {
      document.documentElement.dataset.theme = t;
    },
    { immediate: true },
  );

  watch(theme, (t) => {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, t);
    } catch {
      /* 存不进则本次会话内仍生效，只是不跨会话记忆 */
    }
  });

  function setTheme(t: ThemePref) {
    theme.value = t;
  }

  return { user, theme, resolvedTheme, setTheme };
});
