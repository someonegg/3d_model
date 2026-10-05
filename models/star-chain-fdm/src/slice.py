"""Optional P2S slicing audit; no writes to model or published directories."""
from tools.slicing import slicing_parser, configure_slicing

import json
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw

from tools.slicing import audit_files, model_directory, save_report, slicing_workspace, source_hashes
from geometry import detent_profile_radius, detent_recess_profile, neck_z, slider_top

HERE = Path(__file__).resolve().parents[1]


from tools.slicing_geometry import check_archive_geometry as _check_archive_geometry, extrusion_segments

def check_archive_geometry(archive, source):
    _check_archive_geometry(archive, source, tolerance=3e-5)

def extrusion_paths(gcode, *, with_width=False):
    return extrusion_segments(gcode, with_width=with_width, require_layer=True)

def crosses_rectangle(a, b, lower, upper):
    delta = b - a
    start, end = 0., 1.
    for axis in range(2):
        if abs(delta[axis]) < 1e-10:
            if not lower[axis] <= a[axis] <= upper[axis]:
                return False
        else:
            bounds = sorted(((lower[axis] - a[axis]) / delta[axis],
                             (upper[axis] - a[axis]) / delta[axis]))
            start, end = max(start, bounds[0]), min(end, bounds[1])
            if start > end:
                return False
    return True


def require_gap(paths, z, xy, lower, upper, label):
    for layer, a, b, *_ in paths:
        if layer == z:
            assert not crosses_rectangle(a - xy, b - xy, lower, upper), f'fused {label} at Z={z}'


def layers(start, end):
    return np.round(np.arange(start, end + .001, .2), 3)


