import { test, expect, type Page } from "@playwright/test";
import path from "node:path";
import { repoRoot } from "../../tools/runtime.mjs";

const assemblyHint = "红点标示定位部位 · 高亮显示当前零件";
const navigationHint = "拖动旋转 · 滚轮缩放 · 右键平移";

async function expectAssemblyLayout(page: Page) {
  await expect(page.locator("#model-info")).toBeVisible();
  await expect(page.locator("#assembly-controls")).toBeVisible();
  await expect(page.locator("#interaction-hint")).toHaveText(assemblyHint);
  await expect(page.locator(".assembly-legend")).toHaveCount(0);
  const info = (await page.locator("#model-info").boundingBox())!;
  const panel = (await page.locator("#assembly-panel").boundingBox())!;
  expect(panel.y).toBeGreaterThanOrEqual(info.y + info.height);
  const viewport = (await page.locator("#viewport").boundingBox())!;
  const controls = (await page.locator("#assembly-controls").boundingBox())!;
  const views = (await page.locator(".view-controls").boundingBox())!;
  expect(controls.x).toBeGreaterThanOrEqual(viewport.x);
  expect(controls.y).toBeGreaterThanOrEqual(viewport.y);
  expect(
    viewport.x + viewport.width - controls.x - controls.width,
  ).toBeLessThanOrEqual(17);
  expect(
    viewport.y + viewport.height - controls.y - controls.height,
  ).toBeLessThanOrEqual(17);
  expect(
    views.x + views.width <= controls.x || views.y + views.height <= controls.y,
  ).toBe(true);
  expect(
    await page
      .locator(".viewport-controls")
      .evaluate((el) => getComputedStyle(el).pointerEvents),
  ).toBe("none");
  expect(
    await page
      .locator("#assembly-play")
      .evaluate((el) => getComputedStyle(el).pointerEvents),
  ).toBe("auto");
}

