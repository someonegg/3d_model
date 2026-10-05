"""Optional local P2S audit, kept independent of reproducible geometry builds."""
import argparse
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw
from scipy.spatial import cKDTree
import trimesh

from geometry import HERE, P, WINGS, LID_Z
from tools.slicing import (prepare_profiles, audit_files, model_directory, save_report,
                           slicing_workspace, source_hashes, studio_command)


def check_archive_geometry(archive, source):
    meshes = []
    for name in archive.namelist():
        if not name.endswith('.model'):
            continue
        for node in ET.fromstring(archive.read(name)).findall('.//{*}mesh'):
            vertices = [[float(v.attrib[k]) for k in ('x', 'y', 'z')]
                        for v in node.findall('./{*}vertices/{*}vertex')]
            faces = [[int(f.attrib[k]) for k in ('v1', 'v2', 'v3')]
                     for f in node.findall('./{*}triangles/{*}triangle')]
            meshes.append(trimesh.Trimesh(vertices, faces, process=False))
    actual = trimesh.util.concatenate(meshes)
    expected = trimesh.load(source, force='mesh', process=False)
    assert len(actual.faces) == len(expected.faces), 'stale archive mesh'
    for mesh in (actual, expected):
        mesh.apply_translation(-mesh.bounds.mean(axis=0))
    np.testing.assert_allclose(actual.extents, expected.extents, atol=2e-5)
    for a, b in ((actual, expected), (expected, actual)):
        distances, _ = cKDTree(a.triangles_center).query(b.triangles_center)
        assert max(distances) < 2e-5, '3MF differs from the current STL'


def extrusion_paths(gcode):
    position = np.zeros(4)
    relative_e, relative_xyz, layer, feature = True, False, 0., ''
    paths = []
    for line in gcode.splitlines():
        if line.startswith('; Z_HEIGHT:'):
            layer = round(float(line.split(':')[1]), 3)
        if line.startswith('; FEATURE:'):
            feature = line.split(':', 1)[1].strip()
        words = line.split(';', 1)[0].split()
        if not words:
            continue
        if words[0] in ('M82', 'M83'):
            relative_e = words[0] == 'M83'
        if words[0] in ('G90', 'G91'):
            relative_xyz = words[0] == 'G91'
        data = {'XYZE'.index(word[0]): float(word[1:]) for word in words[1:]
                if word[0] in 'XYZE' and len(word) > 1}
        if words[0] == 'G92':
            for axis, value in data.items():
                position[axis] = value
        if words[0] not in ('G0', 'G1', 'G2', 'G3'):
            continue
        old = position.copy()
        amount = data.get(3, 0.) if relative_e else data.get(3, old[3]) - old[3]
        for axis, value in data.items():
            relative = relative_e if axis == 3 else relative_xyz
            position[axis] = old[axis] + value if relative else value
        if amount <= 0 or layer <= 0:
            continue
        if words[0] in ('G2', 'G3'):
            offsets = {word[0]: float(word[1:]) for word in words[1:] if word[0] in 'IJP'}
            assert 'I' in offsets or 'J' in offsets, 'unsupported extruding arc without I/J centre'
            centre = old[:2] + [offsets.get('I', 0.), offsets.get('J', 0.)]
            radius = np.linalg.norm(old[:2] - centre)
            assert radius > 0, 'zero-radius extruding arc'
            start = math.atan2(old[1] - centre[1], old[0] - centre[0])
            end = math.atan2(position[1] - centre[1], position[0] - centre[0])
            direction = 1 if words[0] == 'G3' else -1
            sweep = direction * ((direction * (end - start)) % (2 * math.pi))
            if abs(sweep) < 1e-8:
                sweep = direction * 2 * math.pi
            sweep += direction * 2 * math.pi * (offsets.get('P', 1) - 1)
            # Approximate arc paths to <=0.005 mm sagitta and 0.25 mm length.
            max_angle = 2 * math.acos(max(-1., 1 - .005 / radius))
            count = max(1, math.ceil(abs(sweep) / max_angle), math.ceil(abs(sweep) * radius / .25))
            angles = np.linspace(start, start + sweep, count + 1)
            radii = np.linspace(radius, np.linalg.norm(position[:2] - centre), count + 1)
            points = centre + np.column_stack((np.cos(angles), np.sin(angles))) * radii[:, None]
            points[0], points[-1] = old[:2], position[:2]
            paths.extend((layer, a, b, feature) for a, b in zip(points, points[1:]))
        elif 0 in data or 1 in data:
            paths.append((layer, old[:2], position[:2].copy(), feature))
    by_layer = {}
    for z, a, b, feature in paths:
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
        for z in np.arange(.4, 2.41, .2):
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--studio', default='/Applications/BambuStudio.app/Contents/MacOS/BambuStudio')
    parser.add_argument('--profiles', type=Path, default=Path('/Applications/BambuStudio.app/Contents/Resources/profiles/BBL'))
    parser.add_argument('--output-dir', type=Path, default=HERE.parents[1] / 'tmp/retractable-shuriken-slicing')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--prepare-only', action='store_true', help='Write profiles and print direct Studio command arrays')
    mode.add_argument('--collect-only', action='store_true', help='Audit existing 3MF outputs against current STL')
    args = parser.parse_args()
    root = slicing_workspace(HERE, args.output_dir)
    source = model_directory(HERE)
    files = ('all-parts.stl',)
    inputs = source_hashes(source, (*files, 'assembly.json'))
    overrides = dict(layer_height='0.2', initial_layer_print_height='0.2', wall_loops='3',
                     sparse_infill_density='15%', enable_support='0', brim_type='no_brim',
                     outer_wall_speed=['45', '45', '45'], inner_wall_speed=['80', '80', '80'],
                     wall_generator='arachne', detect_thin_wall='0')
    if not args.collect_only:
        prepare_profiles(root, args.profiles, '0.20mm Standard @BBL P2S', overrides)
    if args.prepare_only:
        for name in files:
            output = root / Path(name).stem
            output.mkdir(exist_ok=True)
            print(json.dumps(studio_command(args.studio, root, output, source / name, arrange=1)))
        return

    def check(archive, config, gcode, plate, path):
        check_archive_geometry(archive, path)
        checks = inspect_paths(gcode, path, plate, root) if path.name == 'all-parts.stl' else []
        assert not any('support' in name.lower() and time > 0
                       for name, time in plate['feature_type_times'].items()), 'unexpected support paths'
        version = re.search(r'^;\s*BambuStudio\s+(\d+(?:\.\d+){2,3})\s*$', gcode, re.M)
        return dict(archive_geometry_matches=True, critical_extrusion_checks=checks,
                    gcode_producer_version=version.group(1) if version else None)

    common = audit_files(args.studio, root, source, files, inputs, arrange=1,
                         expected={'layer_height': '0.2', 'initial_layer_print_height': '0.2',
                                   'wall_loops': '3', 'enable_support': '0', 'wall_generator': 'arachne'},
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
