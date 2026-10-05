"""Build the rounded transformable toy and two display states."""
import json
import os
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw

from geometry import mesh, parameters, parts, pose, print_transform, straight_length

from preview import display, preview

def pack(entries, gap=5, max_width=220):
    """Deterministic shelf packing; each item is an independently closed part."""
    x, y, row_height = 0., 0., 0.
    plate, records = [], []
    for label, name, m in entries:
        width, height = m.extents[:2]
        if x and x + width > max_width:
            x, y, row_height = 0., y + row_height + gap, 0.
        translation = np.array([x, y, 0.]) - m.bounds[0]
        placed = m.copy()
        placed.apply_translation(translation)
        plate.append(placed)
        records.append(dict(id=label, part=name, translation_mm=translation.tolist(),
                            bounds_mm=placed.bounds.tolist()))
        x += width + gap
        row_height = max(row_height, height)
    return trimesh.util.concatenate(plate), records


def main():
    out = Path(os.environ['MODEL_OUTPUT_DIR'])
    out.mkdir(parents=True, exist_ok=True)
    p = parameters()
    meshes = {name: mesh(value) for name, value in parts(p).items()}
    printable = {}
    for name, m in meshes.items():
        printed = m.copy()
        printed.apply_transform(print_transform(name, p))
        if not printed.is_volume or len(printed.split()) != 1:
            raise ValueError(f'{name}: must be one closed printable solid')
        printed.export(out / f'{name}.stl')
        printable[name] = printed
    counts = {'link-base': 5, 'terminal-base': 1, 'link-lid': 5,
              'terminal-lid': 1, 'slider': 5, 'star-head': 1, 'lock-pin': 13}
    entries = [(f'{name}-{i + 1}', name, printable[name])
               for name, count in counts.items() for i in range(count)]
    plate, layout = pack(entries)
    plate.export(out / 'all-parts.stl')
    closed = pose(p)
    extended = pose(p, p['stroke_mm'])
    display(out, 'closed.glb', meshes, closed)
    display(out, 'extended.glb', meshes, pose(p, p['stroke_mm'], [15, -25, 30, -25, 15], 25))
    preview(out, meshes, p)
    data = dict(parameters=p, counts=counts, layout=layout,
                print_transforms={name: print_transform(name, p).tolist() for name in meshes},
                closed=[dict(id=node, part=name, matrix=matrix.tolist()) for node, name, matrix in closed],
                extended_straight=[dict(id=node, part=name, matrix=matrix.tolist()) for node, name, matrix in extended])
    (out / 'geometry.json').write_text(json.dumps(data, indent=2) + '\n')
    print(f'Built {sum(counts.values())} printed parts and two display states')


if __name__ == '__main__':
    main()
