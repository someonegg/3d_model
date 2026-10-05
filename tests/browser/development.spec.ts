import { test, expect } from "@playwright/test";
import {
  mkdtemp,
  mkdir,
  copyFile,
  writeFile,
  readFile,
  rm,
} from "node:fs/promises";
import path from "node:path";
import { repoRoot, runPython } from "../../tools/runtime.mjs";

test("本地自动发现、校验过期与移除", async ({ page }) => {
  await page.goto("http://127.0.0.1:5273/");
  await expect(page.locator("#status")).toContainText("模型库为空");
  const directory = await mkdtemp(
    path.join(repoRoot, "tmp/fixtures/models/viewer-test-"),
  );
  const id = path.basename(directory);
  const sceneRequests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === `/models/${id}/model.glb`)
      sceneRequests.push(request.url());
  });
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
    await writeFile(path.join(directory, "notes.md"), "独立说明");
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
      publish: [{ from: "source", path: "notes.md" }],
      build: "build.py",
      inputs: ["build.py", "details.json", "model.glb", "preview.png"],
    };
    await writeFile(
      path.join(directory, "details.json"),
      JSON.stringify({ passed: true }),
    );
    await writeFile(
      path.join(directory, "build.py"),
      `import os, shutil
from pathlib import Path
out = Path(os.environ["MODEL_OUTPUT_DIR"])
for name in ["model.glb", "preview.png", "details.json"]:
    shutil.copy2(name, out / name)
`,
    );
    await writeFile(path.join(directory, "model.json"), JSON.stringify(model));
    await expect(
      page.getByRole("button", { name: "开发测试模型" }),
    ).toHaveCount(1);
    await expect(page.locator("#status")).toContainText("build");
    await expect(page.locator("#validation")).toContainText("build");
    await runPython([
      "tools/models.py",
      "build",
      id,
      "--library-root",
      path.join(repoRoot, "tmp/fixtures"),
    ]);
    await expect(page.locator("#status")).toBeEmpty({ timeout: 30000 });
    await expect(page.locator("#validation")).toContainText("校验通过");
    const details = await page.request.get(
      `http://127.0.0.1:5273/models/${id}/details.json`,
    );
    expect(details.status()).toBe(404);
    expect(
      (
        await page.request.get(`http://127.0.0.1:5273/models/${id}/model.json`)
      ).status(),
    ).toBe(404);
    const output = path.join(repoRoot, "tmp/fixtures/build/models", id);
    const geometry = await readFile(path.join(output, "validation.json"));
    await writeFile(path.join(directory, "README.md"), "# 更新说明");
    await writeFile(path.join(directory, "notes.md"), "更新独立说明");
    await expect(page.locator("#validation")).toContainText("待重新校验");
    const previousReadme = await page.request.get(
      `http://127.0.0.1:5273/models/${id}/README.md`,
    );
    expect(await previousReadme.text()).toBe("# 测试模型");
    await runPython([
      "tools/models.py",
      "build",
      id,
      "--library-root",
      path.join(repoRoot, "tmp/fixtures"),
    ]);
    await expect(page.locator("#validation")).toContainText("校验通过");
    expect(
      (await readFile(path.join(output, "validation.json"))).equals(geometry),
    ).toBeTruthy();
    for (const [name, text] of [
      ["README.md", "# 更新说明"],
      ["notes.md", "更新独立说明"],
    ]) {
      const response = await page.request.get(
        `http://127.0.0.1:5273/models/${id}/${name}`,
      );
      expect(await response.text()).toBe(text);
    }
    await page.getByRole("button", { name: "上 / 正面" }).click();
    model.variants[0].name = "更新版本";
    await writeFile(path.join(directory, "model.json"), JSON.stringify(model));
    await expect(page.locator("#variants")).toContainText("更新版本");
    await expect(page.locator("#validation")).toContainText("待重新校验");
    await writeFile(
      path.join(directory, "details.json"),
      JSON.stringify({ passed: false }),
    );
    await expect(page.locator("#validation")).toContainText("待重新校验");
    await expect(page.locator("#status")).toBeEmpty();
    await expect(page.locator("#metrics")).toContainText("1.00 × 2.00 × 3.00");
    // Source/manifest changes expire validation without reparsing unchanged geometry.
    expect(sceneRequests).toHaveLength(1);
    // Rebuilding replaces only the output directory.
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
source = Path(__file__).resolve().parents[1]
output = Path(os.environ["MODEL_OUTPUT_DIR"])
for src, dst in [("source.glb", "model.glb"), ("source.png", "preview.png"), ("details.json", "details.json")]:
    shutil.copy2(source / src, output / dst)
