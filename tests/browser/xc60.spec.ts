import { test, expect } from "@playwright/test";

test("XC60 装配状态、打印排版与整套下载", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/?model=volvo-xc60-2022");
  await expect(page.locator("#variants")).toHaveValue("closed");
  const catalog = await (await page.request.get("/catalog.json")).json();
  expect(
    catalog
      .filter((model: { id: string }) => model.id.startsWith("volvo-xc60-2022"))
      .map((model: { id: string }) => model.id),
  ).toEqual(["volvo-xc60-2022"]);
  await expect(page.locator("#metrics")).toContainText("展示");
  await expect(page.locator("#metrics")).toContainText(" m");
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
  await expect(page.locator("#metrics")).toContainText("3D 打印");
  await expect(page.locator("#metrics")).toContainText(" mm");
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
  expect(report.ok()).toBeFalsy();

  await page.goto("/view.html?model=volvo-xc60-2022");
  await expect(
    page.getByRole("link", { name: "整套打印文件 ZIP" }),
  ).toHaveAttribute("href", /\/models\/volvo-xc60-2022\/print-files\.zip$/);
  expect(errors).toEqual([]);
});

test("键盘整套下载及 Volvo 发布参考说明", async ({ page }) => {
  await page.goto("/view.html?model=keyboard-fidget-fdm");
  await expect(page.locator("#reader-status")).toBeEmpty();
  await expect(
    page.getByRole("link", {
      name: "下载全部打印文件、装配动画、预览、爆炸图和说明",
    }),
  ).toHaveAttribute("href", /\/models\/keyboard-fidget-fdm\/print-files\.zip$/);
  const bundle = await page.request.get(
    "/models/keyboard-fidget-fdm/print-files.zip",
  );
  expect(bundle.ok()).toBeTruthy();
  expect((await bundle.body()).subarray(0, 2).toString()).toBe("PK");
  const notes = await page.request.get("/models/volvo-xc60-2022/references.md");
  expect(notes.ok()).toBeTruthy();
  expect(await notes.text()).toContain("Volvo");
  for (const id of ["keyboard-fidget-fdm", "volvo-xc60-2022"]) {
    const report = await page.request.get(
      `/models/${id}/packaging-validation.json`,
    );
    expect(report.ok()).toBeFalsy();
  }
});