def inspect_paths(gcode, source, metadata, plate, output):
    paths = extrusion_paths(gcode, with_width=True)
    by_layer = {}
    for path in paths:
        by_layer.setdefault(path[0], []).append(path)
    layer_arrays = {}
    for z, rows in by_layer.items():
        starts = np.array([row[1] for row in rows])
        ends = np.array([row[2] for row in rows])
        assert all(row[4] is not None and row[4] > 0 for row in rows), f'missing line width at Z={z}'
        layer_arrays[z] = (starts, ends-starts, (starts+ends)/2, np.array([row[4] for row in rows]))
    checks, tips = [], []
    layout = metadata['layout']
    p = metadata['parameters']
    m = trimesh.load(source, force='mesh')
    # --arrange 1 translates the intact plate object; auto orientation is disabled.
    bounds = plate['objects'][0]['bbox']
    shift = np.array([bounds['x'], bounds['y']]) - m.bounds[0, :2]
    canvas = Image.new('RGB', (1400, 1400), '#f5f2eb')
    draw = ImageDraw.Draw(canvas)
    first_layers = [(a, b) for _, a, b, *_ in by_layer.get(.2, [])]
    for a, b in first_layers:
        draw.line([tuple((a - shift) * 5 + [80, 80]), tuple((b - shift) * 5 + [80, 80])],
                  fill='#6fa6a8', width=2)
    for row in layout:
        name = row['part']
        xy = np.array(row['translation_mm'][:2]) + shift
        probes = []
        local_layers = {}
        if name == 'slider':
            head_x = p['link_length_mm'] + p['closed_pivot_x_mm']
            anchor_x = (p['anchor_start_x_mm'] + p['anchor_end_x_mm']) / 2
            for z in layers(.2, slider_top(p) - p['slider_z_mm']):
                probes.append((z, np.array([[anchor_x, y] for y in (-2, 0, 2)]), 'solid fixed anchor'))
            profile = np.array(detent_recess_profile(p))
            for z in layers(.2, p['detent_depth_mm'] - .1):
                require_gap(by_layer.get(z, []), z, xy, [head_x-.25, -.25],
                            [head_x+.25, .25], 'detent bowl')
                radius = np.interp(z-.1, profile[:, 1], profile[:, 0])
                probes.append((z, np.array([[head_x + radius + .15, 0],
                                           [head_x - radius - .15, 0]]), 'detent bowl walls'))
            for z in layers(.2, p['slider_thickness_mm']):
                # Probe inside the fillet after first-layer edge compensation,
                # beyond the straight neck but within the extruded wall width.
                probes.append((z, np.array([[p['anchor_end_x_mm']+.2, sign*(p['neck_width_mm']/2+.1)]
                                           for sign in (-1, 1)]), 'fixed anchor neck fillet'))
                probes.append((z, np.array([[x, 0] for x in np.linspace(p['anchor_end_x_mm'] + .5,
                    head_x - p['disc_radius_mm'] + .5, 24)]), 'slider neck'))
            for z in layers(p['slider_thickness_mm'] + .2, slider_top(p) - p['slider_z_mm']):
                probes.append((z, np.array([[head_x - 2, 0], [head_x, 0], [head_x + 2, 0]]), 'lower capture head'))
        elif name.endswith('lid'):
            start, end = p['flag_start_x_mm'], p['flag_end_x_mm']
            half, slit = p['flag_width_mm'] / 2, p['flag_slit_mm']
            for z in layers(.2, p['flag_thickness_mm']):
                probes.append((z, np.array([[x, 0] for x in np.linspace(start + .5, end - .5, 30)]), 'detent flag'))
                for sign in (-1, 1):
                    centre = sign * (half + slit / 2)
                    require_gap(by_layer.get(z, []), z, xy, [start + .5, centre - .1], [end - .5, centre + .1], 'detent slit')
                require_gap(by_layer.get(z, []), z, xy, [end + slit / 2 - .1, -half + .5],
                            [end + slit / 2 + .1, half - .5], 'detent end slit')
            bump_height = p['body_height_mm'] - slider_top(p) + p['detent_interference_mm']
            for z in layers(p['flag_thickness_mm'] + .2, np.floor(bump_height / .2 + 1e-6) * .2):
                # Follow the narrowing dome, sampling the middle of each layer.
                # Concentric walls need not run through the centre.
                x = p['closed_pivot_x_mm']
                radius = .65 * detent_profile_radius(z - p['flag_thickness_mm'] - .1, p)
                probes.append((z, np.array([[x - radius, 0], [x + radius, 0], [x, -radius], [x, radius]]), 'detent dome'))
            tip = max(z for z, a, b, *_ in paths if z > p['flag_thickness_mm'] and
                      np.linalg.norm((a + b) / 2 - xy - [p['closed_pivot_x_mm'], 0]) < 1)
            assert abs(tip - bump_height) <= .101, f'{row["id"]}: missing or excessive detent tip height'
            tips.append(dict(part=row['id'], nominal_interference_mm=p['detent_interference_mm'],
                             printed_tip_z_mm=tip,
                             printed_interference_mm=round(tip - (p['body_height_mm'] - slider_top(p)), 3)))
        elif name == 'lock-pin':
            top = 1.2 + p['pin_shaft_length_mm']
            for z in layers(1.4, top):
                # Concentric walls need not have a toolpath through the axis.
                probes.append((z, np.array([[x, y] for radius in (.45, .95)
                    for x, y in ((radius, 0), (-radius, 0), (0, radius), (0, -radius))]),
                    'straight pin shaft walls'))
        elif name == 'link-base' or name == 'terminal-base':
            for sign in (-1, 1):
                y = sign * 6.8
                probes.append((.8, np.array([[1, y], [2, y]]), 'locator socket floor'))
                for z in layers(2.4, p['base_height_mm']):
                    require_gap(by_layer.get(z, []), z, xy, [.85, y - .15],
                                [1.15, y + .15], 'locator socket')
                if name == 'link-base':
                    for z in layers(2, p['base_height_mm'] - p['locator_vertical_clearance_mm']):
                        probes.append((z, np.array([[p['link_length_mm']+.4, y]]), 'locator tongue root'))
                    for z in layers(np.ceil((p['locator_bottom_mm'] + p['locator_engagement_mm'] + .2) / .2) * .2, p['base_height_mm'] - p['locator_vertical_clearance_mm']):
                        probes.append((z, np.array([[p['link_length_mm'] + p['locator_engagement_mm'] - .2, y]]), 'locator tongue tip'))
            probes.append((1., np.array([[x, 0] for x in np.linspace(1, 17, 25)]), 'receiver floor'))
            wall_top = neck_z(p) - .3
            for z in layers(p['floor_mm'] + .2, wall_top):
                probes.append((z, np.array([[p['capture_wall_mm'] / 3, 0],
                                           [2 * p['capture_wall_mm'] / 3, 0]]), 'solid capture wall'))
            for z in layers(wall_top + .2, p['base_height_mm']):
                require_gap(by_layer.get(z, []), z, xy, [.4, -.5], [.8, .5], 'upper neck mouth')
            if name == 'link-base':
                anchor_x = (p['anchor_start_x_mm'] + p['anchor_end_x_mm']) / 2
                front_wall_x = (p['closed_pivot_x_mm'] + p['disc_radius_mm'] + p['anchor_start_x_mm']) / 2
                rear_wall_x = (p['anchor_end_x_mm'] + p['clearance_per_side_mm'] + p['link_length_mm']) / 2
                for z in layers(p['floor_mm'] + .2, p['base_height_mm']):
                    require_gap(by_layer.get(z, []), z, xy, [anchor_x-.3, -.3],
                                [anchor_x+.3, .3], 'post-free anchor pocket')
                    probes.append((z, np.array([[front_wall_x, 0]]), 'fixed anchor front wall'))
                for z in layers(p['floor_mm'] + .2, wall_top):
                    probes.append((z, np.array([[rear_wall_x, 0]]), 'fixed anchor rear wall'))
        if name.endswith('lid'):
            for sign in (-1, 1):
                for z in layers(.2, p['body_height_mm']-p['base_height_mm']):
                    probes.append((z, np.array([[.7, sign*6.8]]), 'socket roof'))
        if name.endswith(('base', 'lid')):
            limit = p['base_height_mm'] if name.endswith('base') else p['body_height_mm']-p['base_height_mm']
            for z in layers(1., limit):
                for sign in (-1, 1):
                    require_gap(by_layer.get(z, []), z, xy,
                                [p['pin_x_mm']-.5, sign*6.8-.5],
                                [p['pin_x_mm']+.5, sign*6.8+.5], 'relocated pin bore')
        for z, points, label in probes:
            if z not in local_layers:
                assert z in layer_arrays, f'{row["id"]}: missing Z={z}'
                starts, vectors, midpoints, widths = layer_arrays[z]
                row_bounds = np.array(row['bounds_mm'])[:, :2] + shift
                mask = np.all(midpoints >= row_bounds[0]-1, axis=1) & np.all(midpoints <= row_bounds[1]+1, axis=1)
                local_layers[z] = starts[mask], vectors[mask], widths[mask]
            starts, vectors, widths = local_layers[z]
            assert len(starts), f'{row["id"]}: missing Z={z}'
            for point in points + xy:
                t = np.clip(np.sum((point - starts) * vectors, axis=1) /
                            np.maximum(np.sum(vectors * vectors, axis=1), 1e-12), 0, 1)
                distances = np.linalg.norm(starts + t[:, None] * vectors - point, axis=1)
                # Preserve the existing 0.30 mm proximity check and account for
                # wide Arachne beads at junctions, with 0.05 mm sampling tolerance.
                limits = np.maximum(.30, widths/2+.05)
                assert np.any(distances < limits), f'{row["id"]}: discontinuous {label} at Z={z}, {point}'
            checks.append(dict(part=row['id'], feature=label, z_mm=z, probes=len(points), passed=True))
    canvas.save(output / 'first-layer-toolpaths.png')
    return dict(path_checks=checks, detent_tips=tips, mesh_matches_source=True,
                variable_line_width_checked=True)


