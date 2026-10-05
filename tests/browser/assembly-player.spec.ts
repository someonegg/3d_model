import { test, expect } from "@playwright/test";
import path from "node:path";
import { repoRoot } from "../../tools/runtime.mjs";

const harnessURL = `/@fs/${path.join(repoRoot, "tests/browser/fixtures/assembly-harness.ts")}`;
test.beforeEach(async ({ page }) => {
  await page.route("**/assembly-test.html", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: `<div id="assembly-controls" hidden>
      <button id="assembly-play"></button><button id="assembly-previous"></button>
      <button id="assembly-next"></button></div>
      <div id="assembly-panel" hidden>
      <h2 id="assembly-title"></h2><p id="assembly-hint"></p>
    </div>`,
    }),
  );
  await page.goto("http://127.0.0.1:5273/assembly-test.html");
});

test("播放器按真实时间推进、只在步骤变化时更新外观并独立释放资源", async ({
  page,
}) => {
  const result = await page.evaluate(
    async (url) => (await import(url)).exercisePlayer(),
    harnessURL,
  );
  expect(result.initial).toEqual({
    isolated: true,
    opacity: [0.2, 0.2],
    highlighted: "463222",
    unchangedOther: true,
  });
  expect(result.steady.x).toBeCloseTo(2, 10);
  expect(result.steady.time).toBeCloseTo(2, 10);
  expect(result.steady).toMatchObject({
    titleMutations: 0,
    materialVersion: 0,
    requests: 2,
    playing: true,
  });
  expect(result.second).toEqual({
    title: "2 / 2 · 第二步",
    opacity: [0.7, 0.9],
    originalEmissive: true,
    bHighlighted: "463222",
  });
  expect(result.complete).toEqual({
    time: 10,
    playing: false,
    restored: true,
    markerVisible: false,
  });
  expect(result.replay).toEqual({ time: 0, playing: true });
  expect(result.backwards).toEqual({ time: 5, x: 5 });
  expect(result.disposed).toEqual({
    restored: true,
    markers: 0,
    x: 0,
    disposals: 5,
    playing: false,
    unbound: true,
  });
  expect(result.reentered).toEqual({ time: 0, children: 3 });
});

test("前进定位下一步起点或动画终点，后退先回本步起点", async ({ page }) => {
  const states = await page.evaluate(
    async (url) => (await import(url)).exerciseNavigation(),
    harnessURL,
  );
  expect(states.map((state: { time: number }) => state.time)).toEqual([
    0, 5, 0, 2, 0, 4, 5, 6, 5, 0, 10, 5, 10, 5,
  ]);
  expect(states[0]).toMatchObject({
    title: "1 / 2 · 第一步",
    previousDisabled: true,
    nextDisabled: false,
  });
  expect(states[1]).toMatchObject({
    title: "2 / 2 · 第二步",
    previousDisabled: false,
    nextDisabled: false,
    playing: false,
  });
  expect(states[3]).toMatchObject({
    previousDisabled: false,
    playing: true,
  });
  expect(states[6]).toMatchObject({
    title: "2 / 2 · 第二步",
    playing: false,
  });
  expect(states[7].playing).toBe(true);
  expect(states[10].playing).toBe(false);
  expect(states[12]).toMatchObject({
    title: "2 / 2 · 第二步",
    previousDisabled: false,
    nextDisabled: true,
    playing: false,
  });
  expect(states[13].nextDisabled).toBe(false);
  expect(states[11].title).toBe("2 / 2 · 第二步");
});

test("装配契约拒绝缺失目标、时长不符和根节点以外的引用", async ({ page }) => {
  const result = await page.evaluate(
    async (url) => (await import(url)).exerciseValidation(),
    harnessURL,
  );
  expect(result).toEqual([
    "targets",
    "duration",
    "outside",
    "root",
    "null-step",
  ]);
});

test("场景缓存复用、变体淘汰、版本失效与模型切换", async ({ page }) => {
  const result = await page.evaluate(
    async (url) => (await import(url)).exerciseCache(),
    harnessURL,
  );
  expect(result).toEqual({
    reused: true,
    replacedPrint: true,
    invalidated: true,
    switched: true,
    releases: 5,
  });
});
