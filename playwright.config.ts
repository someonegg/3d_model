import { defineConfig } from "@playwright/test";
import path from "node:path";
import { repoRoot } from "./tools/runtime.mjs";

process.env.PLAYWRIGHT_HTML_OUTPUT_DIR = path.join(
  repoRoot,
  "tmp/playwright-report",
);

export default defineConfig({
  outputDir: path.join(repoRoot, "tmp/test-results/browser"),
  testDir: "tests/browser",
  forbidOnly: !!process.env.CI,
  timeout: 60000,
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:4273",
    headless: true,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    launchOptions: { args: ["--enable-unsafe-swiftshader"] },
  },
  webServer: [
    {
      command: "npm run preview -- --port 4273 --strictPort",
      url: "http://127.0.0.1:4273",
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --port 5273 --strictPort",
      url: "http://127.0.0.1:5273",
      env: { MODEL_ROOT: path.join(repoRoot, "tmp/fixtures") },
      reuseExistingServer: false,
    },
  ],
});
