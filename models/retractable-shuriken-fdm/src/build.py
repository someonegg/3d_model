"""Reproducible exports; all writes are confined to MODEL_OUTPUT_DIR."""
import json
import os
from pathlib import Path

import numpy as np
import trimesh

from assembly import write_assembly, write_static
from geometry import P, WINGS, make_parts, print_mesh, LID_TOP
from preview import render


def main():
    output = Path(os.environ['MODEL_OUTPUT_DIR'])
    output.mkdir(parents=True, exist_ok=True)
    parts = make_parts()
    placements = {'base': (-41, -41), 'lid': (41, -41), 'rotor': (-41, 40),
                  **{name: (39, 17+i*17) for i, name in enumerate(WINGS)}}
    rows, plate = [], []
    for name, solid in parts.items():
        mesh, transform = print_mesh(solid, name)
        file = 'wing.stl' if name in WINGS else f'{name}.stl'
        if name not in WINGS or name == WINGS[0]:
            mesh.export(output / file)
        placed = mesh.copy()
        placed.apply_translation([*placements[name], 0])
        plate.append(placed)
        rows.append(dict(id=name, file=file, assembly_to_print=transform.tolist(),
                         plate_xy=list(placements[name])))
    trimesh.util.concatenate(plate).export(output / 'all-parts.stl')
    write_static(parts, output / 'expanded.glb', P['rotation_degrees'])
    write_static(parts, output / 'closed.glb', 0)
    write_assembly(parts, output / 'assembly.glb')
    render(parts, output / 'preview.png', degrees=P['rotation_degrees'])
    render(parts, output / 'closed.png')
    render(parts, output / 'exploded.png', exploded=True)
    (output / 'assembly.json').write_text(json.dumps(dict(
        parameters=P, parts=rows, lid_top_mm=LID_TOP,
        physical_print_test=False), ensure_ascii=False, indent=2)+'\n')
    print('Exported seven toy parts, static views and assembly guide', flush=True)


if __name__ == '__main__':
    main()
