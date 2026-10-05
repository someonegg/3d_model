import DOMPurify from "dompurify";
import { marked } from "marked";
import "./view.css";

type Model = {
  id: string;
  name: string;
  base: string;
  readme: string;
};

const get = <T extends HTMLElement>(id: string) =>
  document.getElementById(id) as T;
const status = get("reader-status");
const content = get("markdown");

function fail(message: string) {
  status.textContent = message;
  status.className = "reader-error";
  content.hidden = true;
}

function resolveDocumentUrls(root: HTMLElement, readmeUrl: URL) {
  root.querySelectorAll<HTMLAnchorElement>("a[href]").forEach((link) => {
    const href = link.getAttribute("href");
    if (!href) return;
    const resolved = new URL(href, readmeUrl);
    link.href = resolved.href;
    if (resolved.origin !== location.origin) {
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    }
  });
  root.querySelectorAll<HTMLImageElement>("img[src]").forEach((image) => {
    const src = image.getAttribute("src");
    if (src) image.src = new URL(src, readmeUrl).href;
  });
}

async function load() {
  const modelId = new URLSearchParams(location.search).get("model");
  if (!modelId) return fail("缺少模型参数。请从模型工作台打开说明。");

  try {
    const catalogResponse = await fetch(
      `${import.meta.env.BASE_URL}catalog.json`,
      { cache: "no-store" },
    );
    if (!catalogResponse.ok)
      throw new Error(`模型库请求失败（HTTP ${catalogResponse.status}）`);
    const models = (await catalogResponse.json()) as Model[];
    const model = models.find((entry) => entry.id === modelId);
    if (!model) return fail(`未找到模型“${modelId}”。`);

    document.title = `${model.name}｜模型说明`;
    get("model-name").textContent = model.name;
    get("source-name").textContent = model.readme;
    const readmeUrl = new URL(
      `${import.meta.env.BASE_URL}${model.base}${model.readme
        .split("/")
        .map(encodeURIComponent)
        .join("/")}`,
      location.href,
    );

    const rawLink = document.createElement("a");
    rawLink.href = readmeUrl.href;
    rawLink.textContent = "查看原文";
    get("reader-actions").append(rawLink);

    const response = await fetch(readmeUrl);
    if (!response.ok)
      return fail(`模型说明读取失败（HTTP ${response.status}）。`);
    const markdown = await response.text();
    const html = await marked.parse(markdown, { gfm: true });
    content.innerHTML = DOMPurify.sanitize(html);
    resolveDocumentUrls(content, readmeUrl);
    status.textContent = markdown.trim() ? "" : "此模型说明为空。";
    status.className = markdown.trim() ? "" : "reader-empty";
    content.hidden = !markdown.trim();
  } catch (error) {
    fail(`模型说明无法显示：${String(error)}`);
  }
}

void load();
