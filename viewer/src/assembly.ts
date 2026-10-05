import * as THREE from "three";

type Step = {
  title: string;
  hint: string;
  start: number;
  end: number;
  marker: [number, number, number];
  targets: string[];
  transparentTargets: string[];
  opacity?: number;
  markerRadius?: number;
};
type Guide = { version: number; duration: number; steps: Step[] };
type Appearance = {
  mesh: THREE.Mesh;
  original: THREE.Material | THREE.Material[];
  materials: { base: THREE.Material; display: THREE.Material }[];
};

/** Owns animation and temporary appearance; the caller owns the loaded scene. */
export class AssemblyPlayer {
  private mixer: THREE.AnimationMixer;
  private action: THREE.AnimationAction;
  private guide: Guide;
  private time = 0;
  private playing = false;
  private last = 0;
  private disposed = false;
  private visualState = "";
  private buttonState?: boolean;
  private marker: THREE.Mesh;
  private appearances: Appearance[] = [];
  private steps: { targets: Set<THREE.Mesh>; transparent: Set<THREE.Mesh> }[];
  private controls = document.getElementById("assembly-controls")!;
  private panel = document.getElementById("assembly-panel")!;
  private play = document.getElementById("assembly-play")!;
  private previous = document.getElementById(
    "assembly-previous",
  ) as HTMLButtonElement;
  private next = document.getElementById("assembly-next") as HTMLButtonElement;
  private title = document.getElementById("assembly-title")!;
  private hint = document.getElementById("assembly-hint")!;

  constructor(
    scene: THREE.Object3D,
    clips: THREE.AnimationClip[],
    private requestRender: () => void,
  ) {
    const root = scene.getObjectByName("assembly-root");
    if (!root) throw Error("装配根节点缺失");
    const named = new Map<string, THREE.Object3D>();
    root.traverse((node) => {
      if (!node.name) return;
      if (named.has(node.name)) throw Error(`装配节点名称重复：${node.name}`);
      named.set(node.name, node);
    });
    const guide = scene.userData.assembly as Guide | undefined;
    if (
      !guide ||
      guide.version !== 1 ||
      !Number.isFinite(guide.duration) ||
      guide.duration <= 0 ||
      !Array.isArray(guide.steps) ||
      guide.steps.length === 0 ||
      clips.length !== 1 ||
      !Number.isFinite(clips[0].duration) ||
      Math.abs(clips[0].duration - guide.duration) > 1e-5 ||
      guide.steps.some(
        (s, i) =>
          !s ||
          typeof s.title !== "string" ||
          typeof s.hint !== "string" ||
          !Number.isFinite(s.start) ||
          !Number.isFinite(s.end) ||
          s.start < 0 ||
          s.end <= s.start ||
          s.end > guide.duration ||
          (i === 0 ? s.start !== 0 : s.start <= guide.steps[i - 1].end) ||
          !Array.isArray(s.marker) ||
          s.marker.length !== 3 ||
          !s.marker.every(Number.isFinite) ||
          [s.targets, s.transparentTargets].some(
            (names) =>
              !Array.isArray(names) ||
              names.some(
                (name) => typeof name !== "string" || !named.has(name),
              ),
          ) ||
          s.targets.length === 0 ||
          (s.opacity !== undefined &&
            (!Number.isFinite(s.opacity) || s.opacity <= 0 || s.opacity > 1)) ||
          (s.markerRadius !== undefined &&
            (!Number.isFinite(s.markerRadius) || s.markerRadius <= 0)),
      )
    )
      throw Error("装配步骤数据无效");
    this.guide = guide;
    const meshes = (names: string[]) => {
      const result = new Set<THREE.Mesh>();
      for (const name of names)
        named.get(name)!.traverse((node) => {
          if (node instanceof THREE.Mesh) result.add(node);
        });
      return result;
    };
    this.steps = guide.steps.map((step) => ({
      targets: meshes(step.targets),
      transparent: meshes(step.transparentTargets),
    }));
    root.traverse((node) => {
      if (!(node instanceof THREE.Mesh)) return;
      const original = node.material;
      const materials = (Array.isArray(original) ? original : [original]).map(
        (base) => ({ base, display: base.clone() }),
      );
      node.material = Array.isArray(original)
        ? materials.map((m) => m.display)
        : materials[0].display;
      this.appearances.push({ mesh: node, original, materials });
    });
    this.mixer = new THREE.AnimationMixer(scene);
    this.action = this.mixer
      .clipAction(clips[0])
      .setLoop(THREE.LoopOnce, 1)
      .play();
    this.action.clampWhenFinished = true;
    this.marker = new THREE.Mesh(
      new THREE.SphereGeometry(0.0012, 16, 12),
      new THREE.MeshBasicMaterial({
        color: "#e04e39",
        depthTest: false,
        transparent: true,
      }),
    );
    this.marker.renderOrder = 10;
    root.add(this.marker);
    this.play.onclick = () => {
      if (this.time >= this.guide.duration) this.seek(0);
      this.playing = !this.playing;
      this.resetClock();
      this.update();
      this.requestRender();
    };
    this.previous.onclick = () => {
      const index = this.index();
      const start = this.guide.steps[index].start;
      this.seek(
        this.guide.steps[this.time > start ? index : Math.max(0, index - 1)]
          .start,
      );
    };
    this.next.onclick = () =>
      this.seek(
        this.guide.steps[this.index() + 1]?.start ?? this.guide.duration,
      );
    this.panel.hidden = this.controls.hidden = false;
    this.update();
    this.requestRender();
  }

