"""Export actual printable parts, assembly scenes, layouts and mesh-derived previews."""
from pathlib import Path
import json
import os
import math
import zipfile
import shutil
import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFont
from geometry import P, COLORS, make_parts, make_coupon, mesh, open_door

HERE = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get('MODEL_OUTPUT_DIR', HERE))


def prepared(part):
    result = mesh(part['solid'])
    rx, ry, rz = np.radians(part['rotation'])
    tf = trimesh.transformations.euler_matrix(rx, ry, rz)
    result.apply_transform(tf)
    result.apply_translation(-result.bounds[0])
    return result, tf


def render(parts, destination, angle=0, exploded=False, rear=False):
    width, height, ss = 1500, 960, 2
    canvas = Image.new('RGB', (width*ss, height*ss), '#e9edef')
    draw = ImageDraw.Draw(canvas)
    direction = np.array([.9 if rear else -.95, -1.35, .84])
    direction /= np.linalg.norm(direction)
    right = np.cross([0, 0, 1], direction); right /= np.linalg.norm(right)
    up = np.cross(direction, right)
    basis = np.array([right, up, direction]).T
    meshes = []
    for part in parts:
        shape = part['solid']
        if angle and part['group'].startswith('door-'):
            shape = open_door(shape, 1 if part['group']=='door-left' else -1, angle)
        obj = mesh(shape)
        if exploded:
            n = part['name']
            if n == 'body': obj.apply_translation((0, 0, 43))
            elif part['group'].startswith('door-'):
                obj.apply_translation((0, 34 if part['group']=='door-left' else -34, 25))
            elif part['group']=='wheel':
                obj.apply_translation((0, 26*np.sign(obj.centroid[1]), -8))
            elif n in ['interior','dashboard']: obj.apply_translation((0, 0, 18))
            elif n != 'chassis': obj.apply_translation((0, 0, 43))
        meshes.append((obj, COLORS[part['color']]))
    all_pts = np.concatenate([obj.vertices@basis for obj, _ in meshes])
    lo, hi = all_pts.min(0), all_pts.max(0)
    scale = min((width-150)/(hi[0]-lo[0]), (height-250)/(hi[1]-lo[1]))*ss
    center = (lo+hi)/2
    pixels = np.asarray(canvas).copy()
    depth = np.full((height*ss, width*ss), -np.inf, dtype=np.float32)
    light = np.array([-.5, -.6, 1]); light /= np.linalg.norm(light)
    for obj, color in meshes:
        projected = obj.vertices@basis
        xy = (projected[:, :2]-center[:2])*[scale, -scale]+[width*ss/2, height*ss*.55]
        for face, normal in zip(obj.faces, obj.face_normals):
            if normal@direction <= .001: continue
            tri = xy[face]
            xmin,ymin = np.maximum(np.floor(tri.min(0)).astype(int), 0)
            xmax,ymax = np.minimum(np.ceil(tri.max(0)).astype(int), [width*ss-1,height*ss-1])
            if xmax < xmin or ymax < ymin: continue
            a,b,c=tri
            det=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
            if abs(det)<1e-10: continue
            yy,xx=np.mgrid[ymin:ymax+1,xmin:xmax+1]
            u=((b[1]-c[1])*(xx+.5-c[0])+(c[0]-b[0])*(yy+.5-c[1]))/det
            v=((c[1]-a[1])*(xx+.5-c[0])+(a[0]-c[0])*(yy+.5-c[1]))/det
            w=1-u-v
            z=u*projected[face[0],2]+v*projected[face[1],2]+w*projected[face[2],2]
            region=depth[ymin:ymax+1,xmin:xmax+1]
            visible=(u>=-1e-6)&(v>=-1e-6)&(w>=-1e-6)&(z>region)
            lighting=.56+.44*max(0,normal@light)
            pixels[ymin:ymax+1,xmin:xmax+1][visible]=[int(v*lighting) for v in color[:3]]
            region[visible]=z[visible]
    canvas=Image.fromarray(pixels)
    draw=ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 36*ss)
        small = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 19*ss)
    except OSError:
        font = small = ImageFont.load_default(size=24*ss)
    draw.text((55*ss, 34*ss), 'VOLVO XC60 / 2022', font=font, fill='#263540')
    state = 'EXPLODED ASSEMBLY' if exploded else ('FRONT DOORS / 60 DEG' if angle else 'ZHIYUAN LUXURY / 1:24')
    draw.text((57*ss, 90*ss), state, font=small, fill='#657580')
    draw.text((57*ss, 914*ss), '196.2 mm  |  PLA  |  0.4 mm nozzle  |  Mesh-derived preview', font=small, fill='#657580')
    canvas.resize((width, height), Image.Resampling.LANCZOS).save(destination)


