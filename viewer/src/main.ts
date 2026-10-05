import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import "./style.css";
import { AssemblyPlayer } from "./assembly";
import { SceneCache, type SceneAsset } from "./scene-cache";
type Variant = {
  id: string;
  name: string;
  file: string;
  purpose?: "print" | "display";
  units?: "mm" | "cm" | "m";
  up?: "Y" | "Z";
};
type Report = {
  file: string;
  dimensions: number[];
  triangles: number;
  bytes: number;
  components: number;
  passed: boolean;
};
type Model = {
  id: string;
  name: string;
  description: string;
  purpose: string;
  units: string;
  up: string;
  base: string;
  preview: string;
  readme: string;
  assembly?: string;
  variants: Variant[];
  revisions: Record<string, string>;
  validation: { files: Report[] } | null;
};
const $ = <T extends HTMLElement>(id: string) =>
  document.getElementById(id) as T;
const viewport = $("viewport"),
  status = $("status");
let models: Model[] = [],
  model: Model,
  variant: Variant;
let assemblyMode = false;
let assemblyPlayer: AssemblyPlayer | null = null;
let object: THREE.Object3D | null = null,
  generation = 0,
  controller: AbortController | null = null,
  worker: Worker | null = null;
const sceneCache = new SceneCache(dispose);
let renderer!: THREE.WebGLRenderer;
try {
  renderer = new THREE.WebGLRenderer({ antialias: true });
} catch {
  status.textContent =
    "WebGL 不可用，请使用支持 3D 加速的浏览器。仍可下载模型。";
}
const available = !!renderer!;
const scene = new THREE.Scene();
scene.background = new THREE.Color("#e4ebf0");
scene.add(new THREE.HemisphereLight(0xffffff, 0x61758a, 2));
const light = new THREE.DirectionalLight(0xffffff, 3);
light.position.set(-3, 5, 4);
scene.add(light);
const fill = new THREE.DirectionalLight(0xe0ebff, 1);
fill.position.set(3, 1, -3);
scene.add(fill);
let camera: THREE.PerspectiveCamera | THREE.OrthographicCamera =
  new THREE.PerspectiveCamera(40, 1, 0.01, 10000);
let controls: OrbitControls;
let grid: THREE.GridHelper | null = null,
  axes: THREE.AxesHelper | null = null;
let radius = 50;
let frame = 0;
function render() {
  if (!available || frame || document.hidden) return;
  frame = requestAnimationFrame((now) => {
    frame = 0;
    assemblyPlayer?.advance(now);
    renderer.render(scene, camera);
    if (assemblyPlayer?.needsFrame) render();
  });
}
document.addEventListener("visibilitychange", () => {
  cancelAnimationFrame(frame);
  frame = 0;
  assemblyPlayer?.resetClock();
  if (!document.hidden) render();
});

function size() {
  if (!available) return;
  const w = viewport.clientWidth,
    h = viewport.clientHeight;
  renderer.setSize(w, h);
  const aspect = w / h;
  if (camera instanceof THREE.PerspectiveCamera) camera.aspect = aspect;
  else {
    const extent = (radius * 1.4) / Math.min(aspect, 1);
    camera.left = -extent * aspect;
    camera.right = extent * aspect;
    camera.top = extent;
    camera.bottom = -extent;
  }
  camera.updateProjectionMatrix();
  render();
}
function bindControls() {
  controls?.dispose();
  controls = new OrbitControls(camera, renderer.domElement);
  controls.addEventListener("change", render);
}
if (available) {
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  viewport.prepend(renderer.domElement);
  renderer.domElement.setAttribute("aria-label", "交互式 3D 模型");
  bindControls();
  new ResizeObserver(size).observe(viewport);
}
function dispose(root: THREE.Object3D) {
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();
  const textures = new Set<THREE.Texture>();
  root.traverse((node) => {
    if (node instanceof THREE.Mesh || node instanceof THREE.LineSegments) {
      geometries.add(node.geometry);
      for (const mat of Array.isArray(node.material)
        ? node.material
        : [node.material]) {
        materials.add(mat);
        for (const value of Object.values(mat))
          if (value instanceof THREE.Texture) textures.add(value);
      }
    }
  });
  for (const geometry of geometries) geometry.dispose();
  for (const material of materials) material.dispose();
  for (const texture of textures) texture.dispose();
}

