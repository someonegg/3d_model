"""Validate final STL geometry, rigid motion, insertion and GLB correspondence."""
import itertools
import json
import os
from pathlib import Path
import struct

import manifold3d as mf
import numpy as np
import trimesh

from geometry import P, WINGS, FLOOR, WING_Z, CAM_Z, CAM_TOP, LID_Z, KNOB_TOP, box, cylinder
from assembly import xyz


def load_mesh(path):
    source = trimesh.load(path, force='mesh', process=False)
    # Exact welding only. No face deletion, hole filling or other repair.
    vertices, inverse = np.unique(source.vertices, axis=0, return_inverse=True)
    mesh = trimesh.Trimesh(vertices, inverse[source.faces], process=False)
    assert mesh.is_watertight and mesh.is_winding_consistent, path.name
    assert np.all(mesh.area_faces > 1e-12) and mesh.volume > 0, path.name
    return mesh


def solid(mesh):
    result = mf.Manifold(mf.Mesh(np.asarray(mesh.vertices, dtype=np.float32),
                                 np.asarray(mesh.faces, dtype=np.uint32)))
    assert result.status() == mf.Error.NoError
    return result


def overlap(a, b):
    return max(0., (a ^ b).volume())


def clear(a, b, label, tolerance=.0003):
    amount = overlap(a, b)
    assert amount < tolerance, f'{label}: {amount:.6f} mm3 intersection'
    return amount


def check_stops(base, rotor):
    for degrees in (0, P['rotation_degrees']):
        clear(rotor.rotate((0, 0, degrees)), base, f'stop endpoint/{degrees}')
    for degrees in (-.5, P['rotation_degrees']+.5):
        assert overlap(rotor.rotate((0, 0, degrees)), base) > .005, 'stop absent'


def glb_data(path):
    raw = path.read_bytes()
    magic, version, length = struct.unpack_from('<4sII', raw)
    assert magic == b'glTF' and version == 2 and length == len(raw)
    size, kind = struct.unpack_from('<II', raw, 12)
    assert kind == 0x4E4F534A
    data = json.loads(raw[20:20+size])
    binary = raw[28+size:]

    def values(index):
        a = data['accessors'][index]
        view = data['bufferViews'][a['bufferView']]
        width = {'SCALAR': 1, 'VEC3': 3, 'VEC4': 4}[a['type']]
        return np.frombuffer(binary, dtype='<f4' if a['componentType'] == 5126 else '<u4',
                             count=a['count']*width,
                             offset=view.get('byteOffset', 0)+a.get('byteOffset', 0)).reshape(-1, width)
    return data, values


def verify_views(output, assembled):
    data, values = glb_data(output / 'assembly.glb')
    guide = data['scenes'][0]['extras']['assembly']
    assert guide['duration'] == 24 and len(guide['steps']) == 4
    nodes = {row['name']: row for row in data['nodes'] if 'mesh' in row}
    assert set(nodes) == set(assembled)
    for name, node in nodes.items():
        primitive = data['meshes'][node['mesh']]['primitives'][0]
        actual = values(primitive['attributes']['POSITION'])
        expected = np.array(xyz(assembled[name].vertices))
        # Exact STL reordering is irrelevant; coordinate precision is 0.1 um.
        np.testing.assert_allclose(np.unique(actual.round(7), axis=0),
                                   np.unique(expected.round(7), axis=0), atol=1.1e-7)
    animations = data['animations'][0]
    assert len(animations['channels']) == 7
    for row in animations['channels']:
        sampler = animations['samplers'][row['sampler']]
        times, poses = values(sampler['input']).ravel(), values(sampler['output'])
        assert times[0] == 0 and times[-1] == 24 and np.all(np.diff(times) > 0)
        name = data['nodes'][row['target']['node']]['name']
        if row['target']['path'] == 'rotation':
            assert name == 'rotor'
            np.testing.assert_allclose(poses[-1], [0, 0, 0, 1])
            np.testing.assert_allclose(poses[times == 21][0], [0, .5, 0, np.sqrt(3)/2], atol=1e-6)
        else:
            np.testing.assert_allclose(poses[-1], [0, 0, 0])
            if name in WINGS:
                np.testing.assert_allclose(np.linalg.norm(poses[times == 21][0]), .015, atol=1e-7)
    for file, width in (('closed.glb', .072), ('expanded.glb', .102)):
        scene = trimesh.load(output / file, force='scene', process=False)
        assert len(scene.geometry) == 7
        np.testing.assert_allclose(scene.extents, [width, KNOB_TOP/1000, width], atol=2e-7)
    return dict(parts=7, steps=4, duration_seconds=24, geometry_matches_stl=True,
                closed_and_expanded_dimensions_match=True)


