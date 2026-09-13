"""Independent six-piece keyboard fidget; assembly coordinates are millimetres."""
from pathlib import Path
import json
import os
import numpy as np
import manifold3d as mf
import trimesh
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('MODEL_OUTPUT_DIR', HERE))
P = dict(body=32.0, shell_height=18.0, key=24.0, key_top=25.0,
         travel=3.0, guide_clearance=0.25, spring_thickness=0.8,
         spring_width=2.4, spring_length=18.0, spring_preload=0.1,
         click_width=0.8, click_length=14.4, click_thickness=0.8,
         click_deflection=0.55, hole=4.0)
NAMES = {'shell': '外壳', 'keycap': '方形键帽', 'plunger': '导向柱',
         'base': '滑动底盖', 'return-spring': '回弹片', 'click-spring': '段落弹舌'}


def rect(w, d, r=0):
    if not r:
        return mf.CrossSection.square((w, d), center=True)
    return mf.CrossSection.square((w-2*r, d-2*r), center=True).offset(r, circular_segments=32)


def box(w, d, h, x=0, y=0, z=0, r=0):
    return rect(w, d, r).extrude(h).translate((x, y, z))


def corner_cut(total):
    return mf.CrossSection([[(total-8, 8), (12, total-12), (12, 8)]])


def guide_profile():
    gap=P['guide_clearance']
    return rect(18+2*gap, 8+2*gap, .65) - corner_cut(11+gap*2**.5)


def prism_xz(points, y0, y1):
    # A planar XZ outline extruded along Y.
    return mf.CrossSection([points]).extrude(y1-y0).rotate((90, 0, 0)).translate((0, y1, 0))


def peg(z):
    shape = box(10, 6, 3, z=z, r=.4)
    for side in (-1, 1):
        for y in (-1.6, 1.6):
            rib = prism_xz([(4.9, z+.25), (5.3, z+.65), (5.3, z+2.1),
                            (5.0, z+2.75), (4.9, z+2.75)], y-.3, y+.3)
            shape += rib if side == 1 else rib.mirror((1, 0, 0))
    return shape


def make_parts():
    # Top-down printing leaves the large inner cavity open upwards.
    shell = box(P['body'], P['body'], P['shell_height'], r=3)
    shell -= box(28.4, 28.4, 14, z=-1, r=1)
    shell -= guide_profile().extrude(7).translate((0, 0, 12))
    shell -= box(4, 28.4, 7.55, x=15.5, z=-1)
    for side in (-1, 1):
        shell -= box(31, 1.5, 1.2, x=1.3, y=side*14.55, z=.65)
        shell -= box(2.5, .8, .8, x=12, y=side*14.2, z=1.85)
    # Four roof-connected stops constrain the replaceable cartridge stack.
    for x in (-12.7, 12.7):
        for y in (-12.7, 12.7):
            shell += box(3, 3, 3.05, x=x, y=y, z=9.95)
    shell += prism_xz([(-14.5, 6.3), (-12.4, 6.3), (-12.4, 9.8),
                       (-14.2, 11.6), (-14.5, 11.6)], -.5, .5)
    ear = box(9.4, 8.8, 5, x=-18.3, z=13, r=3)
    ear -= mf.Manifold.cylinder(7, 2, 2, 48).translate((-18.6, 0, 12))
    shell += ear

    cap = box(P['key'], P['key'], 3.2, z=21, r=2)
    cap += rect(24, 24, 2).extrude(.8, scale_top=(22.4/24, 22.4/24)).translate((0, 0, 24.2))
    cap -= box(10.4, 6.4, 4.2, z=20, r=.6)

    plunger = box(18, 8, 6, z=11, r=.5) + peg(21)
    plunger += rect(18, 8, .5).extrude(4, scale_top=(10/18, 6/8)).translate((0, 0, 17))
    for side in (-1, 1):
        plunger += box(1.6, 2, 4, x=side*7.8, y=side*2.6, z=7, r=.25)
    # Retention tabs only on Y sides: they must not intersect the X-side cam followers.
    tab = prism_xz([(3.8, 12.1), (4.7, 13), (3.8, 13)], -7, 7).rotate((0, 0, 90))
    plunger += tab + tab.mirror((0, 1, 0))
    cam = prism_xz([(8.8, 10.3), (9, 10.3), (9.8, 11), (9.8, 11.3),
                    (9, 11.9), (8.8, 11.9)], 1.5, 2.5)
    plunger += cam + cam.mirror((1, 0, 0))
    plunger -= corner_cut(11).extrude(10).translate((0, 0, 13))

    base = box(30, 27.9, 2.4, x=1, r=.8) + box(1.8, 27.9, 6.3, x=15.1)
    for side in (-1, 1):
        base += box(30, 1.1, .7, x=1, y=side*14.45, z=.9)
        # Small detents, on long isolated tongues, hold the sliding cover closed.
        bump = mf.CrossSection([[(13, 13.85), (12, 14.35), (11, 13.85)]]).extrude(.5).translate((0, 0, 1.9))
        base += bump if side == 1 else bump.mirror((0, 1, 0))
        base -= box(13, .6, 8, x=10.5, y=side*12.85, z=-.5)
    for x, y in ((-12.8, 0), (12.8, 0), (0, -12.8), (0, 12.8)):
        base += box(2, 2, 3.9, x=x, y=y, z=2.4)
    # Fingernail recess on the outward-facing edge.
    base -= box(1.6, 7, 1.0, x=16, z=5.2, r=.3)

    frame = rect(27.6, 27.6, .8) - rect(24.8, 24.8, .4)
    frame -= rect(2.2, 1.6).translate((-13.3, 0))
    spring2d = frame
    for side in (-1, 1):
        beam = rect(21.3, P['spring_width'], .6).translate((-2.15, 2.6))
        root = mf.CrossSection.circle(1.8, 32).translate((-12.4, 2.6))
        # Root blends stay inside the frame envelope.
        arm = (beam + root) ^ rect(27.6, 27.6, .8)
        spring2d += arm if side == 1 else arm.rotate(180)
    spring = spring2d.extrude(P['spring_thickness']).translate((0, 0, 7.1-P['spring_thickness']))

    click2d = frame
    for side in (-1, 1):
        arm = rect(P['click_width'], 16.3, .2).translate((11, -4.65))
        arm += rect(2.15, 1, .2).translate((10.325, 2.0))
        arm += mf.CrossSection.circle(.9, 24).translate((11, -12.4))
        # Rigid strike tongue, 0.35 mm from the relaxed beam. Dynamic overshoot
        # may strike it; audible output is deliberately a physical-test criterion.
        strike = rect(1, 10.3, .2).translate((9.75, 7.85))
        group = arm + strike
        click2d += group if side == 1 else group.mirror((1, 0))
    click = click2d.extrude(P['click_thickness']).translate((0, 0, 9))
    for x in (-12.7, 12.7):
        for y in (-12.7, 12.7):
            foot = box(2, 2, 1.9, x=x, y=y, z=7.1)
            click += foot
    return dict(shell=shell, keycap=cap, plunger=plunger, base=base,
                **{'return-spring': spring, 'click-spring': click})


