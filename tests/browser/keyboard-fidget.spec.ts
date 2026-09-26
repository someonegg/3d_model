import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { repoRoot } from "../../tools/runtime.mjs";

test("键盘解压器配合试片与底盖切换和下载", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/?model=keyboard-fidget-fdm&variant=all-parts");
  await expect(page.locator("#status")).toBeEmpty();
  for (const variant of ["fit-coupon", "base"]) {
    await page.selectOption("#variants", variant);
    await expect(page.locator("#status")).toBeEmpty();
    const link = page.getByRole("link", { name: "下载当前模型" });
    await expect(link).toHaveAttribute("href", new RegExp(`${variant}\\.stl$`));
    const response = await page.request.get((await link.getAttribute("href"))!);
    expect(response.ok()).toBeTruthy();
    const source = await readFile(
      path.join(repoRoot, "models/keyboard-fidget-fdm", `${variant}.stl`),
    );
    expect((await response.body()).equals(source)).toBeTruthy();
  }
  expect(errors).toEqual([]);
});
