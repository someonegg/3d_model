import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { repoRoot } from "../../tools/runtime.mjs";

test("伸缩手里剑展示、打印件与下载", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/?model=retractable-shuriken-fdm");
  await expect(page.locator("#status")).toBeEmpty();
  await expect(page.locator("#variants")).toHaveValue("expanded");
  await expect(page.locator("#viewport canvas")).toBeVisible();
  for (const variant of ["closed", "wing", "all-parts"]) {
    await page.selectOption("#variants", variant);
    await expect(page.locator("#status")).toBeEmpty();
  }
  const href = await page
    .getByRole("link", { name: "下载当前模型" })
    .getAttribute("href");
  const downloaded = await page.request.get(href!);
  expect(downloaded.ok()).toBeTruthy();
  expect(
    (await downloaded.body()).equals(
      await readFile(
        path.join(
          repoRoot,
          "build/models/retractable-shuriken-fdm/all-parts.stl",
        ),
      ),
    ),
  ).toBeTruthy();
  await page.goto("/view.html?model=retractable-shuriken-fdm");
  await expect(page.locator("#markdown")).toContainText("待实物验证");
  await expect(page.locator("#markdown")).toContainText("72 / 102 mm");
  for (const file of ["print-files.zip", "assembly.glb"]) {
    const response = await page.request.get(
      `/models/retractable-shuriken-fdm/${file}`,
    );
    expect(response.ok()).toBeTruthy();
    expect(
      (await response.body()).equals(
        await readFile(
          path.join(repoRoot, "build/models/retractable-shuriken-fdm", file),
        ),
      ),
    ).toBeTruthy();
  }
  await page.getByRole("link", { name: "打开交互式装配动画" }).click();
  await expect(page.locator("#assembly-title")).toContainText("1 / 4");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: path.join(repoRoot, "tmp/retractable-shuriken-mobile.png"),
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
