<script setup lang="ts">
import { computed, watch } from "vue";
import { useRoute } from "vue-router";
import QuickAdd from "./components/QuickAdd.vue";
import { useUiStore } from "./stores/ui";
import { useTodosStore } from "./stores/todos";
import { useEventsStore } from "./stores/events";
import { useNotesStore } from "./stores/notes";
import { useTimelineStore } from "./stores/timeline";
import { todayCN } from "./lib/format";

const ui = useUiStore();
const route = useRoute();

const navItems = [
  { to: "/quadrant", ico: "🎯", label: "四象限" },
  { to: "/todos", ico: "✅", label: "待办" },
  { to: "/calendar", ico: "📅", label: "日历" },
  { to: "/timeline", ico: "🕘", label: "时间线" },
  { to: "/notes", ico: "📝", label: "备忘" },
];

const title = computed(() => (route.meta?.title as string) ?? "");
const showQuickadd = computed(() => Boolean(route.meta?.quickadd));
// 备忘视图记笔记，四象限/待办记待办（frontend/CLAUDE.md 界面基准）
const quickaddMode = computed<"todo" | "note">(() => (route.name === "notes" ? "note" : "todo"));

function reloadAll() {
  useTodosStore().load(ui.user);
  useEventsStore().load(ui.user);
  useNotesStore().load(ui.user);
  useTimelineStore().load(ui.user);
}

// 切换数据目录（me ↔ example）时全量刷新
watch(() => ui.user, reloadAll);
</script>

<template>
  <div class="app">
    <aside class="sidebar">
      <div class="brand">
        🗂 我的工作台<small>本地优先 · .ics/.md 直读直写</small>
      </div>
      <nav class="nav">
        <router-link v-for="n in navItems" :key="n.to" :to="n.to">
          <span class="ico">{{ n.ico }}</span> {{ n.label }}
        </router-link>
      </nav>
      <div class="datasource">
        数据目录（data/users/）
        <select v-model="ui.user">
          <option value="me">me · 我的真实数据</option>
          <option value="example">example · 示例数据</option>
        </select>
      </div>
      <div class="foot">数据 = Markdown + .ics<br />软件只是一层皮</div>
    </aside>

    <main class="main">
      <div class="topbar">
        <h1>{{ title }}</h1>
        <div class="date">{{ todayCN() }}</div>
      </div>
      <QuickAdd v-if="showQuickadd" :mode="quickaddMode" />
      <div class="view-body">
        <router-view />
      </div>
    </main>
  </div>
</template>