def main():
    output = Path(os.environ['MODEL_OUTPUT_DIR'])
    info = json.loads((output / 'assembly.json').read_text())
    assembled, solids, print_parts = {}, {}, {}
    for row in info['parts']:
        mesh = load_mesh(output / row['file'])
        assert len(mesh.split(only_watertight=False, repair=False)) == 1
        assert abs(mesh.bounds[0, 2]) < 1e-5
        print_parts[row['id']] = mesh.copy()
        mesh.apply_transform(np.linalg.inv(row['assembly_to_print']))
        assembled[row['id']] = mesh
        solids[row['id']] = solid(mesh)
    assert len(solids) == 7
    np.testing.assert_allclose(assembled['base'].extents, [72, 72, 7.25], atol=1e-5)
    np.testing.assert_allclose(assembled['wing-1'].extents, [24.7, 10, 4.75], atol=1e-5)
    plate = load_mesh(output / 'all-parts.stl')
    chunks = list(plate.split(only_watertight=False, repair=False))
    assert len(chunks) == 7
    for row in info['parts']:
        expected = print_parts[row['id']].copy()
        expected.apply_translation([*row['plate_xy'], 0])
        found = min(chunks, key=lambda m: np.linalg.norm(m.bounds-expected.bounds))
        np.testing.assert_allclose(found.bounds, expected.bounds, atol=1e-5)
        assert abs(found.volume-expected.volume) < .02
        chunks.remove(found)
    for a, b in itertools.combinations(plate.split(only_watertight=False, repair=False), 2):
        gap = np.maximum(b.bounds[0, :2]-a.bounds[1, :2], a.bounds[0, :2]-b.bounds[1, :2])
        assert max(gap) >= 5-1e-5
    # Actual exported wall/wing/pin/clip sections, not just parameter assertions.
    for name, probe, expected in (
        ('base', box(1, 1, 4, x=0, y=18, z=-1), [1, 1, 2]),
        ('wing-1', box(1, 12, 2, x=20, z=2.5), [1, 10, 2]),
        ('wing-1', box(10, 10, 1, x=14.5, z=5.2), [3.2, 3.2, 1]),
    ):
        bounds = np.array((solids[name] ^ probe).bounding_box())
        np.testing.assert_allclose(bounds[3:]-bounds[:3], expected, atol=1e-5)
    for angle in P['clip_angles']:
        probe = box(1, 2.4, 1, x=0, y=33.8, z=LID_Z+.5).rotate((0, 0, angle))
        clipped = (solids['lid'] ^ probe).rotate((0, 0, -angle))
        bounds = np.array(clipped.bounding_box())
        np.testing.assert_allclose(bounds[3:]-bounds[:3], [1, P['clip_width'], 1], atol=.0002)
    # Measure all four final exported retaining shoulders against the unchanged
    # pocket wall, and check the full release stroke over the insertion path.
    for angle in P['clip_angles']:
        shoulder = solids['lid'].rotate((0, 0, -angle)) ^ box(2.02, 3, .1, x=5, y=34.5, z=4.1)
        bounds = np.array(shoulder.bounding_box())
        np.testing.assert_allclose(bounds[4]-34.65, P['clip_deflection'], atol=.0002)
    # Guide clearance: require room for a 10.48 mm rectangular stem throughout
    # the load-bearing region, excluding the chamfer and rounded nose.
    for i in range(4):
        gauge = box(17, P['wing_width']+2*(P['guide_clearance']-.01), 2.38,
                    x=23, z=WING_Z+.01).rotate((0, 0, i*90))
        clear(gauge, solids['base'], f'guide width {i}')
    samples = []
    for degrees in np.linspace(0, P['rotation_degrees'], 61):
        distance = P['travel']*degrees/P['rotation_degrees']
        moving = dict(solids)
        moving['rotor'] = solids['rotor'].rotate((0, 0, float(degrees)))
        for i, name in enumerate(WINGS):
            a = i*np.pi/2
            shift = (distance*np.cos(a), distance*np.sin(a), 0)
            moving[name] = solids[name].translate(shift)
            # A slightly enlarged follower must still fit every exported slot.
            pin = cylinder(P['follower_radius']+P['guide_clearance']-.01, 1.5,
                           x=P['follower_start_radius']+distance, z=CAM_Z+.3).rotate((0, 0, 90*i))
            clear(pin, moving['rotor'], f'cam clearance/{i}/{degrees}')
        worst = max(clear(moving[a], moving[b], f'{a}/{b}/{degrees}')
                    for a, b in itertools.combinations(moving, 2))
        samples.append(dict(degrees=float(degrees), extension_mm=float(distance),
                            maximum_intersection_mm3=round(worst, 7)))
    check_stops(solids['base'], solids['rotor'])
    # Drop in the sliders, then the aligned cam. Cap insertion permits only the
    # intended radial latch interference; no other rigid collision is ignored.
    for offset in np.linspace(0, 15, 31):
        for name in WINGS:
            clear(solids[name].translate((0, 0, float(offset))), solids['base'], f'wing insertion/{name}/{offset}')
        rotor = solids['rotor'].translate((0, 0, float(offset)))
        for name in ['base', *WINGS]:
            clear(rotor, solids[name], f'rotor insertion/{name}/{offset}')
    catches = mf.Manifold()
    for angle in P['clip_angles']:
        catches += box(2.02, P['clip_deflection']+.03, 1.6,
                       x=5, y=34.65+P['clip_deflection']/2, z=2.75).rotate((0, 0, angle))
    rigid_lid = solids['lid'] - catches
    max_latch_contact = 0
    for offset in np.linspace(0, 8, 81):
        shifted = rigid_lid.translate((0, 0, float(offset)))
        for name in ['base', 'rotor', *WINGS]:
            clear(shifted, solids[name], f'lid rigid insertion/{name}/{offset}')
        max_latch_contact = max(max_latch_contact,
                                overlap(solids['lid'].translate((0, 0, float(offset))), solids['base']))
    assert max_latch_contact > .1
    # The depressed hook must have somewhere to go, including beside the cam.
    for angle in P['clip_angles']:
        local = solids['lid'].rotate((0, 0, -angle))
        hook = local ^ box(2.02, 3, LID_Z-2.8, x=5, y=34, z=2.8)
        depressed = hook.translate((0, -(P['clip_deflection']+.01), 0)).rotate((0, 0, angle))
        for offset in np.linspace(0, 8, 81):
            for name in ['base', 'rotor']:
                clear(depressed.translate((0, 0, float(offset))), solids[name],
                      f'depressed catch/{angle}/{name}/{offset}')
    assert overlap(solids['lid'].translate((0, 0, .5)), solids['base']) > .1, 'lid latch absent'
    # Roof plus slot prevent removal during operation; guide overlap at full
    # extension remains measurable on the exported wing, beyond its round root.
    full_wing = solids['wing-1'].translate((15, 0, 0))
    assert overlap(full_wing.translate((0, 0, .5)), solids['rotor'].rotate((0, 0, 60))) > 1
    assert overlap(full_wing.translate((.5, 0, 0)), solids['rotor'].rotate((0, 0, 60))) > .01
    assert overlap(solids['wing-1'].translate((-.5, 0, 0)), solids['rotor']) > .01
    # At full extension both flat sides still meet at least 6 mm of continuous
    # guide/rim wall. Probe the actual exported sections on both sides.
    for side in (-1, 1):
        wall_probe = box(6, .5, 1, x=32.5, y=side*5.8, z=3)
        assert overlap(wall_probe, solids['base']) > 2.99
        wing_probe = box(6, .15, 1, x=32.5, y=side*4.9, z=3)
        assert overlap(wing_probe, full_wing) > .89
    animation = verify_views(output, assembled)
    report = dict(passed=True, parts=7, closed_width_mm=72, expanded_width_mm=102,
                  height_mm=KNOB_TOP, travel_mm=15, rotation_degrees=60,
                  guide_clearance_per_side_mm=P['guide_clearance'], axial_clearance_mm=P['axial_clearance'],
                  full_extension_verified_flat_guide_length_mm=6,
                  cam_clearance_probe_per_side_mm=P['guide_clearance']-.01, samples=samples,
                  assembly_animation=animation,
                  insertion=dict(wing_and_cam_samples=31, lid_samples=81,
                                 permitted_contact='Only the four lid catch ramps',
                                 catch_engagement_mm=P['clip_deflection'],
                                 maximum_latch_interference_mm3=round(max_latch_contact, 4)),
                  clip_screening=dict(method='End-loaded in-plane cantilever approximation; no friction/force simulation',
                                      effective_length_mm=P['clip_length']-1, width_mm=P['clip_width'],
                                      deflection_mm=P['clip_deflection']+.01,
                                      estimated_peak_strain_percent=round(100*1.5*P['clip_width']*(P['clip_deflection']+.01)/(P['clip_length']-1)**2, 3)),
                  physical_print_test=False, operating_force_and_durability_verified=False)
    (output / 'detail-validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('Final STL: seven closed solids; 61 motion poses and assembly paths verified', flush=True)


if __name__ == '__main__':
    main()
