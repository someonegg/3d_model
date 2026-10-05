"""Measure final exported parts and sample rigid travel and compliant detents."""
import itertools
import json
import os
from pathlib import Path

import numpy as np
import trimesh

from geometry import (base, lid, box, cylinder, detent_recess_profile,
                      flag_region, neck_z, pose, slider_top, solid, straight_length,
                      terminal_pivot_x)


def require_clear(a, b, label, tolerance=.002):
    volume = max(0., (a ^ b).volume())
    assert volume <= tolerance, f'{label}: {volume:.6f} mm3 interference'
    return volume


def flex_lid(m, displacement, p):
    """Kinematic envelope only; not a force, fatigue or friction simulation."""
    m = m.subdivide().subdivide()
    v = m.vertices.copy()
    start, end, half = p['flag_start_x_mm'], p['flag_end_x_mm'], p['flag_width_mm'] / 2
    mask = (v[:, 0] >= start - 1e-5) & (v[:, 0] <= end + 1e-5) & (np.abs(v[:, 1]) <= half + 1e-5)
    t = np.maximum((v[:, 0] - start) / (p['closed_pivot_x_mm'] - start), 0)
    response = np.where(t <= 1, t ** 2 * (3 - t) / 2, 1 + 1.5 * (t - 1))
    v[mask, 2] += displacement * response[mask]
    m.vertices = v
    return solid(m)


def detent_lift(p):
    # The bump's leading edge lies nearer the cantilever root than its centre.
    return p['detent_interference_mm'] + .10


def check_capture(incoming, receiver, p, angles):
    """Check the lower head against the solid end wall, independent of the lid."""
    pivot = p['closed_pivot_x_mm'] - p['stroke_mm']
    radius = p['disc_radius_mm']
    collar = incoming ^ box(pivot - radius - .01, pivot + radius + .01,
                             -radius - .01, radius + .01, p['slider_z_mm'], neck_z(p) - .3)
    contacts = []
    for angle in angles:
        transform = trimesh.transformations.rotation_matrix(np.radians(angle), (0, 0, 1), [pivot, 0, 0])
        turned = receiver.transform(transform[:3, :])
        require_clear(collar, turned, f'capture seated/{angle}')
        for pull in (.3, .6, 1.):
            contact = (collar.translate((-pull, 0, 0)) ^ turned).volume()
            assert contact > .2, f'lower head can escape at {angle} deg, pull {pull}: {contact}'
            contacts.append(dict(angle_deg=float(angle), overtravel_mm=pull, contact_mm3=contact))
    return contacts


def check_locators(previous, receiver, p):
    """Closed keys must constrain both lateral and vertical translation."""
    previous = previous.translate((-p['link_length_mm'], 0, 0)) ^ box(.001, p['locator_engagement_mm']+.01, -10, 10, 0, p['body_height_mm'])
    require_clear(previous, receiver, 'closed locator seats')
    checks = []
    for offset in ((0, .25, 0), (0, -.25, 0), (0, 0, .25), (0, 0, -.25)):
        volume = (previous.translate(offset) ^ receiver).volume()
        assert volume > .01, f'locator fails to constrain {offset}: {volume}'
        checks.append(dict(offset_mm=offset, contact_mm3=volume))
    return checks


