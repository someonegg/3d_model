"""Mesh-derived display scenes and public preview."""
import numpy as np
import trimesh
from PIL import Image, ImageDraw
from geometry import pose, straight_length

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


