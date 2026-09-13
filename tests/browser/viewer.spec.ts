import { test, expect } from "@playwright/test";
import path from "node:path";
import { repoRoot } from "../../tools/runtime.mjs";
test("浏览硬币、切换视角与变体、保留选择", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/?model=coin-sacagawea-fdm&variant=obverse");
  await expect(page.locator("#status")).toBeEmpty({ timeout: 60000 });
  await expect(page.locator("canvas")).toBeVisible();
  await expect(page.locator("#metrics")).toContainText("60.00 × 60.00");
  await page
    .getByRole("button", { name: "萨卡加维亚硬币", exact: true })
    .click();
  await page.selectOption("#variants", "double-sided");
  await expect(page.locator("#status")).toBeEmpty({ timeout: 60000 });
  await expect(page.locator("#metrics")).toContainText("60.00 × 60.00 × 6.40");
  const canvas = page.locator("canvas");
  const pixels = () => canvas.screenshot();
  const settle = () =>
    page.evaluate(
      () =>
        new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        ),
    );
  const initial = await pixels();
  await page.getByRole("button", { name: "下 / 背面" }).click();
  await settle();
  const reverse = await pixels();
  expect(reverse.equals(initial)).toBeFalsy();
  await page.getByRole("button", { name: "正交视图" }).click();
  await expect(page.locator("#projection")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await settle();
  const orthographic = await pixels();
  expect(orthographic.equals(reverse)).toBeFalsy();
  await page.check("#wire");
  await settle();
  expect((await pixels()).equals(orthographic)).toBeFalsy();
  await page.uncheck("#wire");
  await page.reload();
  await expect(page.locator("#variants")).toHaveValue("double-sided");
  await expect(page.locator("#status")).toBeEmpty({ timeout: 60000 });
  const download = await page.request.get(
    (await page
      .getByRole("link", { name: "下载当前模型" })
      .getAttribute("href")) as string,
  );
  expect(download.ok()).toBeTruthy();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  expect(errors).toEqual([]);
});
test("加载失败仍可下载", async ({ page }) => {
  await page.route("**/*.stl?*", (route) => route.abort());
  await page.goto("/");
  await expect(page.locator("#status")).toContainText("模型加载失败");
  await expect(page.getByRole("link", { name: "下载当前模型" })).toBeVisible();
});
test("GLB 与外部 glTF 资源", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const model = {
    id: "fixture",
    name: "纹理测试",
    description: "GLB/glTF",
    purpose: "display",
    units: "m",
    up: "Y",
    base: "fixtures/",
    preview: "preview.png",
    readme: "README.md",

    variants: [
      { id: "glb", name: "GLB", file: "model.glb" },
      { id: "gltf", name: "glTF", file: "model.gltf" },
    ],
    revisions: { "model.glb": "1", "model.gltf": "1" },
    validation: null,
  };
  await page.route("**/catalog.json", (route) =>
    route.fulfill({ json: [model] }),
  );
  await page.route("**/fixtures/**", async (route) => {
    const name = new URL(route.request().url()).pathname.split("/").pop();
    if (!name || name === "preview.png") return route.fulfill({ status: 404 });
    return route.fulfill({
      path: path.join(repoRoot, "tmp/fixtures/assets", name),
    });
  });
  await page.goto("/");
  await expect(page.locator("#status")).toBeEmpty({ timeout: 30000 });
  await page.selectOption("#variants", "gltf");
  await expect(page.locator("#status")).toBeEmpty({ timeout: 30000 });
  expect(errors).toEqual([]);
});
test("子目录静态资源与分享链接", async ({ page }) => {
  await page.route("**/nested/**", async (route) => {
    const url = new URL(route.request().url());
    let name = url.pathname.slice("/nested/".length) || "index.html";
    const types: Record<string, string> = {
      html: "text/html",
      js: "text/javascript",
      css: "text/css",
      json: "application/json",
    };
    await route.fulfill({
      path: `dist/${name}`,
      contentType: types[name.split(".").pop()!] ?? "application/octet-stream",
    });
  });
  await page.goto("/nested/?model=coin-sacagawea&variant=reverse");
  await expect(page.locator("#status")).toBeEmpty({ timeout: 60000 });
  await expect(page.locator("#variants")).toHaveValue("reverse");
  await expect(
    page.getByRole("link", { name: "下载当前模型" }),
  ).toHaveAttribute("href", /^\.\/models\//);
  await expect(
    page.getByRole("link", { name: "查看模型说明" }),
  ).toHaveAttribute("href", "./view.html?model=coin-sacagawea");
  await expect(
    page.getByRole("link", { name: "查看模型说明" }),
  ).toHaveAttribute("target", "_blank");
  await expect(
    page.getByRole("link", { name: "查看模型说明" }),
  ).toHaveAttribute("rel", "noopener noreferrer");
});

test("渲染并清理模型说明，正确解析链接", async ({ page }) => {
  const model = {
    id: "markdown-fixture",
    name: "说明测试模型",
    base: "models/markdown-fixture/docs/",
    readme: "README.md",
  };
  const markdown = `# 文档标题

| 项目 | 值 |
| --- | --- |
| 尺寸 | 20 mm |

- 列表项

\`\`\`js
const safe = true;
\`\`\`

[相对链接](../guide.pdf)
[外部链接](https://example.com/help)
![预览](images/preview.png)
<script>window.__unsafe = true</script>
<img src="x" onerror="window.__unsafe = true">
[危险链接](javascript:window.__unsafe=true)
`;
  await page.route("**/catalog.json", (route) =>
    route.fulfill({ json: [model] }),
  );
  await page.route("**/models/markdown-fixture/docs/README.md", (route) =>
    route.fulfill({ contentType: "text/markdown", body: markdown }),
  );
  await page.goto("/view.html?model=markdown-fixture");
  await expect(
    page.getByRole("heading", { name: "说明测试模型" }),
  ).toBeVisible();
  await expect(page.locator("#markdown table")).toContainText("20 mm");
  await expect(page.locator("#markdown pre")).toContainText("const safe");
  await expect(page.getByRole("link", { name: "相对链接" })).toHaveAttribute(
    "href",
    "http://127.0.0.1:4273/models/markdown-fixture/guide.pdf",
  );
  await expect(page.getByRole("link", { name: "外部链接" })).toHaveAttribute(
    "target",
    "_blank",
  );
  await expect(page.getByRole("link", { name: "外部链接" })).toHaveAttribute(
    "rel",
    "noopener noreferrer",
  );
  await expect(page.getByAltText("预览")).toHaveAttribute(
    "src",
    "http://127.0.0.1:4273/models/markdown-fixture/docs/images/preview.png",
  );
  await expect(page.locator("#markdown script")).toHaveCount(0);
  await expect(page.locator("#markdown [onerror]")).toHaveCount(0);
  await expect(page.locator('#markdown a[href^="javascript:"]')).toHaveCount(0);
  await expect(page.getByRole("link", { name: "查看原文" })).toHaveAttribute(
    "href",
    "http://127.0.0.1:4273/models/markdown-fixture/docs/README.md",
  );
  await expect(page.getByRole("link", { name: "返回模型工作台" })).toHaveCount(
    0,
  );
  expect(await page.evaluate(() => (window as any).__unsafe)).toBeUndefined();
});

test("模型说明显示参数、模型和请求错误", async ({ page }) => {
  await page.goto("/view.html");
  await expect(page.locator("#reader-status")).toContainText("缺少模型参数");

  await page.route("**/catalog.json", (route) =>
    route.fulfill({
      json: [
        {
          id: "known",
          name: "已知模型",
          base: "models/known/",
          readme: "README.md",
        },
      ],
    }),
  );
  await page.goto("/view.html?model=unknown");
  await expect(page.locator("#reader-status")).toContainText("未找到模型");

  await page.route("**/models/known/README.md", (route) =>
    route.fulfill({ status: 404 }),
  );
  await page.goto("/view.html?model=known");
  await expect(page.locator("#reader-status")).toContainText(
    "模型说明读取失败（HTTP 404）",
  );
  await expect(page.getByRole("link", { name: "查看原文" })).toBeVisible();
});