function detach() {
  assemblyPlayer?.dispose();
  assemblyPlayer = null;
  object?.removeFromParent();
  object = null;
  for (const helper of [grid, axes]) {
    if (!helper) continue;
    helper.removeFromParent();
    dispose(helper);
  }
  grid = axes = null;
}

function attach(asset: SceneAsset, preserve: boolean) {
  object = asset.object;
  radius = asset.radius;
  scene.add(object);
  if (asset.report) info(asset.report);
  grid = new THREE.GridHelper(radius * 3, 12, 0x9baebb, 0xc5d1d9);
  grid.position.y =
    -asset.box.getSize(new THREE.Vector3()).y / 2 - radius * 0.005;
  grid.visible = $<HTMLInputElement>("grid").checked;
  scene.add(grid);
  axes = new THREE.AxesHelper(radius * 0.8);
  axes.visible = $<HTMLInputElement>("axes").checked;
  scene.add(axes);
  if (asset.assembly) {
    assemblyPlayer = new AssemblyPlayer(
      asset.assembly.scene,
      asset.assembly.clips,
      render,
    );
    grid.visible = axes.visible = false;
  }
  wire();
  if (!preserve) resetView();
  else size();
  status.textContent = "";
  render();
}

function assetKey(file: string, units: string, up: string) {
  return JSON.stringify([url(file), model.revisions[file], units, up]);
}