def check_anchor(slider, receiver, p):
    """The unperforated wide head must be captured without a peg."""
    center = (p['anchor_start_x_mm'] + p['anchor_end_x_mm']) / 2
    require_clear(slider, receiver, 'fixed anchor seats')
    core = box(center-.4, center+.4, -.5, .5, p['slider_z_mm']+.01, slider_top(p)-.01)
    assert (core - slider).volume() < .00001, 'anchor still has a bore'
    require_clear(receiver, core, 'anchor pocket has a post')
    half = p['neck_width_mm'] / 2
    for sign in (-1, 1):
        y0, y1 = sorted((sign*(half+.05), sign*(half+.15)))
        fillet = box(p['anchor_end_x_mm']+.15, p['anchor_end_x_mm']+.25,
                     y0, y1, neck_z(p)+.01, slider_top(p)-.01)
        assert (fillet - slider).volume() < .00001, 'fixed anchor neck fillet missing'
    contacts = []
    for offset in ((.6, 0, 0), (-.6, 0, 0), (0, .6, 0), (0, -.6, 0), (0, 0, .6), (0, 0, -.6)):
        volume = (slider.translate(offset) ^ receiver).volume()
        assert volume > .2, f'fixed anchor can escape {offset}: {volume}'
        contacts.append(dict(offset_mm=offset, contact_mm3=volume))
    for angle in (-8, 8):
        transform = trimesh.transformations.rotation_matrix(np.radians(angle), (0, 0, 1), [center, 0, 0])
        volume = (slider.transform(transform[:3, :]) ^ receiver).volume()
        assert volume > .2, f'fixed anchor has an extra free joint at {angle}: {volume}'
        contacts.append(dict(angle_deg=angle, contact_mm3=volume))
    c = p['clearance_per_side_mm']
    front = p['closed_pivot_x_mm'] + p['disc_radius_mm'] + c
    rear = p['anchor_end_x_mm'] + c
    front_wall = p['anchor_start_x_mm'] - c - front
    rear_wall = p['link_length_mm'] - rear
    assert min(front_wall, rear_wall) >= p['anchor_wall_minimum_mm'] - 1e-6
    for x0, x1 in ((front+.01, p['anchor_start_x_mm']-c-.01), (rear+.01, p['link_length_mm']-.01)):
        wall = box(x0, x1, -.5, .5, p['floor_mm']+.01, neck_z(p)-.31)
        assert (wall - receiver).volume() < .00001, 'fixed anchor end wall missing'
    return dict(post_present=False, bore_present=False,
                head_axial_thickness_mm=p['anchor_end_x_mm']-p['anchor_start_x_mm'],
                neck_fillet_radius_mm=p['anchor_neck_fillet_mm'],
                front_wall_mm=front_wall, rear_wall_mm=rear_wall,
                end_wall_minimum_mm=p['anchor_wall_minimum_mm'], checks=contacts)


def check_plate(out, filename, rows, printed):
    plate = trimesh.load(out / filename, force='mesh')
    chunks = list(plate.split(only_watertight=False))
    assert len(chunks) == len(rows), filename
    assert max(plate.extents[:2]) <= 220.001 and plate.extents[2] < 14
    for row in rows:
        expected = printed[row['part']].copy()
        expected.apply_translation(row['translation_mm'])
        found = min(chunks, key=lambda m: np.linalg.norm(m.bounds - expected.bounds))
        np.testing.assert_allclose(found.bounds, expected.bounds, atol=3e-5)
        assert abs(found.volume - expected.volume) < .02
        chunks.remove(found)
    for a, b in itertools.combinations(plate.split(), 2):
        gap = np.maximum(b.bounds[0, :2] - a.bounds[1, :2], a.bounds[0, :2] - b.bounds[1, :2])
        assert max(gap) >= 4.999, f'{filename}: crowded layout'
    return dict(file=filename, components=len(rows), bounds_mm=plate.bounds.tolist())


def contact_angle(keys, receiver, center, axis, sign):
    def contact(angle):
        matrix = trimesh.transformations.rotation_matrix(np.radians(sign*angle), axis, center)
        return (keys.transform(matrix[:3, :]) ^ receiver).volume() > .002
    assert contact(15), 'locator has no angular stop within 15 degrees'
    # Find the FIRST contact, then refine it; no monotonicity assumed past that stop.
    previous = 0.
    for upper in np.arange(.1, 15.01, .1):
        if contact(upper):
            lower = previous
            for _ in range(12):
                middle = (lower+upper)/2
                if contact(middle):
                    upper = middle
                else:
                    lower = middle
            return round(float(upper), 4)
        previous = upper
    raise AssertionError('unreachable')


def angular_clearances(keys, receiver, p):
    # Remove the donor body/end face to isolate the side-key interface. Keep the
    # key centres fixed, no translation or detent retreat allowed in this probe.
    center = [p['locator_engagement_mm']/2, 0,
              (p['locator_bottom_mm']+p['locator_engagement_mm']/2+p['base_height_mm']-p['locator_vertical_clearance_mm'])/2]
    require_clear(keys, receiver, 'angular probe initial fit')
    return {name: {direction: contact_angle(keys, receiver, center, axis, sign)
                   for direction, sign in (('negative_deg', -1), ('positive_deg', 1))}
            for name, axis in (('roll', [1, 0, 0]), ('pitch', [0, 1, 0]), ('yaw', [0, 0, 1]))}


