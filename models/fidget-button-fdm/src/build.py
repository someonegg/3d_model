"""Four support-free PLA parts for a quiet, replaceable-flexure fidget button."""
from pathlib import Path
import os
import numpy as np
import trimesh
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('MODEL_OUTPUT_DIR', HERE))
NAME = 'fidget-button-fdm.stl'
SEGMENTS = 192


def revolve(profile, radial_mod=None):
    """Revolve a closed radial/Z polygon, preserving a single vertex on the axis."""
    angles = np.arange(SEGMENTS) * (2 * np.pi / SEGMENTS)
    vertices = []
    rings = []
    for profile_index, (radius, z) in enumerate(profile):
        if radius == 0:
            rings.append([len(vertices)] * SEGMENTS)
            vertices.append((0.0, 0.0, z))
        else:
            indices = []
            for angle in angles:
                indices.append(len(vertices))
                local_radius = radius + (radial_mod(profile_index, angle) if radial_mod else 0)
                vertices.append((local_radius * np.cos(angle), local_radius * np.sin(angle), z))
            rings.append(indices)
    faces = []
    for index in range(len(profile)):
        a = rings[index]
        b = rings[(index + 1) % len(profile)]
        if profile[index][0] == 0 and profile[(index + 1) % len(profile)][0] == 0:
            continue
        for sector in range(SEGMENTS):
            next_sector = (sector + 1) % SEGMENTS
            if profile[index][0] == 0:
                faces.append((a[sector], b[sector], b[next_sector]))
            elif profile[(index + 1) % len(profile)][0] == 0:
                faces.append((a[sector], b[sector], a[next_sector]))
            else:
                faces.extend(((a[sector], b[sector], b[next_sector]),
                              (a[sector], b[next_sector], a[next_sector])))
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.remove_unreferenced_vertices()
    if mesh.volume < 0:
        mesh.invert()
    return mesh


def spring(pitch=0.2):
    """Annular support with two opposed cantilevers, printed flat in XY."""
    coords = np.arange(-17.2 + pitch / 2, 17.2, pitch)
    x, y = np.meshgrid(coords, coords, indexing='ij')
    r = np.hypot(x, y)
    rim = (r <= 17.1) & (r >= 14.25)
    left = (x >= -16.2) & (x <= 2.5) & (y >= 3.3) & (y <= 5.3)
    right = (x <= 16.2) & (x >= -2.5) & (y <= -3.3) & (y >= -5.3)
    filled = rim | left | right
    # Square cells make exact, closed sidewalls without boolean operations.
    vertices, faces, lookup = [], [], {}

    def point(i, j, top):
        key = (i, j, top)
        if key not in lookup:
            lookup[key] = len(vertices)
            vertices.append((-17.2 + i * pitch, -17.2 + j * pitch, float(top)))
        return lookup[key]

    nx, ny = filled.shape
    for i, j in np.argwhere(filled):
        corners = ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))
        lower = [point(*corner, 0) for corner in corners]
        upper = [point(*corner, 1) for corner in corners]
        faces.extend(((upper[0], upper[1], upper[2]), (upper[0], upper[2], upper[3]),
                      (lower[0], lower[2], lower[1]), (lower[0], lower[3], lower[2])))
        exposed = (j == 0 or not filled[i, j - 1], i == nx - 1 or not filled[i + 1, j],
                   j == ny - 1 or not filled[i, j + 1], i == 0 or not filled[i - 1, j])
        for edge, is_exposed in enumerate(exposed):
            if is_exposed:
                next_edge = (edge + 1) % 4
                faces.extend(((lower[edge], lower[next_edge], upper[next_edge]),
                              (lower[edge], upper[next_edge], upper[edge])))
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    if mesh.volume < 0:
        mesh.invert()
    return mesh


def make_parts():
    # Shell prints with its top face on the bed; the cavity grows upward.
    shell = revolve([(13.0, 0), (21.0, 0), (21.0, 17.0),
                     (17.5, 17.0), (17.5, 2.5), (13.0, 2.5)])
    # Cap prints face down. Its annular pusher leaves room for the center stop.
    cap = revolve([(0, 0), (12.6, 0), (12.6, 4.0), (13.8, 4.0),
                   (13.8, 6.0), (6.0, 6.0), (6.0, 8.7),
                   (2.6, 8.7), (2.6, 6.0), (0, 6.0)])
    # The plug supports the spring rim and stops the cap after 1.5 mm of travel.
    def grip(profile_index, angle):
        # Six shallow compression ribs hold the serviceable cover in its bore.
        return 0.40 * max(0.0, np.cos(6 * angle)) ** 12 if profile_index in (4, 5) else 0.0

    plug = revolve([(0, 0), (21.0, 0), (21.0, 2.4), (17.25, 2.4),
                    (17.25, 3.0), (17.25, 10.4), (17.05, 11.2),
                    (14.0, 11.2), (14.0, 2.4), (3.0, 2.4),
                    (3.0, 10.7), (0, 10.7)], radial_mod=grip)
    return [('外壳', shell), ('按帽', cap), ('底盖', plug), ('弹片', spring())]


def draw_preview():
    canvas = Image.new('RGB', (1200, 650), '#f5f2eb')
    draw = ImageDraw.Draw(canvas)
    black, accent, pale = '#22313a', '#c78054', '#d7e3e4'
    draw.text((62, 46), 'FIDGET BUTTON  /  PLA  /  0.4 mm NOZZLE', fill=black)
    draw.text((62, 80), '42 mm diameter  |  1.5 mm travel  |  four printed parts', fill=black)
    # Left: assembled top view. Right: exploded section showing the actual interfaces.
    draw.ellipse((110, 158, 520, 568), fill=black)
    draw.ellipse((132, 180, 498, 546), fill='#e4dbce')
    draw.ellipse((189, 237, 441, 489), fill=accent)
    draw.text((226, 363), 'PRESS', fill='white')
    draw.text((185, 590), 'ASSEMBLED TOP VIEW', fill=black)
    cx = 850
    draw.rounded_rectangle((cx-182, 172, cx+182, 211), radius=12, fill=black)
    draw.rounded_rectangle((cx-110, 130, cx+110, 187), radius=22, fill=accent)
    draw.text((cx+126, 145), 'CAP', fill=black)
    draw.rounded_rectangle((cx-147, 258, cx+147, 276), radius=8, fill=pale, outline=black, width=3)
    draw.line((cx-125, 267, cx-23, 267), fill=accent, width=7)
    draw.line((cx+23, 267, cx+125, 267), fill=accent, width=7)
    draw.text((cx+160, 258), 'FLEXURE', fill=black)
    draw.rounded_rectangle((cx-182, 337, cx+182, 359), radius=8, fill=black)
    draw.rectangle((cx-150, 322, cx-117, 337), fill=black)
    draw.rectangle((cx+117, 322, cx+150, 337), fill=black)
    draw.text((cx+150, 338), 'BASE', fill=black)
    draw.line((cx, 205, cx, 249), fill=accent, width=3)
    draw.line((cx, 280, cx, 327), fill=accent, width=3)
    draw.text((655, 442), 'EXPLODED ASSEMBLY', fill=black)
    draw.text((653, 473), 'Printed flat; insert cap from below, then flexure and base.', fill=black)
    canvas.save(OUT / 'preview.png')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    parts = make_parts()
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
    draw_preview()


if __name__ == '__main__':
    main()
