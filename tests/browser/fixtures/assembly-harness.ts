import * as THREE from "three";
import { AssemblyPlayer } from "../../../viewer/src/assembly";
import { SceneCache, type SceneAsset } from "../../../viewer/src/scene-cache";

function fixture() {
  const scene = new THREE.Group();
  const root = new THREE.Group();
  root.name = "assembly-root";
  scene.add(root);
  const shared = new THREE.MeshStandardMaterial({
    opacity: 0.7,
    transparent: true,
    depthWrite: false,
    emissive: "#005500",
  });
  const other = new THREE.MeshBasicMaterial({ opacity: 0.9 });
  const geometry = new THREE.BoxGeometry();
  const a = new THREE.Mesh(geometry, [shared, other]);
  a.name = "a";
  const b = new THREE.Mesh(geometry, shared);
  b.name = "b";
  const group = new THREE.Group();
  group.name = "component";
  group.add(a);
  root.add(group, b);
  scene.userData.assembly = {
    version: 1,
    duration: 10,
    steps: [
      {
        title: "第一步",
        hint: "提示一",
        start: 0,
        end: 3,
        marker: [0, 0, 0],
        targets: ["component"],
        transparentTargets: ["a"],
      },
      {
        title: "第二步",
        hint: "提示二",
        start: 5,
        end: 8,
        marker: [1, 0, 0],
        targets: ["b"],
        transparentTargets: [],
      },
    ],
  };
  const clip = new THREE.AnimationClip("Assembly", 10, [
    new THREE.VectorKeyframeTrack("a.position", [0, 10], [0, 0, 0, 10, 0, 0]),
  ]);
  return { scene, root, a, b, shared, other, geometry, clip };
}

const click = (id: string) => document.getElementById(id)!.click();

export async function exercisePlayer() {
  const f = fixture();
  let requests = 0;
  const player = new AssemblyPlayer(f.scene, [f.clip], () => requests++);
  const displays = f.a.material as THREE.Material[];
  const display = displays[0] as THREE.MeshStandardMaterial;
  const bDisplay = f.b.material as THREE.MeshStandardMaterial;
  const initial = {
    isolated: display !== bDisplay && display !== f.shared,
    opacity: displays.map((material) => material.opacity),
    highlighted: display.emissive.getHexString(),
    unchangedOther:
      bDisplay.emissive.equals(f.shared.emissive) && bDisplay.opacity === 0.7,
  };
  let titleMutations = 0;
  const observer = new MutationObserver((records) => {
    titleMutations += records.length;
  });
  observer.observe(document.getElementById("assembly-title")!, {
    childList: true,
  });
  const version = display.version;
  click("assembly-play");
  player.resetClock(0);
  for (let i = 1; i <= 20; i++) player.advance(i * 100);
  await Promise.resolve();
  observer.disconnect();
  const steady = {
    time: f.a.position.x,
    x: f.a.position.x,
    titleMutations,
    materialVersion: display.version - version,
    requests,
    playing: player.needsFrame,
  };
  player.advance(6000);
  const second = {
    title: document.getElementById("assembly-title")!.textContent,
    opacity: displays.map((material) => material.opacity),
    originalEmissive: display.emissive.equals(f.shared.emissive),
    bHighlighted: bDisplay.emissive.getHexString(),
  };
  player.advance(10000);
  const complete = {
    time: f.a.position.x,
    playing: player.needsFrame,
    restored: bDisplay.emissive.equals(f.shared.emissive),
    markerVisible: f.root.children.at(-1)!.visible,
  };
  click("assembly-play");
  const replay = { time: f.a.position.x, playing: player.needsFrame };
  player.resetClock(0);
  player.advance(7000);
  click("assembly-previous");
  const backwards = { time: f.a.position.x, x: f.a.position.x };
  let disposals = 0;
  for (const material of [...displays, bDisplay])
    material.addEventListener("dispose", () => disposals++);
  const marker = f.root.children.at(-1) as THREE.Mesh;
  marker.geometry.addEventListener("dispose", () => disposals++);
  (marker.material as THREE.Material).addEventListener(
    "dispose",
    () => disposals++,
  );
  player.dispose();
  player.dispose();
  const disposed = {
    restored:
      (f.a.material as THREE.Material[])[0] === f.shared &&
      f.b.material === f.shared,
    markers: f.root.children.filter((node) => node === marker).length,
    x: f.a.position.x,
    disposals,
    playing: player.needsFrame,
    unbound:
      document.getElementById("assembly-play")!.onclick === null &&
      document.getElementById("assembly-next")!.onclick === null,
  };
  const again = new AssemblyPlayer(f.scene, [f.clip], () => requests++);
  const reentered = {
    time: f.a.position.x,
    children: f.root.children.length,
  };
  again.dispose();
  f.geometry.dispose();
  f.shared.dispose();
  f.other.dispose();
  return {
    initial,
    steady,
    second,
    complete,
    replay,
    backwards,
    disposed,
    reentered,
  };
}