def main():
    out = Path(os.environ['MODEL_OUTPUT_DIR'])
    data = json.loads((out / 'geometry.json').read_text())
    p = data['parameters']
    printed, assembled, solids = {}, {}, {}
    for name in data['counts']:
        m = trimesh.load(out / f'{name}.stl', force='mesh')
        assert m.is_volume and len(m.split()) == 1, name
        assert abs(m.bounds[0, 2]) < 2e-5, f'{name}: off bed'
        printed[name] = m.copy()
        m.apply_transform(np.linalg.inv(data['print_transforms'][name]))
        assembled[name], solids[name] = m, solid(m)
    plate = check_plate(out, 'all-parts.stl', data['layout'], printed)
    locator_checks = check_locators(solids['link-base'], solids['link-base'] + solids['link-lid'], p)
    check_locators(solids['link-base'], solids['terminal-base'] + solids['terminal-lid'], p)
    keys = solids['link-base'].translate((-p['link_length_mm'], 0, 0)) ^ box(.001, p['locator_engagement_mm']+.01, -10, 10, 0, p['body_height_mm'])
    receiver = solids['link-base'] + solids['link-lid']
    locator_angles = angular_clearances(keys, receiver, p)
    old_p = p | dict(body_height_mm=12.4, base_height_mm=8.8, slider_thickness_mm=4.6,
                     locator_engagement_mm=5., locator_clearance_mm=.2,
                     flag_start_x_mm=3., detent_interference_mm=.5)
    old_base = base(old_p)
    old_keys = old_base.translate((-p['link_length_mm'], 0, 0)) ^ box(.001, 5.01, -10, 10, 0, 12.4)
    old_angles = angular_clearances(old_keys, old_base + lid(old_p), old_p)
    for sign in (-1, 1):
        tip = keys ^ box(p['locator_engagement_mm']-.02, p['locator_engagement_mm'], sign*6.8-.1, sign*6.8+.1, 0, p['body_height_mm'])
        assert tip.bounding_box()[5] - tip.bounding_box()[2] >= 2.399
        for z in (1., p['base_height_mm']+.1):
            assert (receiver ^ box(.5, 1, sign*6.8-.4, sign*6.8+.4, z, z+.1)).volume() > .015
        # The solid web separating the slot tip from the relocated counterbore.
        probe = box(p['locator_engagement_mm']+p['locator_clearance_mm']+.01, p['pin_x_mm']-1.91, sign*6.8-.2, sign*6.8+.2, .1, .7)
        assert (probe - solids['link-base']).volume() < .00001
    # Bore sizes and receiver envelope are measured against exported solids.
    require_clear(solids['link-base'], cylinder(p['pin_x_mm'], 6.8, 1.599, 1.51, p['base_height_mm'] - .01), 'body pin bore')
    require_clear(solids['star-head'], cylinder(-23, 0, 1.899, 1.91, 6.89), 'star pivot bore')
    assert (solids['star-head'] ^ cylinder(-23, 0, 4.8, 2, 6.8)).volume() > 280
    anchor_checks = check_anchor(solids['slider'], receiver, p)
    np.testing.assert_allclose(assembled['star-head'].extents[1:], [56, 5], atol=.015)
    assert abs(assembled['link-base'].extents[2] - p['base_height_mm']) < 2e-5
    for name, probe, expected in (
        ('slider', box(p['link_length_mm']+4, p['link_length_mm']+5, -10, 10, 0, p['body_height_mm']), [1, p['neck_width_mm'], p['slider_thickness_mm']]),
        ('link-base', box(8, 9, -2, 2, 0, 3), [1, 4, 1.6]),
        ('link-lid', box(8, 9, -p['flag_width_mm'] / 2, p['flag_width_mm'] / 2,
                          p['base_height_mm'] - 1, p['body_height_mm'] + 1), [1, p['flag_width_mm'], p['flag_thickness_mm']]),
        ('link-base', box(0, p['capture_wall_mm'] + .1, -.5, .5, p['floor_mm'] + .01, neck_z(p) - .31),
         [p['capture_wall_mm'], 1, neck_z(p) - .32 - p['floor_mm']]),
    ):
        bounds = np.array((solids[name] ^ probe).bounding_box())
        np.testing.assert_allclose(bounds[3:] - bounds[:3], expected, atol=2e-5)
    neck_bounds = np.array((solids['slider'] ^ box(p['link_length_mm']+4, p['link_length_mm']+5, -3, 3, 0, p['body_height_mm'])).bounding_box())
    assert abs(neck_bounds[2] - neck_z(p)) < 2e-5, 'neck must clear the lower end wall'
    # Inspect the exported cavity, including its narrowing sides and full depth.
    cx = p['link_length_mm'] + p['closed_pivot_x_mm']
    recess_profile = np.array(detent_recess_profile(p))
    for depth in (.05, .2, .5, .7, 1.):
        radius = float(np.interp(depth, recess_profile[:, 1], recess_profile[:, 0]))
        z = slider_top(p) - depth
        require_clear(solids['slider'], cylinder(cx, 0, radius-.02, z-.001, z+.001), f'bowl radius/{depth}')
        rim = box(cx+radius+.03, cx+radius+.06, -.01, .01, z-.001, z+.001)
        assert (rim - solids['slider']).volume() < 1e-7, 'recess sides do not narrow'
    bottom = slider_top(p) - p['detent_depth_mm']
    require_clear(solids['slider'], cylinder(cx, 0, .03, bottom+.001, bottom+.01), 'bowl depth')
    assert (solids['slider'] ^ cylinder(cx, 0, .1, bottom-.02, bottom-.001)).volume() > .0005
    pin_top = 1.2 + p['pin_shaft_length_mm']
    np.testing.assert_allclose(printed['lock-pin'].extents, [5, 5, pin_top], atol=2e-5)
    expected_pin = cylinder(0, 0, 2.5, 0, 1.2) + cylinder(0, 0, 1.48, 1.19, pin_top)
    assert (expected_pin - solids['lock-pin']).volume() < .002
    assert (solids['lock-pin'] - expected_pin).volume() < .002
    pin_bottom = p['body_height_mm'] - p['pin_shaft_length_mm']
    np.testing.assert_allclose(pin_bottom, .2, atol=1e-6)
    # The 5 mm star is fully spanned; 1.4 mm overlaps the lower fork.
    support = dict(tip_above_bottom_mm=pin_bottom, lower_fork_overlap_mm=1.6-pin_bottom,
                   star_bearing_overlap_mm=5., radial_clearance_body_mm=.12,
                   radial_clearance_star_mm=.42, axial_retention_verified=False)
    assert support['lower_fork_overlap_mm'] > 0
    root_z = p['body_height_mm'] - p['flag_thickness_mm']
    tip_z = slider_top(p) - p['detent_interference_mm']
    x = p['closed_pivot_x_mm']
    for name in ('link-lid', 'terminal-lid'):
        bump = solids[name] ^ box(x-2, x+2, -2, 2, tip_z-.1, root_z-.001)
        bounds = bump.bounding_box()
        np.testing.assert_allclose(bounds[2], tip_z, atol=2e-5)
        np.testing.assert_allclose([bounds[3]-bounds[0], bounds[4]-bounds[1]],
                                   [p['detent_root_diameter_mm']]*2, atol=.01)
        tip = solids[name] ^ box(x-2, x+2, -2, 2, tip_z, tip_z+.05)
        assert tip.bounding_box()[3]-tip.bounding_box()[0] < 1, 'dome tip is not rounded and narrowed'
    star_pivot = terminal_pivot_x(p)
    lower_bearing = solids['terminal-base'] ^ cylinder(star_pivot, 0, 2., pin_bottom, 1.6)
    bounds = lower_bearing.bounding_box()
    np.testing.assert_allclose([bounds[2], bounds[5]], [pin_bottom, 1.6], atol=2e-5)
    star_bearing = solids['star-head'] ^ cylinder(-23, 0, 2.5, pin_bottom, p['body_height_mm'])
    bounds = star_bearing.bounding_box()
    np.testing.assert_allclose(bounds[5]-bounds[2], p['star_thickness_mm'], atol=2e-5)
    for x, y, receiver_name in ((p['pin_x_mm'], 6.8, 'link'), (star_pivot, 0, 'terminal')):
        flip = np.diag([1., -1., -1., 1.])
        flip[:3, 3] = (x, y, p['body_height_mm'] + 1.2)
        receiver_pin = solids[receiver_name+'-base'] + solids[receiver_name+'-lid']
        if receiver_name == 'terminal':
            receiver_pin += solids['star-head'].translate((star_pivot+23, 0, 0))
        for offset in np.linspace(0, pin_top, 25):
            pin = solids['lock-pin'].transform(flip[:3, :]).translate((0, 0, float(offset)))
            require_clear(pin, receiver_pin, f'{receiver_name} pin insertion/{offset}')
    # The rounded tips are sampled in the exported mesh, including actual arc facets.
    star_vertices = assembled['star-head'].vertices
    tip = star_vertices[(star_vertices[:, 0] > 24.99) & (np.abs(star_vertices[:, 1]) < 2.9)]
    assert len(tip) > 15
    radii = np.linalg.norm(tip[:, :2] - [25, 0], axis=1)
    np.testing.assert_allclose(radii, 3., atol=2e-5)
    # Sample every axial position with the disc in the preceding body.
    samples = []
    moving = solids['link-base'] + solids['link-lid']
    rigid_lid = solids['link-lid'] - flag_region(p)
    flexible_lid = flex_lid(assembled['link-lid'], detent_lift(p), p)
    for stroke in np.linspace(0, p['stroke_mm'], 45):
        stroke = float(stroke)
        incoming = solids['slider'].translate((-p['link_length_mm'] - stroke, 0, 0))
        previous = solids['link-base'].translate((-p['link_length_mm'] - stroke, 0, 0))
        require_clear(incoming, solids['link-base'], f'slide/base/{stroke}')
        require_clear(incoming, rigid_lid, f'slide/rigid lid/{stroke}')
        require_clear(incoming, flexible_lid if stroke else solids['link-lid'], f'slide/detent/{stroke}')
        require_clear(previous, moving, f'slide/keyed ends/{stroke}')
        samples.append(stroke)
    # At full extension the captured pin and its neck clear the mouth over +/-35 deg.
    bend_samples = []
    pin_x = p['closed_pivot_x_mm'] - p['stroke_mm']
    incoming = solids['slider'].translate((-p['link_length_mm'] - p['stroke_mm'], 0, 0))
    previous = solids['link-base'].translate((-p['link_length_mm'] - p['stroke_mm'], 0, 0))
    for angle in np.linspace(-p['joint_angle_deg'], p['joint_angle_deg'], 29):
        transform = trimesh.transformations.rotation_matrix(np.radians(angle), (0, 0, 1), [pin_x, 0, 0])
        require_clear(incoming, moving.transform(transform[:3, :]), f'bend/slider/{angle}')
        require_clear(previous, moving.transform(transform[:3, :]), f'bend/body/{angle}')
        bend_samples.append(float(angle))
    # Stop and key checks must reject both pull-through and bending while closed.
    capture_checks = check_capture(incoming, solids['link-base'], p, bend_samples)
    for lift in (.5, 1, 2):
        assert (incoming.translate((0, 0, lift)) ^ rigid_lid).volume() > .05, 'lid does not capture head vertically'
    assert (solids['slider'].translate((-p['link_length_mm'] + .6, 0, 0)) ^ solids['link-base']).volume() > .05
    transform = trimesh.transformations.rotation_matrix(np.radians(8), (0, 0, 1), [p['closed_pivot_x_mm'], 0, 0])
    assert (solids['link-base'].translate((-p['link_length_mm'], 0, 0)) ^ moving.transform(transform[:3, :])).volume() > .1
    # Five real detents have clearance in their dimples and interfere only when released.
    rest = solids['slider'].translate((-p['link_length_mm'], 0, 0))
    require_clear(rest, solids['link-lid'], 'seated detent')
    detent_contact = solids['slider'].translate((-p['link_length_mm'] - 2, 0, 0)) ^ solids['link-lid']
    assert .2 < detent_contact.volume() < 3, 'detent not present or excessive'
    require_clear(detent_contact, rigid_lid, 'detent outside flexible flag')
    # Validate entire exported closed assembly, including pins, star and terminal fork.
    state_dimensions = {}
    bent = [dict(id=node, part=name, matrix=matrix.tolist()) for node, name, matrix in
            pose(p, p['stroke_mm'], [15, -25, 30, -25, 15], 25)]
    states = {key: data[key] for key in ('closed', 'extended_straight')} | {'extended_bent': bent}
    for key, rows in states.items():
        solids_in_state, meshes_in_state = {}, []
        for row in rows:
            m = assembled[row['part']].copy()
            m.apply_transform(row['matrix'])
            meshes_in_state.append(m)
            solids_in_state[row['id']] = solid(m)
        for a, b in itertools.combinations(solids_in_state, 2):
            require_clear(solids_in_state[a], solids_in_state[b], f'{key}/{a}/{b}')
        dimensions = trimesh.util.concatenate(meshes_in_state).extents
        state_dimensions[key] = dimensions.tolist()
    np.testing.assert_allclose(state_dimensions['closed'][0], straight_length(p), atol=.02)
    np.testing.assert_allclose(state_dimensions['extended_straight'][0], straight_length(p, p['stroke_mm']), atol=.02)
    star_rows = []
    terminal = solids['terminal-base'] + solids['terminal-lid']
    for angle in np.linspace(-40, 40, 33):
        star_pose = dict((name, (part, transform)) for name, part, transform in pose(p, star_angle=float(angle)))
        m = assembled['star-head'].copy()
        m.apply_transform(star_pose['star-head'][1])
        m.apply_translation((-(p['links']-1)*p['link_length_mm'], 0, 0))
        require_clear(solid(m), terminal, f'star pivot/{angle}')
        star_rows.append(float(angle))
    for angle in (-42, 42):
        row = next(row for row in pose(p, star_angle=angle) if row[0] == 'star-head')
        m = assembled['star-head'].copy()
        m.apply_transform(row[2]); m.apply_translation((-(p['links']-1)*p['link_length_mm'], 0, 0))
        assert (solid(m) ^ terminal).volume() > .01, 'missing star hard stop'
    # Insertion is from above, before the lid traps the disc and flat anchor.
    for offset in np.linspace(0, 10, 21):
        require_clear(solids['slider'].translate((0, 0, float(offset))), solids['link-base'], f'anchor insertion/{offset}')
        require_clear(rest.translate((0, 0, float(offset))), solids['link-base'], f'disc insertion/{offset}')
    # Verify display nodes correspond to the real components and metres/Y-up bounds.
    for file, rows in (('closed.glb', data['closed']), ('extended.glb', bent)):
        scene = trimesh.load(out / file, force='scene')
        assert len(scene.geometry) == 31 and scene.bounds[1, 1] < .014
        for row in rows:
            expected = assembled[row['part']].copy()
            expected.apply_transform(row['matrix'])
            expected.vertices = expected.vertices[:, [0, 2, 1]] * [.001, .001, -.001]
            transform, geometry = scene.graph[row['id']]
            actual = scene.geometry[geometry].copy()
            actual.apply_transform(transform)
            np.testing.assert_allclose(actual.bounds, expected.bounds, atol=1e-7)
            assert abs(actual.volume - expected.volume) < 1e-10
    scene = trimesh.load(out / 'closed.glb', force='scene')
    np.testing.assert_allclose(scene.extents, np.array(state_dimensions['closed'])[[0, 2, 1]] / 1000, atol=1e-7)
    report = dict(passed=True, parts=31, plate=plate, fixed_anchor_screening=anchor_checks,
                  detent_recess=dict(shape='ellipsoidal bowl with smooth Bezier lip',
                      radial_clearance_mm=p['detent_recess_clearance_mm'],
                      floor_clearance_mm=p['detent_depth_mm']-p['detent_interference_mm'],
                      mouth_diameter_mm=2*recess_profile[0, 0]),
                  locator_checks=locator_checks, locator_angles=locator_angles, previous_locator_angles=old_angles,
                  angular_method='First rigid tongue collision about fixed centre; no retreat, compliance, friction or force model. Not physical stiffness.', tongue_tip_minimum_mm=2.4,
                  assembly_dimensions_mm=state_dimensions, stroke_samples_mm=samples,
                  bend_samples_deg=bend_samples, star_samples_deg=star_rows,
                  nominal_joint_stroke_mm=p['stroke_mm'], detent_contact_mm3=detent_contact.volume(),
                  capture_screening=dict(wall_thickness_mm=p['capture_wall_mm'],
                      lower_head_height_mm=p['head_lower_height_mm'],
                      stop_contact_height_mm=neck_z(p) - .3 - p['slider_z_mm'], checks=capture_checks),
                  compliant_screening=dict(method='prescribed cantilever envelope, no friction/force/fatigue model',
                      flag_thickness_mm=p['flag_thickness_mm'], flag_width_mm=p['flag_width_mm'],
                      flag_effective_length_mm=p['closed_pivot_x_mm'] - p['flag_start_x_mm'], lift_mm=detent_lift(p),
                      estimated_flag_surface_strain_percent=100 * 1.5 * p['flag_thickness_mm'] * detent_lift(p) /
                          (p['closed_pivot_x_mm'] - p['flag_start_x_mm']) ** 2),
                  lock_pin_screening=support,
                  physical_print_test=False, holding_force_verified=False, fatigue_verified=False)
    (out / 'detail-validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Exported geometry, 45 sliding positions, 29 bend angles and 33 star angles passed')


if __name__ == '__main__':
    main()
