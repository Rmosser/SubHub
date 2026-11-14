import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  base: "/manage/",
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      "/api": "http://localhost:8080",
      "/sub": "http://localhost:8080",
      "/static": "http://localhost:8080",
    },
  },
  build: {
    outDir: "../app/static/frontend/dist",
    emptyOutDir: true,
  },
});
