import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { repoRoot } from "../../tools/runtime.mjs";

test("星链伸缩杖展示状态、打印文件与下载", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/?model=star-chain-fdm&variant=closed");
  await expect(page.locator("#status")).toBeEmpty({ timeout: 60000 });
  await expect(page.locator("canvas")).toBeVisible();
  await expect(page.locator("#variants")).toHaveValue("closed");
  for (const variant of [
    "fit-kit",
    "fit-20",
    "fit-30",
    "fit-40",
    "detent-30",
    "detent-40",
    "detent-50",
  ]) {
    await expect(
      page.locator(`#variants option[value="${variant}"]`),
    ).toHaveCount(0);
  }
  const catalog = await (await page.request.get("/catalog.json")).text();
  expect(catalog).not.toContain("star-chain-joint-test-fdm");
  await page.selectOption("#variants", "extended");
  await expect(page.locator("#status")).toBeEmpty({ timeout: 60000 });
  await page.selectOption("#variants", "all-parts");
  await expect(page.locator("#status")).toBeEmpty({ timeout: 60000 });
  const href = await page
    .getByRole("link", { name: "下载当前模型" })
    .getAttribute("href");
  const response = await page.request.get(href!);
  expect(response.ok()).toBeTruthy();
  expect(
    (await response.body()).equals(
      await readFile(
        path.join(repoRoot, "build/models/star-chain-fdm/all-parts.stl"),
      ),
    ),
  ).toBeTruthy();
  await page.goto("/view.html?model=star-chain-fdm");
  await expect(page.locator("#markdown")).toContainText("无柱收口槽");
  await expect(page.locator("#markdown")).toContainText("实心宽头");
  await expect(page.locator("#markdown")).toContainText("凹窝朝上");
  await expect(page.locator("#markdown")).toContainText("每节长 29 mm");
  await expect(page.locator("#markdown")).toContainText("230 mm");
  await expect(page.locator("#markdown")).toContainText("285 mm");
  await expect(page.locator("#markdown")).toContainText("壳体厚 10.0 mm");
  await expect(page.locator("#markdown")).toContainText(
    "detent_interference_mm",
  );
  await expect(page.locator("#markdown")).toContainText("须使用同次生成的配套文件");
  await expect(page.locator("#markdown")).toContainText("保持力和寿命待实物验证");
  await expect(page.locator("#markdown")).not.toContainText("29 件");
  await expect(page.locator("#markdown")).not.toContainText("试配件");
  for (const file of ["print-files.zip"]) {
    const response = await page.request.get(`/models/star-chain-fdm/${file}`);
    expect(response.ok()).toBeTruthy();
    expect(
      (await response.body()).equals(
        await readFile(
          path.join(repoRoot, "build/models/star-chain-fdm", file),
        ),
      ),
    ).toBeTruthy();
  }
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  expect(errors).toEqual([]);
});