for (const [model, steps] of [
  ["keyboard-fidget-fdm", 5],
  ["retractable-shuriken-fdm", 4],
  ["volvo-xc60-2022", 10],
] as const) {
  test(`${model} 装配控制、播放结束后重播与模式切换`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(`/?model=${model}&mode=assembly`);
    await expect(page.locator("#assembly-title")).toContainText(`1 / ${steps}`);
    await expect(page.locator("#status")).toBeEmpty();
    await expect(page.locator("#model-info")).toBeVisible();
    await expect(page.locator("#variants")).toBeDisabled();
    await expect(
      page.locator("#assembly-progress, #assembly-restart, #fit"),
    ).toHaveCount(0);
    const panel = await page.locator("#assembly-panel").boundingBox();
    const viewport = await page.locator("#viewport").boundingBox();
    expect(panel!.x).toBeGreaterThanOrEqual(viewport!.x + viewport!.width);
    await expectAssemblyLayout(page);
    await expect(page.locator("#assembly-previous")).toHaveText("后退");
    await expect(page.locator("#assembly-next")).toHaveText("前进");
    await expect(page.locator("#assembly-previous")).toBeDisabled();
    await expect(page.locator("#assembly-previous")).toHaveCSS(
      "background-color",
      "rgb(217, 224, 229)",
    );
    await expect(page.locator("#assembly-previous")).toHaveCSS(
      "cursor",
      "not-allowed",
    );
    await expect(page.locator("#assembly-next")).toHaveCSS("cursor", "pointer");
    const initial = await page.locator("#viewport canvas").screenshot();
    const playStyle = await page
      .locator("#assembly-play")
      .evaluate((button) => {
        const style = getComputedStyle(button);
        return [style.backgroundColor, style.color, style.borderColor];
      });
    await page.locator("#assembly-play").click();
    await expect(page.locator("#assembly-play")).toHaveText("暂停");
    expect(
      await page.locator("#assembly-play").evaluate((button) => {
        const style = getComputedStyle(button);
        return [style.backgroundColor, style.color, style.borderColor];
      }),
    ).toEqual(playStyle);
    await page.waitForTimeout(250);
    await page.locator("#assembly-play").click();
    const paused = await page.locator("#viewport canvas").screenshot();
    await page.waitForTimeout(200);
    expect(await page.locator("#viewport canvas").screenshot()).toEqual(paused);
    for (let step = 2; step <= steps; step++) {
      await page.locator("#assembly-next").click();
      await expect(page.locator("#assembly-title")).toContainText(
        `${step} / ${steps}`,
      );
    }
    await expect(page.locator("#assembly-previous")).toBeEnabled();
    await expect(page.locator("#assembly-previous")).toHaveCSS(
      "cursor",
      "pointer",
    );
    await expect(page.locator("#assembly-next")).toBeEnabled();
    await page.locator("#assembly-next").click();
    await expect(page.locator("#assembly-next")).toBeDisabled();
    await expect(page.locator("#assembly-next")).toHaveCSS(
      "background-color",
      "rgb(217, 224, 229)",
    );
    await page.locator("#assembly-previous").click();
    await expect(page.locator("#assembly-next")).toBeEnabled();
    await page.locator("#assembly-play").click();
    await expect(page.locator("#assembly-play")).toHaveText("播放", {
      timeout: 15000,
    });
    await page.locator("#assembly-play").click();
    await expect(page.locator("#assembly-title")).toContainText(`1 / ${steps}`);
    await expect(page.locator("#assembly-play")).toHaveText("暂停");
    await page.locator("#assembly-play").click();
    await page.locator("#assembly-toggle").click();
    await expect(page.locator("#assembly-panel")).toBeHidden();
    await expect(page.locator("#assembly-controls")).toBeHidden();
    await expect(page.locator("#interaction-hint")).toHaveText(navigationHint);
    await expect(page.locator("#model-info")).toBeVisible();
    await expect(page.locator("#variants")).toBeEnabled();
    await expect(page).not.toHaveURL(/mode=assembly/);
    await page.locator("#assembly-toggle").click();
    expect(await page.locator("#viewport canvas").screenshot()).toEqual(
      initial,
    );
    await page.screenshot({
      path: path.join(repoRoot, `tmp/${model}-assembly-desktop.png`),
    });
    await page.locator('.model[data-id="fidget-button-fdm"]').click();
    await expect(page.locator("#assembly-panel")).toBeHidden();
    await expect(page.locator("#assembly-controls")).toBeHidden();
    await expect(page.locator("#interaction-hint")).toHaveText(navigationHint);
    await expect(page.locator("#model-info")).toBeVisible();
    expect(errors).toEqual([]);
  });
}

test("装配说明直达链接和移动端布局", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/view.html?model=keyboard-fidget-fdm");
  await page.getByRole("link", { name: "打开交互式装配动画" }).click();
  await expect(page.locator("#assembly-panel")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  const viewport = await page.locator("#viewport").boundingBox();
  const panel = await page.locator("#assembly-panel").boundingBox();
  expect(panel!.y).toBeGreaterThanOrEqual(viewport!.y + viewport!.height);
  await expectAssemblyLayout(page);
  await expect(page.locator("#interaction-hint")).toBeHidden();
  await page.locator("#assembly-play").click();
  await expect(page.locator("#assembly-play")).toHaveText("暂停");
  await page.locator("#assembly-play").click();
  await page.screenshot({
    path: path.join(repoRoot, "tmp/keyboard-assembly-mobile.png"),
    fullPage: true,
  });
});

test("动画加载失败时仍可读取说明和下载", async ({ page }) => {
  await page.route("**/assembly.glb?*", (route) =>
    route.fulfill({ status: 404, body: "missing" }),
  );
  await page.goto("/?model=keyboard-fidget-fdm&mode=assembly");
  await expect(page.locator("#status")).toContainText("模型加载失败");
  await expect(page.locator("#assembly-panel")).toBeHidden();
  await expect(page.locator("#assembly-controls")).toBeHidden();
  await expect(page.locator("#interaction-hint")).toHaveText(assemblyHint);
  await expect(page.locator("#model-info")).toBeVisible();
  await expect(page.getByRole("link", { name: "查看模型说明" })).toBeVisible();
  await expect(page.getByRole("link", { name: "下载当前模型" })).toBeVisible();
  await page.locator("#assembly-toggle").click();
  await expect(page.locator("#status")).toBeEmpty();
});

