"""Export actual printable parts, assembly scenes, layouts and mesh-derived previews."""
from pathlib import Path
import json
import os
import math
import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFont
from assembly import write_assembly
from geometry import P, COLORS, make_parts, make_coupon, mesh, open_door

HERE = Path(__file__).resolve().parents[1]


def prepared(part):
    result = mesh(part['solid'])
    rx, ry, rz = np.radians(part['rotation'])
    tf = trimesh.transformations.euler_matrix(rx, ry, rz)
    result.apply_transform(tf)
    result.apply_translation(-result.bounds[0])
    return result, tf


from preview import render, scene

def export_all(out):
    out.mkdir(parents=True, exist_ok=True)
    (out/'parts').mkdir(exist_ok=True)
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
    write_assembly(parts, out/'assembly.glb')
    scene(parts).export(out/'assembled.glb')
    scene(parts, 60).export(out/'doors-open.glb')
    render(parts, out/'preview.png')
    render(parts, out/'doors-open.png', 60)
    render(parts, out/'rear.png', rear=True)
    render(parts, out/'exploded.png', exploded=True)
    return parts, metadata, plate_rows


def main():
    export_all(Path(os.environ['MODEL_OUTPUT_DIR']))


if __name__ == '__main__':
    main()
