"""Optional local P2S audit, kept independent of reproducible geometry builds."""
from tools.slicing import slicing_parser, configure_slicing

import json
from pathlib import Path
import re

import numpy as np
from PIL import Image, ImageDraw
import trimesh

from geometry import HERE, P, WINGS, LID_Z
from tools.slicing import audit_files, model_directory, save_report, slicing_workspace, source_hashes


from tools.slicing_geometry import check_archive_geometry, extrusion_segments

def extrusion_paths(gcode):
    by_layer = {}
    for z, a, b, feature in extrusion_segments(gcode, require_layer=True):
        if z > 0:
            by_layer.setdefault(z, []).append((a, b, feature))
    return by_layer

def inspect_paths(gcode, source, plate, output):
    paths = extrusion_paths(gcode)
    mesh = trimesh.load(source, force='mesh')
    bounds = plate['objects'][0]['bbox']
    shift = np.array([bounds['x'], bounds['y']])-mesh.bounds[0, :2]
    info = json.loads((source.parent / 'assembly.json').read_text())
    rows = {row['id']: row for row in info['parts']}
    probes = []

    def to_plate(name, points):
        row = rows[name]
        result = trimesh.transform_points(points, row['assembly_to_print'])[:, :2]
        return result + row['plate_xy'] + shift

    for angle in P['clip_angles']:
        a = np.radians(angle)
        points = np.array([[x, 33.8, LID_Z+1] for x in np.arange(-6, 6, .5)])
        points[:, :2] = points[:, :2] @ np.array([[np.cos(a), np.sin(a)], [-np.sin(a), np.cos(a)]])
        for z in np.arange(.2, 2.41, .2):
            probes.append((f'clip-{angle}', round(float(z), 2), to_plate('lid', points), .34))
    # Audit the narrower, shifted vertical stems and enlarged retaining heads,
    # not only the in-plane tongues. All coordinates are in the assembled frame.
    for angle in P['clip_angles']:
        a = np.radians(angle)
        rotation = np.array([[np.cos(a), np.sin(a)], [-np.sin(a), np.cos(a)]])
        for feature, y, layers in (
            ('stem', 34.0, np.arange(2.6, 6.41, .2)),
            ('catch', 34.65 + P['clip_deflection']/2, (5.6, 5.8)),
        ):
            points = np.array([[x, y, 4.15] for x in np.arange(4.3, 5.71, .2)])
            points[:, :2] = points[:, :2] @ rotation
            for z in layers:
                probes.append((f'clip-{angle}-{feature}', round(float(z), 2),
                               to_plate('lid', points), .34))
    # Pin cross-sections have concentric walls; query the mid-wall ring rather
    # than demanding extrusion at the potentially unfilled centre.
    for name in WINGS:
        a = WINGS.index(name)*np.pi/2
        points = np.array([[P['follower_start_radius']+1.15*np.cos(t), 1.15*np.sin(t), 5]
                           for t in np.linspace(0, 2*np.pi, 17)[:-1]])
        points[:, :2] = points[:, :2] @ np.array([[np.cos(a), np.sin(a)], [-np.sin(a), np.cos(a)]])
        for z in np.arange(2.6, 4.61, .2):
            probes.append((name+'-pin', round(float(z), 2), to_plate(name, points), .34))

    prepared = {}
    for z, segments in paths.items():
        starts = np.array([a for a, _, _ in segments])
        ends = np.array([b for _, b, _ in segments])
        prepared[z] = starts, ends-starts
    results = []
    for name, z, points, tolerance in probes:
        assert z in prepared, f'missing layer {z}'
        starts, vectors = prepared[z]
        denom = np.maximum(np.sum(vectors*vectors, axis=1), 1e-12)
        worst = 0.
        for point in points:
            t = np.clip(np.sum((point-starts)*vectors, axis=1)/denom, 0, 1)
            distance = float(np.linalg.norm(starts+t[:, None]*vectors-point, axis=1).min())
            assert distance < tolerance, f'{name} missing extrusion at Z={z}: {point}, gap {distance}'
            worst = max(worst, distance)
        results.append(dict(feature=name, layer_mm=z, probes=len(points),
                            maximum_distance_to_extrusion_mm=round(worst, 4)))
    # Record actual paths at representative critical heights for visual audit.
    canvas = Image.new('RGB', (1400, 1400), '#f2f0eb')
    draw = ImageDraw.Draw(canvas)
    for index, z in enumerate((.2, 1.2, 2.6, 4.6)):
        origin = np.array([index % 2 * 700 + 30, index // 2 * 700 + 50])
        draw.text(tuple(origin-[0, 25]), f'Z = {z:.1f} mm', fill='#263a44')
        for start, end, feature in paths.get(z, []):
            a = (np.array(start)-shift-mesh.bounds[0, :2])*4 + origin
            b = (np.array(end)-shift-mesh.bounds[0, :2])*4 + origin
            color = '#b36d35' if 'wall' in feature.lower() else '#338477'
            draw.line([tuple(a), tuple(b)], fill=color, width=1)
    canvas.save(output / 'critical-toolpaths.png')
    return results


SLICING = json.loads((Path(__file__).resolve().parents[1] / 'slicing.json').read_text())


def main():
    parser = slicing_parser(HERE, 'retractable-shuriken-slicing')
    args = parser.parse_args()
    root = slicing_workspace(HERE, args.output_dir)
    source = model_directory(HERE)
    files = ('all-parts.stl',)
    inputs = source_hashes(source, (*files, 'assembly.json'))
    if configure_slicing(args, root, source, files, inputs, SLICING):
        return
    def check(archive, config, gcode, plate, path):
        check_archive_geometry(archive, path)
        checks = inspect_paths(gcode, path, plate, root) if path.name == 'all-parts.stl' else []
        assert not any('support' in name.lower() and time > 0
                       for name, time in plate['feature_type_times'].items()), 'unexpected support paths'
        version = re.search(r'^;\s*BambuStudio\s+(\d+(?:\.\d+){2,3})\s*$', gcode, re.M)
        return dict(archive_geometry_matches=True, critical_extrusion_checks=checks,
                    gcode_producer_version=version.group(1) if version else None)

    common = audit_files(args.studio, root, source, files, inputs, arrange=SLICING['arrange'],
                         expected=SLICING['expected'],
                         callback=check, collect_only=args.collect_only)
    versions = {row['gcode_producer_version'] for row in common['plates']}
    if len(versions) == 1 and None not in versions:
        common['software'] = f'Bambu Studio {versions.pop()}'
        common['software_version_source'] = 'Audited G-code headers in both 3MF archives'
    report = dict(status='complete', printer='Bambu Lab P2S', nozzle_mm=.4, layer_mm=.2,
                  first_layer_mm=.2, supports=False, **common)
    save_report(root, report, source, inputs)
    print(json.dumps({key: report[key] for key in ('status', 'printer', 'software', 'physical_print_test')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