function resetView() {
  if (!available) return;
  const direction = new THREE.Vector3(1, 1.3, 1.4).normalize();
  controls.target.set(0, 0, 0);
  const aspect = viewport.clientWidth / viewport.clientHeight;
  camera.position.copy(
    direction.multiplyScalar((radius * 3.3) / Math.min(aspect, 1)),
  );
  camera.near = Math.max(radius / 1000, 0.00001);
  camera.far = radius * 100;
  camera.up.set(0, 1, 0);
  camera.zoom = 1;
  camera.updateProjectionMatrix();
  controls.update();
  size();
}
function url(name: string, m = model) {
  return `${import.meta.env.BASE_URL}${m.base}${name.split("/").map(encodeURIComponent).join("/")}`;
}
function info(runtime?: Report) {
  $("title").textContent = model.name;
  $("description").textContent = model.description;
  const report =
    model.validation?.files.find((r) => r.file === variant.file) ?? runtime;
  const values: Record<string, string> = {
    用途: (variant.purpose ?? model.purpose) === "print" ? "3D 打印" : "展示",
    格式: variant.file.split(".").pop()!.toUpperCase(),
    尺寸: report
      ? `${report.dimensions.map((n) => n.toFixed(2)).join(" × ")} ${variant.units ?? model.units}`
      : "加载后显示",
    三角形: report?.triangles.toLocaleString() ?? "—",
    文件大小: report ? `${(report.bytes / 1024 / 1024).toFixed(1)} MB` : "—",
    实体数量: report?.components.toString() ?? "—",
  };
  $("metrics").replaceChildren(
    ...Object.entries(values).flatMap(([key, value]) => {
      const dt = document.createElement("dt"),
        dd = document.createElement("dd");
      dt.textContent = key;
      dd.textContent = value;
      return [dt, dd];
    }),
  );
  $("validation").textContent = report?.passed
    ? "✓ 几何校验通过"
    : "待重新校验，请运行 build";
  $("validation").className = report?.passed ? "pass" : "pending";
  $("downloads").replaceChildren(
    ...[
      [variant.file, "下载当前模型"],
      [model.readme, "查看模型说明"],
      ...(model.assembly ? [[model.assembly, "下载装配动画"]] : []),
    ].map(([file, label]) => {
      const a = document.createElement("a");
      a.textContent = label;
      if (file.endsWith(".md")) {
        const viewer = new URL("view.html", location.href);
        viewer.searchParams.set("model", model.id);
        a.href = `${import.meta.env.BASE_URL}${viewer.pathname.split("/").pop()}${viewer.search}`;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
      } else {
        a.href = url(file);
        a.download = file;
      }
      return a;
    }),
  );
}
async function buffer(response: Response, signal: AbortSignal) {
  if (!response.ok) throw Error(`HTTP ${response.status}`);
  const total = Number(response.headers.get("content-length")),
    reader = response.body!.getReader();
  let received = 0;
  const chunks: Uint8Array[] = [];
  while (true) {
    if (signal.aborted) throw new DOMException("取消", "AbortError");
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    received += value.length;
    status.textContent = `正在加载… ${total ? Math.round((received / total) * 100) + "%" : (received / 1048576).toFixed(1) + " MB"}`;
  }
  const data = new Uint8Array(received);
  let offset = 0;
  for (const chunk of chunks) {
    data.set(chunk, offset);
    offset += chunk.length;
  }
  return data.buffer;
}
async function load(preserve = false) {
  const loadingModel = model;
  const loadingAssembly = assemblyMode;
  const loadingVariant: Variant = loadingAssembly
    ? {
        id: "assembly",
        name: "装配动画",
        file: model.assembly!,
        purpose: "display",
        units: "m",
        up: "Y",
      }
    : variant;
  detach();
  info();
  if (!available) return;
  const token = ++generation;
  controller?.abort();
  worker?.terminate();
  controller = new AbortController();
  const signal = controller.signal;
  const slot = loadingAssembly ? "assembly" : "print";
  const keys = {
    assembly: assetKey(loadingModel.assembly ?? "", "m", "Y"),
    print: assetKey(
      variant.file,
      variant.units ?? model.units,
      variant.up ?? model.up,
    ),
  };
  sceneCache.retain(loadingModel.id, keys);
  const key = keys[slot];
  let pending: THREE.Object3D | null = null;
  status.textContent = "正在加载模型…";
  try {
    const cached = sceneCache.get(slot, key);
    if (cached) {
      attach(cached, preserve);
      return;
    }
    if (loadingModel.revisions[loadingVariant.file] === "missing")
      throw Error(`模型尚未构建，请运行 npm run build`);
    let next: THREE.Object3D;
    let assemblyScene: THREE.Object3D | undefined;
    let assemblyClips: THREE.AnimationClip[] = [];
    let rawDimensions: number[] | undefined;
    let byteLength = 0;
    if (loadingVariant.file.toLowerCase().endsWith(".stl")) {
      const data = await buffer(
        await fetch(
          url(loadingVariant.file, loadingModel) +
            `?v=${loadingModel.revisions[loadingVariant.file]}`,
          {
            signal,
          },
        ),
        signal,
      );
      byteLength = data.byteLength;
      if (token !== generation) return;
      status.textContent = "正在解析网格…";
      const geometry = await new Promise<THREE.BufferGeometry>(
        (resolve, reject) => {
          const w = new Worker(new URL("./stl.worker.ts", import.meta.url), {
            type: "module",
          });
          worker = w;
          const cancel = () => {
            w.terminate();
            reject(new DOMException("取消", "AbortError"));
          };
          signal.addEventListener("abort", cancel, { once: true });
          w.onmessage = (e) => {
            signal.removeEventListener("abort", cancel);
            w.terminate();
            if (e.data.error) return reject(Error(e.data.error));
            const g = new THREE.BufferGeometry();
            g.setAttribute(
              "position",
              new THREE.BufferAttribute(e.data.positions, 3),
            );
            g.setAttribute(
              "normal",
              new THREE.BufferAttribute(e.data.normals, 3),
            );
            resolve(g);
          };
          w.onerror = (e) => {
            signal.removeEventListener("abort", cancel);
            w.terminate();
            reject(Error(e.message));
          };
          w.postMessage(data, [data]);
        },
      );
      geometry.computeBoundingBox();
      rawDimensions = geometry
        .boundingBox!.getSize(new THREE.Vector3())
        .toArray();
      next = new THREE.Mesh(
        geometry,
        new THREE.MeshStandardMaterial({
          color: 0xb5bec5,
          roughness: 0.58,
          metalness: 0.18,
          side: THREE.DoubleSide,
        }),
      );
      if ((loadingVariant.up ?? loadingModel.up) === "Z")
        next.rotation.x = -Math.PI / 2;
    } else {
      const manager = new THREE.LoadingManager();
      let resourceError = "";
      manager.onError = (asset) => {
        resourceError = asset;
      };
      manager.setURLModifier((asset) => {
        const resolved = new URL(asset, location.href);
        if (resolved.protocol === "data:" || resolved.protocol === "blob:")
          return asset;
        if (resolved.origin !== location.origin)
          throw Error("不支持远程 glTF 资源");
        return asset;
      });
      const loader = new GLTFLoader(manager);
      const data = await buffer(
        await fetch(
          url(loadingVariant.file, loadingModel) +
            `?v=${loadingModel.revisions[loadingVariant.file]}`,
          {
            signal,
          },
        ),
        signal,
      );
      byteLength = data.byteLength;
      const gltf = await loader.parseAsync(
        data,
        new URL(
          url(loadingVariant.file, loadingModel),
          location.href,
        ).href.replace(/[^/]*$/, ""),
      );
      if (resourceError) {
        dispose(gltf.scene);
        throw Error(`缺失模型资源：${resourceError}`);
      }
      if (loadingAssembly) {
        assemblyScene = gltf.scene;
        assemblyClips = gltf.animations;
        next = new THREE.Group();
        next.add(gltf.scene);
      } else next = gltf.scene;
    }
    pending = next;
    if (token !== generation) {
      dispose(next);
      pending = null;
      return;
    }
    next.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(next);
    if (box.isEmpty()) throw Error("模型为空");
    // Keep runtime metrics even when validation is currently fresh: a cached
    // scene can outlive its validation report after an input or manifest edit.
    let triangles = 0;
    next.traverse((node) => {
      if (node instanceof THREE.Mesh)
        triangles +=
          (node.geometry.index?.count ??
            node.geometry.getAttribute("position").count) / 3;
    });
    const report: Report = {
      file: loadingVariant.file,
      dimensions: rawDimensions ?? box.getSize(new THREE.Vector3()).toArray(),
      triangles,
      bytes: byteLength,
      components: 0,
      passed: false,
    };
    next.position.sub(box.getCenter(new THREE.Vector3()));
    const asset: SceneAsset = {
      object: next,
      box,
      radius: Math.max(box.getSize(new THREE.Vector3()).length() / 2, 0.001),
      assembly: assemblyScene
        ? { scene: assemblyScene, clips: assemblyClips }
        : undefined,
      report,
    };
    attach(asset, preserve);
    sceneCache.set(slot, key, asset);
    pending = null;
  } catch (error) {
    if (token === generation && !signal.aborted) {
      detach();
      sceneCache.delete(slot);
      status.textContent = `模型加载失败：${String(error)}。可下载原文件检查。`;
      render();
    }
    if (pending) dispose(pending);
  }
}