`;
    await mkdir(path.join(directory, "src"));
    await mkdir(path.join(repoRoot, "tmp/fixtures/tools"), { recursive: true });
    await writeFile(
      path.join(repoRoot, `tmp/fixtures/tools/${id}.py`),
      "# shared input\n",
    );
    await writeFile(path.join(directory, "src/build.py"), script);
    await writeFile(
      path.join(directory, "model.json"),
      JSON.stringify({
        ...model,
        build: "src/build.py",
        inputs: [
          "src/build.py",
          "source.glb",
          "source.png",
          `../../tools/${id}.py`,
        ],
      }),
    );
    await runPython([
      "tools/models.py",
      "build",
      id,
      "--library-root",
      path.join(repoRoot, "tmp/fixtures"),
    ]);
    await expect(page.locator("#validation")).toContainText("校验通过");
    await writeFile(
      path.join(repoRoot, `tmp/fixtures/tools/${id}.py`),
      "# changed shared input\n",
    );
    await expect(page.locator("#validation")).toContainText("待重新校验");
    await runPython([
      "tools/models.py",
      "build",
      id,
      "--library-root",
      path.join(repoRoot, "tmp/fixtures"),
    ]);
    await expect(page.locator("#validation")).toContainText("校验通过");
    expect(sceneRequests).toHaveLength(1);
    // A rebuilt asset with a new revision must evict and replace the cached scene.
    await runPython([
      "-c",
      "import sys, trimesh; trimesh.Scene(trimesh.creation.box(extents=[2, 3, 4])).export(sys.argv[1])",
      path.join(directory, "source.glb"),
    ]);
    await runPython([
      "tools/models.py",
      "build",
      id,
      "--library-root",
      path.join(repoRoot, "tmp/fixtures"),
    ]);
    await expect(page.locator("#validation")).toContainText("校验通过");
    await expect(page.locator("#metrics")).toContainText("2.00 × 3.00 × 4.00");
    await expect(page.locator("#status")).toBeEmpty();
    expect(sceneRequests).toHaveLength(2);
    expect(sceneRequests[1]).not.toBe(sceneRequests[0]);
    // Editing an independent manual script must not refresh the model library.
    await page.waitForTimeout(1000);
    let catalogRequests = 0;
    const countCatalog = (request: { url(): string }) => {
      if (new URL(request.url()).pathname === "/catalog.json")
        catalogRequests++;
    };
    page.on("request", countCatalog);
    await writeFile(
      path.join(directory, "src/slice.py"),
      "raise RuntimeError('manual audit only')\n",
    );
    await page.waitForTimeout(1200);
    page.off("request", countCatalog);
    expect(catalogRequests).toBe(0);
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
    await rm(path.join(repoRoot, `tmp/fixtures/tools/${id}.py`), {
      force: true,
    });
    await rm(directory, { recursive: true, force: true });
  }
});

test("混合展示与打印变体共享输入过期状态", async ({ page }) => {
  const directory = await mkdtemp(
    path.join(repoRoot, "tmp/fixtures/models/mixed-test-"),
  );
  const id = path.basename(directory);
  const build = () =>
    runPython([
      "tools/models.py",
      "build",
      id,
      "--library-root",
      path.join(repoRoot, "tmp/fixtures"),
    ]);
  try {
    await copyFile(
      path.join(repoRoot, "tmp/fixtures/assets/texture.png"),
      path.join(directory, "preview.png"),
    );
    await writeFile(path.join(directory, "README.md"), "# 混合模型");
    await writeFile(path.join(directory, "parameters.json"), "{}");
    await writeFile(
      path.join(directory, "build.py"),
      `import os, shutil, trimesh
