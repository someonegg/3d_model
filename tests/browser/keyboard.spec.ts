import { test, expect } from "@playwright/test";

test("新版键盘五件下载与五步装配", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/?model=keyboard-fidget-fdm");
  await expect(page.locator("#status")).toBeEmpty();
  await expect(page.locator("#variants option")).toHaveCount(6);
  await expect(page.locator("#variants")).toContainText("弹性盒");
  await expect(page.locator("#variants")).not.toContainText("锁销");
  for (const file of ["cartridge.stl", "print-files.zip"]) {
    const response = await page.request.get(
      `/models/keyboard-fidget-fdm/${file}`,
    );
    expect(response.ok(), file).toBeTruthy();
    expect((await response.body()).length).toBeGreaterThan(100);
  }
  for (const file of ["return-spring.stl", "click-spring.stl", "lock-pin-1.stl", "lock-pin-2.stl"]) {
    expect(
      (await page.request.get(`/models/keyboard-fidget-fdm/${file}`)).ok(),
    ).toBeFalsy();
  }
  await page.goto("/?model=keyboard-fidget-fdm&mode=assembly");
  await expect(page.locator("#assembly-panel")).toBeVisible();
  for (const title of [
    "弹性盒落座",
    "放入导向柱",
    "罩合外壳",
    "底面拧入螺钉",
    "安装键帽",
  ]) {
    await expect(page.locator("#assembly-title")).toContainText(title);
    if (title !== "安装键帽") await page.locator("#assembly-next").click();
  }
  await page.locator("#assembly-play").click();
  await expect(page.locator("#assembly-play")).toHaveText("暂停");
  expect(errors).toEqual([]);
});
