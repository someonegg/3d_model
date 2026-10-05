"""Build the rounded transformable toy and two display states."""
import json
import os
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw

from geometry import mesh, parameters, parts, pose, print_transform, straight_length

COLORS = {'link-base': '#344655', 'terminal-base': '#344655',
          'link-lid': '#6fa6a8', 'terminal-lid': '#6fa6a8',
          'slider': '#dcab64', 'lock-pin': '#dcab64', 'star-head': '#b8795f'}


def rgba(name):
    value = COLORS[name].lstrip('#')
    return [int(value[i:i + 2], 16) for i in (0, 2, 4)] + [255]


def display(out, name, meshes, rows):
    scene = trimesh.Scene()
    for node, part, transform in rows:
        m = meshes[part].copy()
        m.visual = trimesh.visual.ColorVisuals(m, vertex_colors=rgba(part))
        # STL mm / Z up -> glTF metres / Y up, baked into vertex coordinates.
        m.apply_transform(transform)
        m.vertices = m.vertices[:, [0, 2, 1]] * [0.001, 0.001, -0.001]
        scene.add_geometry(m, node_name=node, geom_name=node)
    scene.export(out / name)


def preview(out, meshes, p):
    canvas = Image.new('RGB', (1440, 980), '#f5f2eb')
    draw = ImageDraw.Draw(canvas)
    draw.text((65, 35), 'TRANSFORMABLE STAR TOY  /  PLA  /  P2S 0.4', fill='#344655', font_size=25)
    states = [(pose(p), (75, 195), f'CLOSED  /  {straight_length(p):g} mm'),
              (pose(p, p['stroke_mm'], [15, -25, 30, -25, 15], 25), (75, 575),
               f'EXTENDED + BENT  /  {straight_length(p, p["stroke_mm"]):g} mm when straight')]
    # Orthographic mesh projection, not an invented illustration of the mechanism.
    for rows, origin, title in states:
        triangles = []
        for _, name, transform in rows:
            m = meshes[name].copy()
            m.apply_transform(transform)
            for triangle in m.triangles:
                triangles.append((float(triangle[:, 2].mean()), triangle, COLORS[name]))
        for _, triangle, color in sorted(triangles, key=lambda row: row[0]):
            xy = triangle[:, :2] * [4.65, -4.65] + origin
            draw.polygon([tuple(v) for v in xy], fill=color)
        draw.text((65, origin[1] + 140), title, fill='#344655', font_size=21)
    draw.text((65, 810), 'Stepped captive heads  |  solid end walls  |  broad paired tongues', fill='#344655', font_size=22)
    draw.text((65, 860), f"{p['body_height_mm']:g} mm body  /  print sliders recess-down ", fill='#344655', font_size=22)
    draw.text((65, 910), 'Physical holding force and durability remain untested.', fill='#344655', font_size=20)
    canvas.save(out / 'preview.png')


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
