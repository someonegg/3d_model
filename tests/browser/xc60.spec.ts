import { test, expect } from "@playwright/test";

test("XC60 装配状态、打印排版与整套下载", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/?model=volvo-xc60-2022-display&variant=closed");
  await expect(page.locator("#status")).toBeEmpty();
  await expect(page.locator("canvas")).toBeVisible();
  const closed = await page.locator("canvas").screenshot();
  await page.selectOption("#variants", "open");
  await expect(page.locator("#status")).toBeEmpty();
  await expect(
    page.getByRole("link", { name: "下载当前模型" }),
  ).toHaveAttribute("href", /doors-open\.glb/);
  const opened = await page.locator("canvas").screenshot();
  expect(opened.equals(closed)).toBeFalsy();

  await page.goto("/?model=volvo-xc60-2022&variant=fit-coupon");
  await expect(page.locator("#status")).toBeEmpty();
  await expect(page.locator("#variants")).toHaveValue("fit-coupon");
  await page.selectOption("#variants", "plate-white-1");
  await expect(page.locator("#status")).toBeEmpty();
  const bundle = await page.request.get(
    "/models/volvo-xc60-2022/print-files.zip",
  );
  expect(bundle.ok()).toBeTruthy();
  expect((await bundle.body()).subarray(0, 2).toString()).toBe("PK");
  const report = await page.request.get(
    "/models/volvo-xc60-2022/detail-validation.json",
  );
  expect((await report.json()).passed).toBe(true);

  await page.goto("/view.html?model=volvo-xc60-2022");
  await expect(
    page.getByRole("link", { name: "整套打印文件 ZIP" }),
  ).toHaveAttribute("href", /\/models\/volvo-xc60-2022\/print-files\.zip$/);
  expect(errors).toEqual([]);
});
