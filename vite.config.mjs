import { defineConfig } from "vite";
import path from "node:path";
import { modelLibrary } from "./tools/model-plugin.mjs";
import { repoRoot } from "./tools/runtime.mjs";

export default defineConfig({
  root: path.join(repoRoot, "viewer"),
  appType: "mpa",
  base: "./",
  publicDir: false,
  optimizeDeps: {
    // 工作线程首次加载时也需要已完成优化的依赖，避免旧依赖请求返回 504。
    include: ["three/addons/loaders/STLLoader.js"],
  },
  server: {
    port: 5173,
    watch: {
      ignored: ["**/__pycache__/**"],
    },
  },
  preview: {
    port: 5173,
  },
  build: {
    outDir: "../tmp/site",
    emptyOutDir: false,
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      input: {
        index: path.resolve(repoRoot, "viewer/index.html"),
        view: path.resolve(repoRoot, "viewer/view.html"),
      },
    },
  },
  plugins: [
    modelLibrary(path.resolve(process.env.MODEL_LIBRARY_ROOT || repoRoot)),
  ],
});