from pathlib import Path
out = Path(os.environ['MODEL_OUTPUT_DIR'])
mesh = trimesh.creation.box(extents=[100, 200, 300])
mesh.export(out / 'print.stl')
mesh.apply_scale(.001)
trimesh.Scene(mesh).export(out / 'assembly.glb')
shutil.copy2('preview.png', out / 'preview.png')
`,
    );
    await writeFile(
      path.join(directory, "model.json"),
      JSON.stringify({
        id,
        name: "混合测试模型",
        description: "统一校验",
        purpose: "print",
        units: "mm",
        up: "Z",
        variants: [
          {
            id: "closed",
            name: "装配展示",
            file: "assembly.glb",
            purpose: "display",
            units: "m",
            up: "Y",
          },
          { id: "print", name: "打印零件", file: "print.stl" },
        ],
        preview: "preview.png",
        readme: "README.md",
        build: "build.py",
        inputs: ["build.py", "parameters.json", "preview.png"],
      }),
    );
    await build();
    await page.goto(`http://127.0.0.1:5273/?model=${id}`);
    await expect(page.locator("#status")).toBeEmpty();
    await expect(page.locator("#variants")).toHaveValue("closed");
    await expect(page.locator("#metrics")).toContainText(
      "0.10 × 0.20 × 0.30 m",
    );
    await expect(page.locator("#validation")).toContainText("校验通过");
    await writeFile(
      path.join(directory, "parameters.json"),
      '{"changed":true}',
    );
    await expect(page.locator("#validation")).toContainText("待重新校验");
    await page.selectOption("#variants", "print");
    await expect(page.locator("#status")).toBeEmpty();
    await expect(page.locator("#validation")).toContainText("待重新校验");
    await expect(page.locator("#metrics")).toContainText(
      "100.00 × 200.00 × 300.00 mm",
    );
    await build();
    await expect(page.locator("#validation")).toContainText("校验通过");
    await page.selectOption("#variants", "closed");
    await expect(page.locator("#status")).toBeEmpty();
    await expect(page.locator("#validation")).toContainText("校验通过");
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
});

test("打包说明热更新只更新下载包与发布说明", async ({ page }) => {
  const directory = await mkdtemp(
    path.join(repoRoot, "tmp/fixtures/models/bundle-test-"),
  );
  const id = path.basename(directory);
  const output = path.join(repoRoot, "tmp/fixtures/build/models", id);
  try {
    for (const [source, target] of [
      ["model.glb", "model.glb"],
      ["texture.png", "preview.png"],
    ]) {
      await copyFile(
        path.join(repoRoot, "tmp/fixtures/assets", source),
        path.join(directory, target),
      );
    }
    await writeFile(
      path.join(directory, "README.md"),
      "# 下载\n[整套下载](print-files.zip)\n[参考说明](notes.md)",
    );
    await writeFile(path.join(directory, "notes.md"), "初始参考说明");
    await writeFile(
      path.join(directory, "build.py"),
      `import os, shutil
from pathlib import Path
out = Path(os.environ["MODEL_OUTPUT_DIR"])
for name in ["model.glb", "preview.png"]:
    shutil.copy2(name, out / name)
`,
    );
    const bundle = {
      file: "print-files.zip",
      files: [
        { from: "output", path: "model.glb" },
        { from: "source", path: "README.md" },
        { from: "source", path: "notes.md" },
      ],
    };
    await writeFile(
      path.join(directory, "bundle.json"),
      JSON.stringify(bundle),
    );
    await writeFile(
      path.join(directory, "model.json"),
      JSON.stringify({
        id,
        name: "打包测试",
        description: "说明热更新",
        purpose: "display",
        units: "m",
        up: "Y",
        variants: [{ id: "main", name: "模型", file: "model.glb" }],
        preview: "preview.png",
        readme: "README.md",
        build: "build.py",
        inputs: ["build.py", "model.glb", "preview.png"],
        bundle: "bundle.json",
        publish: ["print-files.zip", { from: "source", path: "notes.md" }],
      }),
    );
    const rebuild = () =>
      runPython([
        "tools/models.py",
        "build",
        id,
        "--library-root",
        path.join(repoRoot, "tmp/fixtures"),
      ]);
    await rebuild();
    const geometry = await readFile(path.join(output, "validation.json"));
    await page.goto(`http://127.0.0.1:5273/?model=${id}`);
    await expect(page.locator("#validation")).toContainText("校验通过");
    await writeFile(path.join(directory, "notes.md"), "更新后的参考说明");
    await expect(page.locator("#validation")).toContainText("待重新校验");
    await rebuild();
    await expect(page.locator("#validation")).toContainText("校验通过");
    expect(
      (await readFile(path.join(output, "validation.json"))).equals(geometry),
    ).toBeTruthy();
    const notes = await page.request.get(
      `http://127.0.0.1:5273/models/${id}/notes.md`,
    );
    expect(await notes.text()).toBe("更新后的参考说明");
    bundle.files.reverse();
    await writeFile(
      path.join(directory, "bundle.json"),
      JSON.stringify(bundle),
    );
    await expect(page.locator("#validation")).toContainText("待重新校验");
    await rebuild();
    await expect(page.locator("#validation")).toContainText("校验通过");
    expect(
      (await readFile(path.join(output, "validation.json"))).equals(geometry),
    ).toBeTruthy();
  } finally {
    await rm(directory, { recursive: true, force: true });
    await rm(output, { recursive: true, force: true });
  }
});