def scene(parts, angle=0):
    result = trimesh.Scene()
    for part in parts:
        shape = part['solid']
        if part['group'].startswith('door-'):
            shape = open_door(shape, 1 if part['group']=='door-left' else -1, angle)
        obj = mesh(shape)
        obj.visual = trimesh.visual.ColorVisuals(obj, vertex_colors=COLORS[part['color']])
        # GLB uses metres and Y-up.
        obj.apply_transform(trimesh.transformations.rotation_matrix(-math.pi/2, [1, 0, 0]))
        obj.apply_scale(.001)
        result.add_geometry(obj, node_name=part['name'], geom_name=part['name'])
    return result


def export_all(out):
    out.mkdir(parents=True, exist_ok=True)
    (out/'parts').mkdir(exist_ok=True)
    if out.resolve() != HERE:
        shutil.copyfile(HERE/'references.md',out/'references.md')
    parts = make_parts()
    print(f'Exporting {len(parts)} printable parts', flush=True)
    metadata = []
    layouts = {}
    for part in parts:
        obj, rotation = prepared(part)
        obj.export(out/'parts'/f"{part['name']}.stl")
        assembly = mesh(part['solid'])
        translated_min = trimesh.transform_points(assembly.vertices, rotation).min(0)
        rotation[:3, 3] = -translated_min
        metadata.append(dict(name=part['name'], color=part['color'], group=part['group'],
                             assembly_to_print=rotation.tolist(), bounds=assembly.bounds.tolist(),
                             dimensions=obj.extents.tolist(), components=len(part['solid'].decompose())))
        layouts.setdefault(part['color'], []).append((part['name'], obj))
    # Shelf-pack with 6 mm between bounding boxes and 8 mm border, separate by color.
    plate_rows = []
    for color, group in layouts.items():
        x = y = 8.; row_h = 0.; page = 1; current = []
        names = []
        def flush():
            filename = f'plate-{color}-{page}.stl'
            trimesh.util.concatenate(current).export(out/filename)
            plate_rows.append(dict(file=filename, color=color, parts=list(names)))
        for name, original in sorted(group, key=lambda row: -row[1].extents[1]):
            obj = original.copy(); w, h = obj.extents[:2]
            if max(w, h) > 240:
                raise ValueError(f'{name} exceeds plate')
            if x+w > 248:
                x = 8; y += row_h+6; row_h=0
            if y+h > 248:
                flush(); page+=1; x=y=8.; row_h=0; current=[]; names=[]
            obj.apply_translation((x, y, 0)); current.append(obj); names.append(name)
            x += w+6; row_h=max(row_h,h)
        if current: flush()
    coupon = trimesh.util.concatenate([mesh(v) for v in make_coupon()])
    coupon.apply_translation(-coupon.bounds[0]); coupon.export(out/'fit-coupon.stl')
    (out/'assembly.json').write_text(json.dumps({'parameters':P, 'parts':metadata, 'plates':plate_rows}, indent=2)+'\n')
    scene(parts).export(out/'assembled.glb')
    scene(parts, 60).export(out/'doors-open.glb')
    render(parts, out/'preview.png')
    render(parts, out/'doors-open.png', 60)
    render(parts, out/'rear.png', rear=True)
    render(parts, out/'exploded.png', exploded=True)
    # Complete STL bundle; fixed archive timestamps keep rebuilds reproducible.
    with zipfile.ZipFile(out/'print-files.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        files = sorted((out/'parts').glob('*.stl')) + [out/p['file'] for p in plate_rows] + [out/name for name in ['fit-coupon.stl','assembly.json','assembled.glb','doors-open.glb','preview.png','doors-open.png','exploded.png','rear.png','references.md']]+[HERE/'README.md']
        for file in files:
            name = 'parts/'+file.name if file.parent.name=='parts' else file.name
            entry=zipfile.ZipInfo(name, date_time=(2022,1,1,0,0,0));entry.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(entry,file.read_bytes())
    (out/'slicing-validation.json').write_text(json.dumps({'status':'not-run','reason':'Geometry rebuilt; run src/slice.py to check these exact STL files.'},indent=2)+'\n')
    return parts, metadata, plate_rows


def main():
    export_all(OUT)


if __name__ == '__main__':
    main()
