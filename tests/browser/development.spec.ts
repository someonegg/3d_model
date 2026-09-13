import { test, expect } from "@playwright/test";
import { mkdtemp, copyFile, writeFile, rm } from "node:fs/promises";
import path from "node:path";
import { repoRoot, runPython } from "../../tools/runtime.mjs";

test("本地自动发现、校验过期与移除", async ({ page }) => {
  const directory = await mkdtemp(
    path.join(repoRoot, "tmp/fixtures/models/viewer-test-"),
  );
  const id = path.basename(directory);
  try {
    await copyFile(
      path.join(repoRoot, "tmp/fixtures/assets/model.glb"),
      path.join(directory, "model.glb"),
    );
    await copyFile(
      path.join(repoRoot, "tmp/fixtures/assets/texture.png"),
      path.join(directory, "preview.png"),
    );
    await writeFile(path.join(directory, "README.md"), "# 测试模型");
    const model = {
      id,
      name: "开发测试模型",
      description: "热更新测试",
      purpose: "display",
      units: "m",
      up: "Y",
      variants: [{ id: "main", name: "初始版本", file: "model.glb" }],
      preview: "preview.png",
      readme: "README.md",
      artifacts: ["details.json"],
    };
    await writeFile(
      path.join(directory, "details.json"),
      JSON.stringify({ passed: true }),
    );
    await writeFile(path.join(directory, "model.json"), JSON.stringify(model));
    await runPython([
      "tools/models.py",
      "validate",
      id,
      "--root",
      path.join(repoRoot, "tmp/fixtures/models"),
    ]);
    await page.goto(`http://127.0.0.1:5273/?model=${id}`);
    await expect(page.locator("#status")).toBeEmpty({ timeout: 30000 });
    await expect(page.locator("#validation")).toContainText("校验通过");
    const details = await page.request.get(
      `http://127.0.0.1:5273/models/${id}/details.json`,
    );
    expect(details.ok()).toBeTruthy();
    expect(await details.json()).toEqual({ passed: true });
    expect(
      (
        await page.request.get(`http://127.0.0.1:5273/models/${id}/model.json`)
      ).status(),
    ).toBe(404);
    await page.getByRole("button", { name: "上 / 正面" }).click();
    model.variants[0].name = "更新版本";
    await writeFile(path.join(directory, "model.json"), JSON.stringify(model));
    await expect(page.locator("#variants")).toContainText("更新版本");
    await expect(page.locator("#validation")).toContainText("校验通过");
    await writeFile(
      path.join(directory, "details.json"),
      JSON.stringify({ passed: false }),
    );
    await expect(page.locator("#validation")).toContainText("待重新校验");
    await expect(page.locator("#status")).toBeEmpty();
    await expect(page.locator("#metrics")).toContainText("1.00 × 2.00 × 3.00");
    // Build swaps the whole directory; watching must survive both swaps.
    await copyFile(
      path.join(directory, "model.glb"),
      path.join(directory, "source.glb"),
    );
    await copyFile(
      path.join(directory, "preview.png"),
      path.join(directory, "source.png"),
    );
    const script = `from pathlib import Path
import os, shutil
source = Path(__file__).resolve().parent
output = Path(os.environ["MODEL_OUTPUT_DIR"])
for src, dst in [("source.glb", "model.glb"), ("source.png", "preview.png"), ("details.json", "details.json")]:
    shutil.copy2(source / src, output / dst)
`;
    await writeFile(path.join(directory, "build.py"), script);
    await writeFile(
      path.join(directory, "model.json"),
      JSON.stringify({
        ...model,
        build: "build.py",
        inputs: ["build.py", "source.glb", "source.png"],
      }),
    );
    await runPython([
      "tools/models.py",
      "build",
      id,
      "--root",
      path.join(repoRoot, "tmp/fixtures/models"),
    ]);
    await expect(page.locator("#validation")).toContainText("校验通过");
    await writeFile(
      path.join(directory, "build.py"),
      script + "\n# changed input\n",
    );
    await expect(page.locator("#validation")).toContainText("待重新校验");
    await runPython([
      "tools/models.py",
      "build",
      id,
      "--root",
      path.join(repoRoot, "tmp/fixtures/models"),
    ]);
    await expect(page.locator("#validation")).toContainText("校验通过");
    await rm(directory, { recursive: true, force: true });
    await expect(
      page.getByRole("button", { name: "开发测试模型" }),
    ).toHaveCount(0);
    await expect(page.locator("#status")).toContainText("模型库为空");
    await expect(page.locator("#title")).toBeEmpty();
    await expect(page.locator("#metrics")).toBeEmpty();
    await expect(page.locator("#downloads a")).toHaveCount(0);
    await expect(page.locator("#variants option")).toHaveCount(0);
    await expect(page.locator("#variants")).toBeDisabled();
    expect(new URL(page.url()).searchParams.has("model")).toBeFalsy();
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});
