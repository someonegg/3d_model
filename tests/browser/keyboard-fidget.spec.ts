import { test, expect } from "@playwright/test";

test("键盘解压器配合试片切换与下载", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/?model=keyboard-fidget-fdm&variant=all-parts");
  await expect(page.locator("#status")).toBeEmpty();
  await page.selectOption("#variants", "fit-coupon");
  await expect(page.locator("#status")).toBeEmpty();
  const link = page.getByRole("link", { name: "下载当前模型" });
  await expect(link).toHaveAttribute("href", /fit-coupon\.stl/);
  const response = await page.request.get((await link.getAttribute("href"))!);
  expect(response.ok()).toBeTruthy();
  expect(errors).toEqual([]);
});