function wire() {
  object?.traverse((node) => {
    if (node instanceof THREE.Mesh)
      for (const mat of Array.isArray(node.material)
        ? node.material
        : [node.material])
        if ("wireframe" in mat)
          mat.wireframe = $<HTMLInputElement>("wire").checked;
  });
  render();
}
function updateInteractionHint() {
  $("interaction-hint").textContent = assemblyMode
    ? "红点标示定位部位 · 高亮显示当前零件"
    : "拖动旋转 · 滚轮缩放 · 右键平移";
}

function select(
  id: string,
  variantId?: string,
  preserve = false,
  mode = false,
) {
  model = models.find((m) => m.id === id) ?? models[0];
  if (!model) {
    assemblyMode = false;
    $("assembly-toggle").hidden = true;
    updateInteractionHint();
    ++generation;
    controller?.abort();
    worker?.terminate();
    controller = null;
    worker = null;
    detach();
    sceneCache.clear();
    for (const id of [
      "title",
      "description",
      "metrics",
      "validation",
      "downloads",
      "variants",
    ])
      $(id).replaceChildren();
    $<HTMLSelectElement>("variants").disabled = true;
    const query = new URL(location.href);
    query.searchParams.delete("model");
    query.searchParams.delete("variant");
    query.searchParams.delete("mode");
    history.replaceState(null, "", query);
    render();
    status.textContent = "模型库为空。添加 model.json 后刷新。";
    return;
  }
  assemblyMode = mode && !!model.assembly;
  updateInteractionHint();
  $("assembly-toggle").hidden = !model.assembly;
  $("assembly-toggle").textContent = assemblyMode ? "返回打印模型" : "装配动画";
  $("assembly-toggle").setAttribute("aria-pressed", String(assemblyMode));
  variant = model.variants.find((v) => v.id === variantId) ?? model.variants[0];
  const select = $<HTMLSelectElement>("variants");
  select.replaceChildren(
    ...model.variants.map((v) => new Option(v.name, v.id)),
  );
  select.disabled = assemblyMode;
  select.value = variant.id;
  document
    .querySelectorAll<HTMLButtonElement>(".model")
    .forEach((button) =>
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.id === model.id),
      ),
    );
  const query = new URL(location.href);
  query.searchParams.set("model", model.id);
  query.searchParams.set("variant", variant.id);
  if (assemblyMode) query.searchParams.set("mode", "assembly");
  else query.searchParams.delete("mode");
  history.replaceState(null, "", query);
  void load(preserve);
}
async function refresh(preserve = false) {
  try {
    const response = await fetch(`${import.meta.env.BASE_URL}catalog.json`, {
      cache: "no-store",
    });
    if (!response.ok) throw Error(`HTTP ${response.status}`);
    models = await response.json();
    $("models").replaceChildren(
      ...models.map((m) => {
        const button = document.createElement("button");
        button.className = "model";
        button.dataset.id = m.id;
        const image = document.createElement("img");
        image.src = url(m.preview, m);
        image.alt = "";
        const name = document.createElement("span");
        name.textContent = m.name;
        button.append(image, name);
        button.onclick = () => select(m.id);
        return button;
      }),
    );
    const params = new URLSearchParams(location.search);
    select(
      params.get("model") ?? "",
      params.get("variant") ?? "",
      preserve,
      params.get("mode") === "assembly",
    );
  } catch (error) {
    status.textContent = `模型库读取失败：${String(error)}`;
  }
}
$<HTMLSelectElement>("variants").onchange = (e) =>
  model && select(model.id, (e.target as HTMLSelectElement).value);
