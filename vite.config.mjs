import { defineConfig } from "vite";
import path from "node:path";
import { modelLibrary } from "./tools/model-plugin.mjs";
import { repoRoot } from "./tools/runtime.mjs";

export default defineConfig({
  root: "viewer",
  appType: "mpa",
  base: "./",
  publicDir: false,
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
  plugins: [modelLibrary(path.resolve(process.env.MODEL_ROOT || repoRoot))],
});
