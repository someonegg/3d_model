"""Orchestrate model exports and public previews."""
from pathlib import Path
import os
import json
import trimesh
from geometry import P, NAMES, PLACEMENTS, make_parts, printing, mesh_of
from preview import render
from assembly import write_assembly

def main():
    out = Path(os.environ['MODEL_OUTPUT_DIR'])
    out.mkdir(parents=True, exist_ok=True)
    parts = make_parts()
    plate = []
    rows = []
    for name, part in parts.items():
        mesh, transform = printing(part, name)
        mesh.export(out / f'{name}.stl')
        x, y = PLACEMENTS[name]
        mesh.apply_translation((x, y, 0))
        plate.append(mesh)
        rows.append(dict(id=name, name=NAMES[name], file=f'{name}.stl', assembly_to_print=transform.tolist(), plate_xy=[x, y]))
    trimesh.util.concatenate(plate).export(out / 'all-parts.stl')
    write_assembly(parts, mesh_of, out / 'assembly.glb')
    render(parts, out / 'preview.png')
    render(parts, out / 'exploded.png', True)
    (out / 'assembly.json').write_text(json.dumps(dict(parameters=P, parts=rows, physical_print_test=False), ensure_ascii=False, indent=2) + '\n')
if __name__ == '__main__':
    main()