SLICING = json.loads((Path(__file__).resolve().parents[1] / 'slicing.json').read_text())


def main():
    parser = slicing_parser(HERE, 'star-chain-slicing')
    args = parser.parse_args()
    root, source = slicing_workspace(HERE, args.output_dir), model_directory(HERE)
    metadata = json.loads((source / 'geometry.json').read_text())
    files = ('all-parts.stl',)
    inputs = source_hashes(source, (*files, 'geometry.json'))
    if configure_slicing(args, root, source, files, inputs, SLICING):
        return


    def check(archive, config, gcode, plate, path):
        check_archive_geometry(archive, path)
        return inspect_paths(gcode, path, metadata, plate, root / path.stem)

    common = audit_files(args.studio, root, source, files, inputs, arrange=SLICING['arrange'],
        expected=SLICING['expected'],
        callback=check, collect_only=args.collect_only)
    report = save_report(root, dict(status='complete', printer='Bambu Lab P2S', nozzle_mm=.4,
        layer_mm=.2, wall_loops=4, infill_percent=20, supports=False,
        diagnostic_note='The local vendor end G-code contains T65535 in its AMS unload block; CLI reports it as invalid. Vendor G-code is preserved; all plates return success.',
        **common), source, inputs)
    print(json.dumps(dict(status=report['status'], report=str(root / 'slicing-validation.json'),
        plates=[dict(file=row['file'], minutes=round(row['seconds'] / 60, 1),
                     grams=round(sum(f['total_used_g'] for f in row['filaments']), 1),
                     path_checks=len(row['path_checks'])) for row in report['plates']]), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
