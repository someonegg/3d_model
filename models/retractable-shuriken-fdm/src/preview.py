"""Orthographic previews of actual meshes, using a software depth buffer."""
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from geometry import mesh_of, pose, WINGS
from assembly import COLORS


def render(parts, path, degrees=0, exploded=False):
    parts = pose(parts, degrees)
    canvas = Image.new('RGB', (1200, 1000), '#f2f0eb')
    colors = COLORS
    offsets = {'base': 0, 'rotor': 30, 'lid': 50,
               **{name: 15 for name in WINGS}} if exploded else {name: 0 for name in parts}
    # Orthographic mesh projection; the preview uses the exported solid surfaces.
    rows = []
    light = np.array([-.4, -.6, 1.0]); light /= np.linalg.norm(light)
    for name, solid in parts.items():
        m = mesh_of(solid)
        m.apply_translation((0, 0, offsets[name]))
        for tri, norm in zip(m.triangles, m.face_normals):
            view = np.array([1, -1, .9])
            if norm @ view <= .001:
                continue
            screen = np.column_stack((.75*tri[:, 0]+.75*tri[:, 1],
                                      .40*tri[:, 0]-.40*tri[:, 1]-tri[:, 2]))
            depth = tri @ view
            rgb = tuple(int(colors[name][i:i+2], 16) for i in (1, 3, 5))
            shade = .66 + .34*max(0, norm @ light)
            rows.append((depth, screen, tuple(int(c*shade) for c in rgb)))
    allpoints = np.vstack([r[1] for r in rows]); lo=allpoints.min(0); hi=allpoints.max(0)
    scale = min(1000/(hi[0]-lo[0]), 760/(hi[1]-lo[1]))
    center=(lo+hi)/2
    pixels = np.asarray(canvas).copy()
    depth_buffer = np.full((1000, 1200), -np.inf)
    for depths, points, color in rows:
        points=(points-center)*scale+np.array([600, 540])
        left, top=np.maximum(np.floor(points.min(0)).astype(int), [0, 0])
        right, bottom=np.minimum(np.ceil(points.max(0)).astype(int), [1199, 999])
        if right < left or bottom < top:
            continue
        xx, yy=np.meshgrid(np.arange(left, right+1)+.5, np.arange(top, bottom+1)+.5)
        (ax,ay),(bx,by),(cx,cy)=points
        denom=(by-cy)*(ax-cx)+(cx-bx)*(ay-cy)
        if abs(denom)<1e-9:
            continue
        u=((by-cy)*(xx-cx)+(cx-bx)*(yy-cy))/denom
        v=((cy-ay)*(xx-cx)+(ax-cx)*(yy-cy))/denom
        w=1-u-v
        z=u*depths[0]+v*depths[1]+w*depths[2]
        old=depth_buffer[top:bottom+1, left:right+1]
        mask=(u>=-1e-7)&(v>=-1e-7)&(w>=-1e-7)&(z>old)
        old[mask]=z[mask]
        pixels[top:bottom+1, left:right+1][mask]=color
    canvas=Image.fromarray(pixels)
    draw=ImageDraw.Draw(canvas)
    try:
        font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 32)
        small=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 22)
    except OSError:
        font=small=ImageFont.load_default()
    draw.text((50, 35), 'RETRACTABLE STAR  /  PLA', fill='#243640', font=font)
    draw.text((50, 85), 'EXPLODED ASSEMBLY' if exploded else ('102 mm EXPANDED' if degrees else '72 mm CLOSED'), fill='#526571', font=small)
    draw.text((50, 948), 'P2S  |  0.4 mm nozzle  |  Seven printed parts  |  Prototype', fill='#526571', font=small)
    canvas.save(path)

