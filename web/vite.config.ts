import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 开发模式：前端 5173，/ws 与 /api 代理到网关 8090
// --mode static：纯静态回放站点（GitHub Pages 等），用相对路径以便部署在子路径下
export default defineConfig(({ mode }) => ({
  base: mode === "static" ? "./" : "/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/ws": { target: "ws://localhost:8090", ws: true },
      "/api": "http://localhost:8090",
      "/healthz": "http://localhost:8090",
    },
  },
  build: {
    outDir: "dist",
    chunkSizeWarningLimit: 2500,
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
}));
