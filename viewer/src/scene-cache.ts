import * as THREE from "three";

export type SceneAsset = {
  object: THREE.Object3D;
  box: THREE.Box3;
  radius: number;
  assembly?: { scene: THREE.Object3D; clips: THREE.AnimationClip[] };
  report?: {
    file: string;
    dimensions: number[];
    triangles: number;
    bytes: number;
    components: number;
    passed: boolean;
  };
};
type Slot = "assembly" | "print";

/** Owns at most the current model's assembly and selected print scene. */
export class SceneCache {
  private model = "";
  private entries = new Map<Slot, { key: string; asset: SceneAsset }>();

  constructor(private release: (root: THREE.Object3D) => void) {}

  retain(model: string, keys: Record<Slot, string>) {
    for (const [slot, entry] of this.entries) {
      if (model !== this.model || keys[slot] !== entry.key) this.delete(slot);
    }
    this.model = model;
  }

  get(slot: Slot, key: string) {
    const entry = this.entries.get(slot);
    return entry?.key === key ? entry.asset : undefined;
  }

  set(slot: Slot, key: string, asset: SceneAsset) {
    this.delete(slot);
    this.entries.set(slot, { key, asset });
  }

  delete(slot: Slot) {
    const entry = this.entries.get(slot);
    if (!entry) return;
    this.entries.delete(slot);
    this.release(entry.asset.object);
  }

  clear() {
    for (const slot of this.entries.keys()) this.delete(slot);
    this.model = "";
  }
}
