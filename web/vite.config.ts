import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // 서브경로 배포용. nginx 뒤 /wiki/ 로 붙일 때 VITE_BASE=/wiki/ 로 빌드한다.
  base: process.env.VITE_BASE ?? "/",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8722",
    },
  },
  build: {
    outDir: "dist",
    chunkSizeWarningLimit: 1500,
  },
});