test("WebGL 不可用时装配入口保留说明和下载", async ({ page }) => {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (
      this: HTMLCanvasElement,
      ...args: Parameters<typeof original>
    ) {
      if (String(args[0]).startsWith("webgl")) return null;
      return original.apply(this, args);
    } as typeof original;
  });
  await page.goto("/?model=keyboard-fidget-fdm&mode=assembly");
  await expect(page.locator("#status")).toContainText("WebGL 不可用");
  await expect(page.locator("#assembly-panel")).toBeHidden();
  await expect(page.locator("#assembly-controls")).toBeHidden();
  await expect(page.locator("#interaction-hint")).toHaveText(assemblyHint);
  await expect(page.locator("#model-info")).toBeVisible();
  await expect(page.getByRole("link", { name: "查看模型说明" })).toBeVisible();
  await expect(page.getByRole("link", { name: "下载装配动画" })).toBeVisible();
});

test("XC60 移动端说明入口与动画加载失败回退", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/view.html?model=volvo-xc60-2022");
  await page.getByRole("link", { name: "打开交互式装配动画" }).click();
  await expect(page.locator("#assembly-title")).toContainText("1 / 10");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: path.join(repoRoot, "tmp/xc60-assembly-mobile.png"),
    fullPage: true,
  });
  await page.route("**/assembly.glb?*", (route) =>
    route.fulfill({ status: 404, body: "missing" }),
  );
  await page.reload();
  await expect(page.locator("#status")).toContainText("模型加载失败");
  await expect(page.getByRole("link", { name: "下载装配动画" })).toBeVisible();
  await page.locator("#assembly-toggle").click();
  await expect(page.locator("#status")).toBeEmpty();
});

test("模式缓存复用、变体淘汰和快速切换", async ({ page }) => {
  const requests: string[] = [];
  const errors: string[] = [];
  page.on("request", (request) => {
    if (/\.(stl|glb)\?/.test(request.url())) requests.push(request.url());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/?model=keyboard-fidget-fdm");
  await expect(page.locator("#status")).toBeEmpty();
  const print = requests.find((url) => url.includes("all-parts.stl"))!;
  await page.locator("#assembly-toggle").click();
  await expect(page.locator("#assembly-panel")).toBeVisible();
  const assembly = requests.find((url) => url.includes("assembly.glb"))!;
  const initial = await page.locator("#viewport canvas").screenshot();
  await page.locator("#assembly-next").click();
  await page.locator("#assembly-toggle").click();
  await expect(page.locator("#status")).toBeEmpty();
  await page.locator("#assembly-toggle").click();
  await expect(page.locator("#assembly-title")).toContainText("1 / 5");
  expect(await page.locator("#viewport canvas").screenshot()).toEqual(initial);
  expect(requests.filter((url) => url === print)).toHaveLength(1);
  expect(requests.filter((url) => url === assembly)).toHaveLength(1);
  await page.locator("#assembly-toggle").click();
  await page.locator("#variants").selectOption("shell");
  await expect(page.locator("#status")).toBeEmpty();
  await page.locator("#variants").selectOption("all-parts");
  await expect(page.locator("#status")).toBeEmpty();
  expect(requests.filter((url) => url === print)).toHaveLength(2);
  // Delay an uncached scene so model selection overtakes its load.
  await page.locator('.model[data-id="fidget-button-fdm"]').click();
  await expect(page.locator("#status")).toBeEmpty();
  await page.route("**/assembly.glb?*", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 150));
    await route.continue();
  });
  await page.locator('.model[data-id="keyboard-fidget-fdm"]').click();
  await expect(page.locator("#status")).toBeEmpty();
  await page.locator("#assembly-toggle").click();
  await page.locator('.model[data-id="fidget-button-fdm"]').click();
  await expect(page.locator("#status")).toBeEmpty();
  await expect(page.locator("#assembly-panel")).toBeHidden();
  await page.waitForTimeout(250);
  expect(errors).toEqual([]);
});