def mesh_of(solid):
    raw = solid.to_mesh()
    result = trimesh.Trimesh(np.asarray(raw.vert_properties)[:, :3], np.asarray(raw.tri_verts), process=True)
    result.remove_unreferenced_vertices()
    return result


def printing(solid, name):
    m = mesh_of(solid)
    rotation = 180 if name in ('shell', 'keycap', 'plunger', 'click-spring') else 0
    matrix = trimesh.transformations.rotation_matrix(np.radians(rotation), [1, 0, 0])
    m.apply_transform(matrix)
    matrix2 = trimesh.transformations.translation_matrix([0, 0, -m.bounds[0, 2]])
    m.apply_transform(matrix2)
    return m, matrix2 @ matrix


def fit_coupon():
    gauge = box(22.5, 12.5, 5, r=.8) - guide_profile().extrude(7).translate((0, 0, -1))
    gauge += box(14.4, 10.4, 5, x=17.8, r=.8) - box(10.4, 6.4, 4, x=17.8, z=1.8, r=.6)
    gauge += box(2, 5, 5, x=11)
    sample = (box(18, 8, 5, r=.5) - corner_cut(11).extrude(5)) + peg(5)
    a, b = mesh_of(gauge), mesh_of(sample)
    b.apply_translation((0, 20, 0))
    return trimesh.util.concatenate((a, b))


def render(parts, path, exploded=False):
    canvas = Image.new('RGB', (1200, 1000), '#f2f0eb')
    draw = ImageDraw.Draw(canvas)
    colors = dict(shell='#354d5a', keycap='#efad61', plunger='#cf8d52', base='#728995',
                  **{'return-spring': '#55a797', 'click-spring': '#c7a367'})
    offsets = dict(shell=0, keycap=31, plunger=18, base=-40,
                   **{'return-spring': -26, 'click-spring': -13}) if exploded else {k:0 for k in parts}
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
    draw.text((50, 35), 'KEYBOARD FIDGET  /  PLA', fill='#243640', font=font)
    draw.text((50, 85), 'EXPLODED ASSEMBLY' if exploded else '24 mm SQUARE KEY  /  3 mm TRAVEL', fill='#526571', font=small)
    draw.text((50, 948), 'P2S  |  0.4 mm nozzle  |  Six printed parts  |  Prototype', fill='#526571', font=small)
    canvas.save(path)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/'slicing-validation.json').write_text(json.dumps(dict(status='not-run', reason='Geometry rebuilt; run src/slice.py for these STL files.', physical_print_test=False), indent=2)+'\n')
    parts = make_parts()
    placements = dict(shell=(-32, -27), keycap=(14, -27), plunger=(47, -27),
                      base=(-32, 18), **{'return-spring': (9, 18), 'click-spring': (49, 18)})
    plate=[]; rows=[]
    for name, solid in parts.items():
        m, transform=printing(solid, name)
        m.export(OUT/f'{name}.stl')
        x,y=placements[name]; m.apply_translation((x,y,0)); plate.append(m)
        rows.append(dict(id=name, name=NAMES[name], file=f'{name}.stl',
                         assembly_to_print=transform.tolist(), plate_xy=[x,y]))
    trimesh.util.concatenate(plate).export(OUT/'all-parts.stl')
    fit_coupon().export(OUT/'fit-coupon.stl')
    render(parts, OUT/'preview.png'); render(parts, OUT/'exploded.png', True)
    (OUT/'assembly.json').write_text(json.dumps(dict(parameters=P, parts=rows,
        physical_print_test=False), ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
