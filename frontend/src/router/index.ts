import { createRouter, createWebHashHistory } from "vue-router";
import type { RouteRecordRaw } from "vue-router";

// 五视图路由（hash 模式：本地/PWA 场景最稳，无需服务端 history 回退）
// meta.quickadd：该视图是否显示"＋快速记录"框（仅四象限/待办/备忘）
export const routes: RouteRecordRaw[] = [
  { path: "/", redirect: "/quadrant" },
  { path: "/quadrant", name: "quadrant", component: () => import("../views/QuadrantView.vue"), meta: { title: "四象限", quickadd: true } },
  { path: "/todos", name: "todos", component: () => import("../views/TodoView.vue"), meta: { title: "待办", quickadd: true } },
  { path: "/calendar", name: "calendar", component: () => import("../views/CalendarView.vue"), meta: { title: "日历" } },
  { path: "/timeline", name: "timeline", component: () => import("../views/TimelineView.vue"), meta: { title: "时间线" } },
  { path: "/notes", name: "notes", component: () => import("../views/NotesView.vue"), meta: { title: "备忘", quickadd: true } },
];

const router = createRouter({
  history: createWebHashHistory(),
  routes,
});

export default router;
