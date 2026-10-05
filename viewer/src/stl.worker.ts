import { STLLoader } from "three/addons/loaders/STLLoader.js";
self.onmessage = (event: MessageEvent<ArrayBuffer>) => {
  try {
    const geometry = new STLLoader().parse(event.data);
    const positions = geometry.getAttribute("position").array as Float32Array;
    const normals = geometry.getAttribute("normal").array as Float32Array;
    self.postMessage(
      { positions, normals },
      { transfer: [positions.buffer, normals.buffer] },
    );
  } catch (error) {
    self.postMessage({ error: String(error) });
  }
};