export function exerciseNavigation() {
  const f = fixture();
  const player = new AssemblyPlayer(f.scene, [f.clip], () => {});
  const previous = document.getElementById(
    "assembly-previous",
  ) as HTMLButtonElement;
  const next = document.getElementById("assembly-next") as HTMLButtonElement;
  const state = () => ({
    time: f.a.position.x,
    title: document.getElementById("assembly-title")!.textContent,
    previousDisabled: previous.disabled,
    nextDisabled: next.disabled,
    playing: player.needsFrame,
  });
  const states = [state()];
  click("assembly-next");
  states.push(state());
  click("assembly-previous");
  states.push(state());
  click("assembly-play");
  player.resetClock(0);
  player.advance(2000);
  states.push(state());
  click("assembly-previous");
  states.push(state());
  click("assembly-play");
  player.resetClock(0);
  player.advance(4000);
  states.push(state());
  click("assembly-next");
  states.push(state());
  click("assembly-play");
  player.resetClock(0);
  player.advance(1000);
  states.push(state());
  click("assembly-previous");
  states.push(state());
  click("assembly-previous");
  states.push(state());
  click("assembly-next");
  click("assembly-play");
  player.resetClock(0);
  player.advance(5000);
  states.push(state());
  click("assembly-previous");
  states.push(state());
  click("assembly-next");
  states.push(state());
  click("assembly-previous");
  states.push(state());
  player.dispose();
  f.geometry.dispose();
  f.shared.dispose();
  f.other.dispose();
  return states;
}

export function exerciseValidation() {
  const failures: string[] = [];
  for (const invalid of [
    "targets",
    "duration",
    "outside",
    "root",
    "null-step",
  ]) {
    const f = fixture();
    if (invalid === "targets")
      delete f.scene.userData.assembly.steps[0].targets;
    if (invalid === "duration") f.clip.duration = 9;
    if (invalid === "outside") {
      f.scene.add(f.a);
    }
    if (invalid === "root") f.root.name = "other";
    if (invalid === "null-step") f.scene.userData.assembly.steps[0] = null;
    try {
      new AssemblyPlayer(f.scene, [f.clip], () => {});
    } catch {
      failures.push(invalid);
    }
    f.geometry.dispose();
    f.shared.dispose();
    f.other.dispose();
  }
  return failures;
}

export function exerciseCache() {
  const released: THREE.Object3D[] = [];
  const cache = new SceneCache((root) => released.push(root));
  const asset = (): SceneAsset => ({
    object: new THREE.Group(),
    box: new THREE.Box3(),
    radius: 1,
  });
  const assembly = asset(),
    printed = asset();
  cache.retain("model", { assembly: "a1", print: "p1" });
  cache.set("assembly", "a1", assembly);
  cache.set("print", "p1", printed);
  cache.retain("model", { assembly: "a1", print: "p1" });
  const reused =
    cache.get("assembly", "a1") === assembly &&
    cache.get("print", "p1") === printed &&
    released.length === 0;
  cache.retain("model", { assembly: "a1", print: "p2" });
  const replacedPrint =
    released[0] === printed.object && cache.get("assembly", "a1") === assembly;
  cache.set("print", "p2", asset());
  cache.retain("model", { assembly: "a2", print: "p2" });
  const invalidated =
    released[1] === assembly.object && !cache.get("assembly", "a1");
  cache.set("assembly", "a2", asset());
  cache.retain("other", { assembly: "a2", print: "p2" });
  const switched = released.length === 4;
  cache.set("assembly", "a2", asset());
  cache.clear();
  cache.clear();
  return {
    reused,
    replacedPrint,
    invalidated,
    switched,
    releases: released.length,
  };
}
