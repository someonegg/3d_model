import { test, expect } from "@playwright/test";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { repoRoot } from "../../tools/runtime.mjs";

test("全部模型说明、预览、移动端布局和发布边界", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const modelsRoot = path.join(repoRoot, "models");
  const entries = await readdir(modelsRoot, { withFileTypes: true });
  const expectedIds: string[] = [];
  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name.startsWith(".")) continue;
    const directory = path.join(modelsRoot, entry.name);
    if (!(await readdir(directory)).includes("model.json")) continue;
    const manifest = JSON.parse(
      await readFile(path.join(directory, "model.json"), "utf8"),
    ) as { id: string };
    expectedIds.push(manifest.id);
  }
  expect(expectedIds.length).toBeGreaterThan(0);
  const response = await page.request.get("/catalog.json");
  expect(response.ok()).toBe(true);
  const models = (await response.json()) as {
    id: string;
    base: string;
    assets: string[];
    preview: string;
    assembly?: string;
  }[];
  expect(models.map((model) => model.id).sort()).toEqual(expectedIds.sort());
  for (const model of models) {
    expect(model.base).toBe(`models/${model.id}/`);
    expect(model.assets.some((name) => /^(src|references)\//.test(name))).toBe(
      false,
    );
    expect(model.assets).toContain(model.preview);
    expect(
      model.assets.some((name) =>
        /(?:validation|assembly|parameters|model)\.json$/.test(name),
      ),
    ).toBe(false);
    expect(model).not.toHaveProperty("inputs");
    expect(model).not.toHaveProperty("build");
    expect(model).not.toHaveProperty("artifacts");
    const preview = await page.request.get(`/${model.base}${model.preview}`);
    expect(preview.ok()).toBeTruthy();
    await page.goto(`/view.html?model=${model.id}`);
    await expect(page.locator("#markdown")).toBeVisible();
    await expect(page.locator("#reader-status")).toBeEmpty();
    await expect(page.locator("#markdown")).toContainText("核心参数");
    if (model.id !== "volvo-xc60-2022") {
      expect(model.assets.some((name) => /fit-(coupon|kit)/.test(name))).toBe(
        false,
      );
      await expect(page.locator("#markdown")).not.toContainText("配合试片");
      await expect(page.locator("#markdown")).not.toContainText("试配件");
    } else {
      expect(model.assets).toContain("fit-coupon.stl");
      await expect(page.locator("#markdown")).toContainText("先打印配合件");
    }
    await expect
      .poll(() =>
        page.locator("#markdown img").evaluateAll((images) =>
          images.every((image) => {
            const img = image as HTMLImageElement;
            return img.complete && img.naturalWidth > 0;
          }),
        ),
      )
      .toBe(true);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      `${model.id}: mobile layout`,
    ).toBeTruthy();
    const links = await page.locator("#markdown a").evaluateAll((anchors) =>
      anchors
        .map((anchor) => new URL((anchor as HTMLAnchorElement).href))
        .filter((url) => url.origin === location.origin)
        .map((url) => ({
          path: decodeURIComponent(url.pathname),
          model: url.searchParams.get("model"),
          mode: url.searchParams.get("mode"),
        })),
    );
    for (const entry of links) {
      const link = entry.path;
      if (link === "/index.html") {
        expect(model.assembly).toBeTruthy();
        expect(entry.model).toBe(model.id);
        expect(entry.mode).toBe("assembly");
        continue;
      }
      expect(link.startsWith(`/${model.base}`)).toBe(true);
      expect(model.assets).toContain(link.slice(model.base.length + 1));
    }
    const privateSource = await page.request.get(`/${model.base}src/build.py`);
    expect(privateSource.status()).toBe(404);
  }
});
