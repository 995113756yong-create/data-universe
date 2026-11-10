import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 开发模式：前端 5173，/ws 与 /api 代理到网关 8090
export default defineConfig({
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
});
