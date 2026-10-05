"""Orchestrate model exports and public previews."""
from pathlib import Path
import os
import numpy as np
import trimesh
from geometry import NAME, make_parts
from preview import draw_preview

def main():
    OUT = Path(os.environ['MODEL_OUTPUT_DIR'])
    OUT.mkdir(parents=True, exist_ok=True)
    parts = make_parts()
    parts[1][1].export(OUT / 'fidget-button-fdm-cap.stl')
    parts[-1][1].export(OUT / 'fidget-button-fdm-spring.stl')
    placements = [(-31, 0), (32, -25), (32, 26), (-29, 48)]
    meshes = []
    for (name, mesh), (x, y) in zip(parts, placements):
        if not mesh.is_watertight or not mesh.is_winding_consistent or mesh.volume <= 0:
            raise ValueError(f'{name} is not a closed positive solid')
        mesh.apply_translation((x, y, -mesh.bounds[0, 2]))
        meshes.append(mesh)
        print(name, 'size', np.round(mesh.extents, 2).tolist(), 'volume', round(mesh.volume, 2))
    trimesh.util.concatenate(meshes).export(OUT / NAME)
    draw_preview(OUT)


if __name__ == '__main__':
    main()
