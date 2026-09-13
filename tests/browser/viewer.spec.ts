import { test, expect } from "@playwright/test";
import path from "node:path";
import { repoRoot } from "../../tools/runtime.mjs";
test("浏览硬币、切换视角与变体、保留选择", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/?model=coin-sacagawea-fdm&variant=obverse");
  await expect(page.locator("#status")).toBeEmpty({ timeout: 60000 });
  await expect(page.locator("canvas")).toBeVisible();
  await expect(page.locator("#metrics")).toContainText("60.00 × 60.00");
  await page
    .getByRole("button", { name: "萨卡加维亚硬币", exact: true })
    .click();
  await page.selectOption("#variants", "double-sided");
  await expect(page.locator("#status")).toBeEmpty({ timeout: 60000 });
  await expect(page.locator("#metrics")).toContainText("60.00 × 60.00 × 6.40");
  const canvas = page.locator("canvas");
  const pixels = () => canvas.screenshot();
  const settle = () =>
    page.evaluate(
      () =>
        new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        ),
    );
  const initial = await pixels();
  await page.getByRole("button", { name: "下 / 背面" }).click();
  await settle();
  const reverse = await pixels();
  expect(reverse.equals(initial)).toBeFalsy();
  await page.getByRole("button", { name: "正交视图" }).click();
  await expect(page.locator("#projection")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await settle();
  const orthographic = await pixels();
  expect(orthographic.equals(reverse)).toBeFalsy();
  await page.check("#wire");
  await settle();
  expect((await pixels()).equals(orthographic)).toBeFalsy();
  await page.uncheck("#wire");
  await page.reload();
  await expect(page.locator("#variants")).toHaveValue("double-sided");
  await expect(page.locator("#status")).toBeEmpty({ timeout: 60000 });
  const download = await page.request.get(
    (await page
      .getByRole("link", { name: "下载当前模型" })
      .getAttribute("href")) as string,
  );
  expect(download.ok()).toBeTruthy();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  expect(errors).toEqual([]);
});
test("加载失败仍可下载", async ({ page }) => {
  await page.route("**/*.stl?*", (route) => route.abort());
  await page.goto("/");
  await expect(page.locator("#status")).toContainText("模型加载失败");
  await expect(page.getByRole("link", { name: "下载当前模型" })).toBeVisible();
});
test("GLB 与外部 glTF 资源", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const model = {
    id: "fixture",
    name: "纹理测试",
    description: "GLB/glTF",
    purpose: "display",
    units: "m",
    up: "Y",
    base: "fixtures/",
    preview: "preview.png",
    readme: "README.md",

    variants: [
      { id: "glb", name: "GLB", file: "model.glb" },
      { id: "gltf", name: "glTF", file: "model.gltf" },
    ],
    revisions: { "model.glb": "1", "model.gltf": "1" },
    validation: null,
  };
  await page.route("**/catalog.json", (route) =>
    route.fulfill({ json: [model] }),
  );
  await page.route("**/fixtures/**", async (route) => {
    const name = new URL(route.request().url()).pathname.split("/").pop();
    if (!name || name === "preview.png") return route.fulfill({ status: 404 });
    return route.fulfill({
      path: path.join(repoRoot, "tmp/fixtures/assets", name),
    });
  });
  await page.goto("/");
  await expect(page.locator("#status")).toBeEmpty({ timeout: 30000 });
  await page.selectOption("#variants", "gltf");
  await expect(page.locator("#status")).toBeEmpty({ timeout: 30000 });
  expect(errors).toEqual([]);
});
test("子目录静态资源与分享链接", async ({ page }) => {
  await page.route("**/nested/**", async (route) => {
    const url = new URL(route.request().url());
    let name = url.pathname.slice("/nested/".length) || "index.html";
    const types: Record<string, string> = {
      html: "text/html",
      js: "text/javascript",
      css: "text/css",
      json: "application/json",
    };
    await route.fulfill({
      path: `dist/${name}`,
      contentType: types[name.split(".").pop()!] ?? "application/octet-stream",
    });
  });
  await page.goto("/nested/?model=coin-sacagawea&variant=reverse");
  await expect(page.locator("#status")).toBeEmpty({ timeout: 60000 });
  await expect(page.locator("#variants")).toHaveValue("reverse");
  await expect(
    page.getByRole("link", { name: "下载当前模型" }),
  ).toHaveAttribute("href", /^\.\/models\//);
});