test("单帧调度与后台暂停恢复", async ({ page }) => {
  await page.addInitScript(() => {
    const stats = { calls: [] as number[] };
    Object.assign(window, { assemblyFrameStats: stats });
    const original = requestAnimationFrame;
    window.requestAnimationFrame = (callback) =>
      original((time) => {
        stats.calls.push(time);
        callback(time);
      });
  });
  await page.goto("/?model=keyboard-fidget-fdm&mode=assembly");
  await expect(page.locator("#assembly-panel")).toBeVisible();
  await page.evaluate(() => {
    (window as any).assemblyFrameStats.calls = [];
  });
  await page.locator("#assembly-play").click();
  await page.waitForTimeout(350);
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: true,
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  const paused = await page.locator("#viewport canvas").screenshot();
  const frames = await page.evaluate(
    () => (window as any).assemblyFrameStats.calls as number[],
  );
  expect(new Set(frames).size).toBe(frames.length);
  await page.waitForTimeout(250);
  expect(await page.locator("#viewport canvas").screenshot()).toEqual(paused);
  expect(
    await page.evaluate(() => (window as any).assemblyFrameStats.calls.length),
  ).toBe(frames.length);
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: false,
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect
    .poll(() =>
      page.evaluate(() => (window as any).assemblyFrameStats.calls.length),
    )
    .toBeGreaterThan(frames.length);
  await page.locator("#assembly-play").click();
  const stopped = await page.locator("#viewport canvas").screenshot();
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: true,
    });
    document.dispatchEvent(new Event("visibilitychange"));
    Object.defineProperty(document, "hidden", {
      configurable: true,
      value: false,
    });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.waitForTimeout(150);
  expect(await page.locator("#viewport canvas").screenshot()).toEqual(stopped);
  await expect(page.locator("#assembly-play")).toHaveText("播放");
});

for (const orthographic of [false, true]) {
  test(`重置视图恢复方向、大小和居中，保留${orthographic ? "正交" : "透视"}模式与装配步骤`, async ({
    page,
  }) => {
    await page.goto("/?model=keyboard-fidget-fdm&mode=assembly");
    await expect(page.locator("#status")).toBeEmpty();
    await page.locator("#assembly-next").click();
    if (orthographic) await page.locator("#projection").click();
    await page.getByRole("button", { name: "重置视图", exact: true }).click();
    const initial = await page.locator("#viewport canvas").screenshot();
    const bounds = (await page.locator("#viewport canvas").boundingBox())!;
    const x = bounds.x + bounds.width / 2,
      y = bounds.y + bounds.height / 2;
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.mouse.move(x + 70, y + 30, { steps: 5 });
    await page.mouse.up();
    await page.mouse.wheel(0, -300);
    await page.mouse.down({ button: "right" });
    await page.mouse.move(x + 120, y + 60, { steps: 5 });
    await page.mouse.up({ button: "right" });
    await page.waitForTimeout(200);
    expect(await page.locator("#viewport canvas").screenshot()).not.toEqual(
      initial,
    );
    await page.locator("#reset").click();
    expect(await page.locator("#viewport canvas").screenshot()).toEqual(
      initial,
    );
    await expect(page.locator("#projection")).toHaveAttribute(
      "aria-pressed",
      String(orthographic),
    );
    await expect(page.locator("#assembly-title")).toContainText("2 / 5");
    await expect(page.locator("#assembly-play")).toHaveText("播放");
    await page.locator("#assembly-play").click();
    await page.locator("#reset").click();
    await expect(page.locator("#assembly-play")).toHaveText("暂停");
  });
}

test("平板装配控件随右栏排列在视图区下方", async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 900 });
  await page.goto("/?model=keyboard-fidget-fdm&mode=assembly");
  await expect(page.locator("#assembly-panel")).toBeVisible();
  const viewport = (await page.locator("#viewport").boundingBox())!;
  const panel = (await page.locator("#assembly-panel").boundingBox())!;
  expect(panel.y).toBeGreaterThanOrEqual(viewport.y + viewport.height);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await expectAssemblyLayout(page);
  await page.screenshot({
    path: path.join(repoRoot, "tmp/keyboard-assembly-tablet.png"),
    fullPage: true,
  });
});