$("assembly-toggle").onclick = () =>
  model && select(model.id, variant.id, false, !assemblyMode);
$("reset").onclick = () => resetView();
$("wire").onchange = wire;
$("grid").onchange = () => {
  if (grid) grid.visible = $<HTMLInputElement>("grid").checked;
  render();
};
$("axes").onchange = () => {
  if (axes) axes.visible = $<HTMLInputElement>("axes").checked;
  render();
};
$("projection").onclick = () => {
  if (!available) return;
  const old = camera;
  camera =
    old instanceof THREE.PerspectiveCamera
      ? new THREE.OrthographicCamera()
      : new THREE.PerspectiveCamera(40, 1, 0.01, 10000);
  camera.position.copy(old.position);
  camera.up.copy(old.up);
  camera.near = old.near;
  camera.far = old.far;
  const target = controls.target.clone();
  bindControls();
  controls.target.copy(target);
  controls.update();
  $("projection").setAttribute(
    "aria-pressed",
    String(camera instanceof THREE.OrthographicCamera),
  );
  size();
};
document.querySelectorAll<HTMLButtonElement>("[data-view]").forEach(
  (button) =>
    (button.onclick = () => {
      if (!available) return;
      const directions: Record<string, number[]> = {
        top: [0, 1, 0],
        bottom: [0, -1, 0],
        front: [0, 0, 1],
        back: [0, 0, -1],
        left: [-1, 0, 0],
        right: [1, 0, 0],
      };
      const d = directions[button.dataset.view!];
      camera.position
        .set(...(d as [number, number, number]))
        .multiplyScalar(
          (radius * 3.3) /
            Math.min(viewport.clientWidth / viewport.clientHeight, 1),
        );
      controls.target.set(0, 0, 0);
      camera.up.set(0, Math.abs(d[1]) ? 0 : 1, Math.abs(d[1]) ? -d[1] : 0);
      controls.update();
      render();
    }),
);
if (import.meta.hot)
  import.meta.hot.on("models-updated", () => void refresh(true));
void refresh();
