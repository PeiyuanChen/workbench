import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// 开发服务器：/api 代理到本地 FastAPI 后端，前端一律用相对路径 /api
export default defineConfig({
  plugins: [vue()],
  server: {
    // 显式绑定 IPv4 回环，避免 Windows 上只绑 ::1 导致连不上
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
