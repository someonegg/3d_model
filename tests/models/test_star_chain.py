"""Regressions for captive heads, pull-release detents and sliced open gaps."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np
import trimesh

SOURCE = Path(__file__).resolve().parents[2] / 'models/star-chain-fdm/src'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SOURCE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


geometry = load('star_chain_geometry', 'geometry.py')
with patch.dict(sys.modules, {'geometry': geometry}):
    verify = load('star_chain_verify', 'verify.py')
    slicing = load('star_chain_slice', 'slice.py')


class StarChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = geometry.parameters()
        cls.slider = geometry.slider(cls.p)
        cls.rest = cls.slider.translate((-cls.p['link_length_mm'], 0, 0))
        cls.extended = cls.rest.translate((-cls.p['stroke_mm'], 0, 0))

    def test_end_wall_captures_at_all_clearances_and_bend_angles(self):
        p = self.p
        pivot = p['closed_pivot_x_mm'] - p['stroke_mm']
        angles = np.linspace(-p['joint_angle_deg'], p['joint_angle_deg'], 29)
        for clearance in (.2, .3, .4):
            receiver = geometry.base(p, clearance)
            verify.check_capture(self.extended, receiver, p, angles)
            for angle in angles:
                turn = trimesh.transformations.rotation_matrix(np.radians(angle), (0, 0, 1), [pivot, 0, 0])
                verify.require_clear(self.extended, receiver.transform(turn[:3, :]), 'raised neck at full bend')

    def test_validator_rejects_missing_lower_end_wall(self):
        p = self.p
        defective = geometry.base(p) - geometry.box(-1, p['capture_wall_mm'] + .01, -8, 8,
                                                   p['floor_mm'], geometry.neck_z(p) - .29)
        with self.assertRaisesRegex(AssertionError, 'lower head can escape'):
            verify.check_capture(self.extended, defective, p, [0])

    def test_solid_fixed_anchor_is_captured_without_post(self):
        for clearance in (.2, .3, .4):
            with self.subTest(clearance=clearance):
                p = self.p | {'clearance_per_side_mm': clearance}
                receiver = geometry.base(p) + geometry.lid(p)
                report = verify.check_anchor(self.slider, receiver, p)
                self.assertFalse(report['post_present'])
                self.assertFalse(report['bore_present'])
                self.assertGreaterEqual(report['head_axial_thickness_mm'], 4)
                self.assertGreaterEqual(min(report['front_wall_mm'], report['rear_wall_mm']), 2.4-1e-6)
                self.assertEqual(len(report['checks']), 8)

    def test_fixed_anchor_validator_rejects_missing_wall_post_and_bore(self):
        p = self.p
        receiver = geometry.base(p) + geometry.lid(p)
        center = (p['anchor_start_x_mm'] + p['anchor_end_x_mm']) / 2
        missing_wall = receiver - geometry.box(p['anchor_end_x_mm']+.3, p['link_length_mm']+.1, -4.4, 4.4,
                                               p['floor_mm'], p['body_height_mm']+.1)
        with self.assertRaisesRegex(AssertionError, 'fixed anchor can escape'):
            verify.check_anchor(self.slider, missing_wall, p)
        post = geometry.cylinder(center, 0, .2, p['floor_mm'], geometry.slider_top(p))
        with self.assertRaisesRegex(AssertionError, 'fixed anchor seats'):
            verify.check_anchor(self.slider, receiver + post, p)
        with self.assertRaisesRegex(AssertionError, 'anchor still has a bore'):
            verify.check_anchor(self.slider - post, receiver, p)

    def test_closed_locators_constrain_vertical_and_lateral_motion(self):
        base = geometry.base(self.p)
        lid = geometry.lid(self.p)
        self.assertEqual(len(verify.check_locators(base, base + lid, self.p)), 4)
        # Removing the socket floors must be rejected as missing downward support.
        defective = base
        for sign in (-1, 1):
            defective -= geometry.box(-.1, 5.3, sign * 6.8 - 2.1, sign * 6.8 + 2.1,
                                      -.1, self.p['base_height_mm']+.01)
        with self.assertRaisesRegex(AssertionError, 'locator fails'):
            verify.check_locators(base, defective + lid, self.p)

    def test_missing_socket_floor_fails_downward_support(self):
        base = geometry.base(self.p)
        receiver = base + geometry.lid(self.p)
        for sign in (-1, 1):
            receiver -= geometry.box(-.1, 5.21, sign*6.8-1.8, sign*6.8+1.8, -.1, self.p['base_height_mm'])
        with self.assertRaisesRegex(AssertionError, r'locator fails to constrain \(0, 0, -0.25\)'):
            verify.check_locators(base, receiver, self.p)

    def test_missing_socket_roof_fails(self):
        base = geometry.base(self.p)
        with self.assertRaisesRegex(AssertionError, 'locator fails'):
            verify.check_locators(base, base, self.p)

    def test_coarse_tongue_tip_and_both_ends(self):
        base = geometry.base(self.p)
        for sign in (-1, 1):
            tip = base ^ geometry.box(self.p['link_length_mm']+self.p['locator_engagement_mm']-.02, self.p['link_length_mm']+self.p['locator_engagement_mm'], sign*6.8-.1, sign*6.8+.1, 0, 12.4)
            self.assertGreaterEqual(tip.bounding_box()[5]-tip.bounding_box()[2], 2.399)
        verify.check_locators(base, geometry.base(self.p, terminal=True)+geometry.lid(self.p, terminal=True), self.p)
        self.assertEqual(len(geometry.pose(self.p)), 31)

    def test_detent_variants_seat_and_release_without_rigid_collision(self):
        contacts = []
        for interference in sorted({.3, .4, self.p['detent_interference_mm']}):
            p = self.p | {'detent_interference_mm': interference}
            lid = geometry.lid(p)
            rigid = lid - geometry.flag_region(p)
            lifted = verify.flex_lid(geometry.mesh(lid), verify.detent_lift(p), p)
            verify.require_clear(self.rest, lid, 'seated detent')
            contact = (self.rest.translate((-2, 0, 0)) ^ lid).volume()
            self.assertGreater(contact, .2)
            contacts.append(contact)
            for stroke in (.15, .3, .5, 1, 2, 5, self.p['stroke_mm']):
                moving = self.rest.translate((-stroke, 0, 0))
                verify.require_clear(moving, rigid, 'detent outside flag')
                verify.require_clear(moving, lifted, 'detent release')
        self.assertTrue(all(a < b for a, b in zip(contacts, contacts[1:])))
        weak_lid = geometry.lid(self.p | {'detent_interference_mm': 0})
        self.assertAlmostEqual((self.rest.translate((-2, 0, 0)) ^ weak_lid).volume(), 0, places=6)

    def test_stepped_slider_prints_neck_on_bed(self):
        m = geometry.mesh(self.slider)
        m.apply_transform(geometry.print_transform('slider', self.p))
        neck = geometry.solid(m) ^ geometry.box(self.p['link_length_mm']+4, self.p['link_length_mm']+5, -3, 3, -1, self.p['body_height_mm'])
        bounds = neck.bounding_box()
        self.assertAlmostEqual(bounds[2], 0, places=5)
        self.assertAlmostEqual(bounds[5], self.p['slider_thickness_mm'], places=5)

    def test_straight_pin_length_is_independent_of_body_height(self):
        for length in (8.2, 9.2, 10.2):
            pin = geometry.lock_pin(self.p | {'pin_shaft_length_mm': length})
            # Reject the old axial slit and any enlarged retaining barb.
            core = geometry.box(-.2, .2, -.2, .2, 1.21, length+1.19)
            self.assertLess((core-pin).volume(), 1e-6)
            vertices = geometry.mesh(pin).vertices
            shaft = vertices[vertices[:, 2] > 1.201]
            np.testing.assert_allclose(np.linalg.norm(shaft[:, :2], axis=1), 1.48, atol=1e-5)
            self.assertAlmostEqual(pin.bounding_box()[5], length+1.2)

    def test_dome_root_tip_and_connected_lids(self):
        p = self.p
        x = p['closed_pivot_x_mm']
        root = p['body_height_mm'] - p['flag_thickness_mm']
        bottom = geometry.slider_top(p) - p['detent_interference_mm']
        for terminal in (False, True):
            lid = geometry.lid(p, terminal)
            bump = lid ^ geometry.box(x-2, x+2, -2, 2, bottom-.1, root-.001)
            bounds = bump.bounding_box()
            self.assertAlmostEqual(bounds[2], bottom, places=5)
            self.assertGreater(bounds[3]-bounds[0], 3.59)
            tip = lid ^ geometry.box(x-2, x+2, -2, 2, bottom, bottom+.05)
            self.assertLess(tip.bounding_box()[3]-tip.bounding_box()[0], 1)
            self.assertEqual(len(geometry.mesh(lid).split()), 1)

    def test_shorter_pin_preserves_head_and_remaining_shaft(self):
        old = geometry.lock_pin(self.p | {'pin_shaft_length_mm': 10.2})
        new = geometry.lock_pin(self.p)
        self.assertLess((new-old).volume(), 1e-6)
        self.assertAlmostEqual(new.bounding_box()[5], 11.0)
        self.assertAlmostEqual(self.p['body_height_mm']-self.p['pin_shaft_length_mm'], .2)
        self.assertAlmostEqual((old-new).volume(), geometry.cylinder(0, 0, 1.48, 0, .4).volume(), places=5)

    def test_lid_thinning_preserves_lower_surfaces_and_other_parts(self):
        p = self.p
        old = p | dict(body_height_mm=10.4, flag_thickness_mm=2., pin_shaft_length_mm=10.2)
        clip = geometry.box(-100, 100, -100, 100, -1, p['body_height_mm'])
        for terminal in (False, True):
            before = geometry.lid(old, terminal) ^ clip
            after = geometry.lid(p, terminal)
            self.assertLess((before-after).volume() + (after-before).volume(), 1e-6)
            before, after = geometry.base(old, terminal=terminal), geometry.base(p, terminal=terminal)
            self.assertLess((before-after).volume() + (after-before).volume(), 1e-6)
        for build_part in (geometry.slider, geometry.star):
            before, after = build_part(old), build_part(p)
            self.assertLess((before-after).volume() + (after-before).volume(), 1e-6)

    def test_star_geometry_unchanged_by_thinning(self):
        old = self.p | dict(body_height_mm=12.4, base_height_mm=8.8, slider_thickness_mm=4.6)
        before, after = geometry.star(old), geometry.star(self.p)
        self.assertLess((before-after).volume() + (after-before).volume(), 1e-6)

    def test_gap_audit_rejects_crossing_with_midpoint_outside_gap(self):
        path = (.2, np.array([-1., 0.]), np.array([10., 0.]), 'wall')
        with self.assertRaisesRegex(AssertionError, 'fused'):
            slicing.require_gap([path], .2, np.zeros(2), [0., -.1], [1., .1], 'slit')
        slicing.require_gap([path], .4, np.zeros(2), [0., -.1], [1., .1], 'slit')

    def test_arc_paths_preserve_circular_gaps_and_following_position(self):
        for command, side in (('G2', -1), ('G3', 1)):
            paths = slicing.extrusion_paths(f'; Z_HEIGHT: 0.2\nM83\nG1 X1 Y0\n'
                f'{command} X-1 Y0 I-1 J0 E1\nG1 X-1 Y2 E0.1\n')
            arc = paths[:-1]
            points = np.vstack([a for _, a, _, _ in arc] + [arc[-1][2]])
            np.testing.assert_allclose(np.linalg.norm(points, axis=1), 1, atol=1e-8)
            self.assertGreater(side * points[len(points) // 2, 1], .99)
            np.testing.assert_allclose(paths[-1][1], [-1, 0])
            slicing.require_gap(arc, .2, np.zeros(2), [-.1, -.1], [.1, .1], 'circular void')

    def test_absolute_extrusion_and_relative_moves_update_position(self):
        paths = slicing.extrusion_paths('; Z_HEIGHT: 0.2\nM82\nG92 E10\nG1 X1 Y0 E11\n'
            'G3 X0 Y1 I-1 J0 E11.5\nG91\nG1 X0 Y1 E11.6\n')
        np.testing.assert_allclose(paths[-1][1], [0, 1])
        np.testing.assert_allclose(paths[-1][2], [0, 2])

    def test_variable_width_comments_follow_straight_and_arc_paths(self):
        paths = slicing.extrusion_paths('; Z_HEIGHT: 0.2\nM83\nG1 X1 Y0\n'
            '; LINE_WIDTH: 0.62\nG1 X2 Y0 E0.1\n'
            '; LINE_WIDTH: 0.5\nG3 X0 Y2 I-2 J0 E0.1\n', with_width=True)
        self.assertEqual(paths[0][4], .62)
        self.assertTrue(all(path[4] == .5 for path in paths[1:]))
        self.assertGreater(len(paths), 2)


if __name__ == '__main__':
    unittest.main()
