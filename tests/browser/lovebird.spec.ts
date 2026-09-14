import { test, expect } from "@playwright/test";

test("牡丹鹦鹉书签展示与下载", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/?model=bookmark-lovebird-fdm&variant=bookmark");
  await expect(page.locator("#status")).toBeEmpty({ timeout: 60000 });
  await expect(page.locator("canvas")).toBeVisible();
  await expect(page.locator("#metrics")).toContainText("45.00 × 150.00 × 1.32");
  await expect(page.locator("#variants")).toHaveValue("bookmark");
  const href = await page
    .getByRole("link", { name: "下载当前模型" })
    .getAttribute("href");
  expect(href).toContain("bookmark-lovebird-fdm.stl");
  const response = await page.request.get(href!);
  expect(response.ok()).toBeTruthy();
  expect((await response.body()).length).toBeGreaterThan(1000000);
  const preview = await page.request.get(
    "/models/bookmark-lovebird-fdm/preview.png",
  );
  expect(preview.ok()).toBeTruthy();
  await page.getByRole("button", { name: "下 / 背面" }).click();
  await expect(page.locator("#status")).toBeEmpty();
  expect(errors).toEqual([]);
});