  get needsFrame() {
    return this.playing && !this.disposed;
  }

  resetClock(now = performance.now()) {
    this.last = now;
  }

  /** Called by the viewer immediately before drawing the same frame. */
  advance(now: number) {
    if (!this.needsFrame) return;
    this.time = Math.min(
      this.guide.duration,
      this.time + Math.max(0, (now - this.last) / 1000),
    );
    this.last = now;
    if (this.time >= this.guide.duration) this.playing = false;
    this.update();
  }

  private index() {
    let index = 0;
    this.guide.steps.forEach((step, i) => {
      if (this.time >= step.start) index = i;
    });
    return index;
  }

  private seek(time: number) {
    if (!Number.isFinite(time)) return;
    this.playing = false;
    this.time = Math.max(0, Math.min(this.guide.duration, time));
    this.update();
    this.requestRender();
  }

  private update() {
    this.action.paused = false;
    this.mixer.setTime(this.time);
    if (this.buttonState !== this.playing) {
      this.play.textContent = this.playing ? "暂停" : "播放";
      this.play.setAttribute("aria-pressed", String(this.playing));
      this.buttonState = this.playing;
    }
    const index = this.index(),
      step = this.guide.steps[index];
    this.previous.disabled = this.time === 0;
    this.next.disabled = this.time >= this.guide.duration;
    const active = this.time < this.guide.duration;
    const state = `${index}:${active}`;
    if (state === this.visualState) return;
    this.visualState = state;
    this.title.textContent = `${index + 1} / ${this.guide.steps.length} · ${step.title}`;
    this.hint.textContent = step.hint;
    const resolved = this.steps[index];
    for (const { mesh, materials } of this.appearances) {
      const transparent = active && resolved.transparent.has(mesh);
      for (const { base, display } of materials) {
        const opacity = transparent ? (step.opacity ?? 0.2) : base.opacity;
        const enabled = transparent
          ? opacity < 1 || base.transparent
          : base.transparent;
        if (display.transparent !== enabled) display.needsUpdate = true;
        display.transparent = enabled;
        display.opacity = opacity;
        display.depthWrite =
          transparent && opacity < 1 ? false : base.depthWrite;
        if (
          display instanceof THREE.MeshStandardMaterial &&
          base instanceof THREE.MeshStandardMaterial
        ) {
          if (active && resolved.targets.has(mesh))
            display.emissive.set("#463222");
          else display.emissive.copy(base.emissive);
        }
      }
    }
    this.marker.position.fromArray(step.marker);
    this.marker.scale.setScalar((step.markerRadius ?? 0.0012) / 0.0012);
    this.marker.visible = active;
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.playing = false;
    this.mixer.stopAllAction();
    this.mixer.uncacheRoot(this.mixer.getRoot());
    this.marker.removeFromParent();
    this.marker.geometry.dispose();
    (this.marker.material as THREE.Material).dispose();
    for (const { mesh, original, materials } of this.appearances) {
      mesh.material = original;
      for (const { display } of materials) display.dispose();
    }
    this.appearances = [];
    this.panel.hidden = this.controls.hidden = true;
    this.play.onclick = this.previous.onclick = this.next.onclick = null;
  }
}
