"""Modal path parsing and conservative deposited material checks."""
import unittest
import numpy as np
import manifold3d as mf
from tools.slicing_geometry import extrusion_segments, bead_envelope, require_clear, require_material


class SharedPathTests(unittest.TestCase):
    def test_coordinate_and_extrusion_modes_reset_and_unbounded_height(self):
        paths = extrusion_segments('G90\nM82\nG92 X10 Y20 Z25 E100\nG1 X12 E101\n'
                                   'G91\nM83\nG1 Y3 E1\nG1 X1 E-1\nG92 E0\n'
                                   'G90\nM82\nG1 X15 Y24 E1\n')
        self.assertEqual(len(paths), 3)
        np.testing.assert_allclose(paths[0][1], [10, 20])
        np.testing.assert_allclose(paths[1][2], [12, 23])
        np.testing.assert_allclose(paths[2][1], [13, 23])
        self.assertEqual(paths[0][0], 25)

    def test_full_circle_and_relative_arc_followed_by_line(self):
        paths = extrusion_segments('M83\nG0 X1 Y0 Z.2\nG3 X1 Y0 I-1 J0 E2\nG91\n'
                                   'G2 X-1 Y1 I-1 J0 E1\nG1 X2 E1')
        self.assertGreater(len(paths), 30)
        np.testing.assert_allclose(paths[-2][2], [0, 1], atol=1e-12)
        np.testing.assert_allclose(paths[-1][2], [2, 1])
        self.assertTrue(any(np.linalg.norm(a - [-1, 0]) < .05 for _, a, _, _ in paths))
        with self.assertRaisesRegex(AssertionError, 'centre'):
            extrusion_segments('G2 X1 E1')

    def test_missing_dimensions_and_actual_material_interference(self):
        with self.assertRaisesRegex(AssertionError, 'dimensions'):
            extrusion_segments('G1 X1 E1', dimensions=True)
        rows = extrusion_segments('; Z_HEIGHT: .4\n; LAYER_HEIGHT: .2\n; LINE_WIDTH: .6\n'
                                  'G1 X2 E1', dimensions=True)
        solid = bead_envelope(rows)
        np.testing.assert_allclose(np.array(solid.bounding_box())[[2, 5]], [.2, .4])
        probe = mf.Manifold.cube((1, .1, .1)).translate((.5, -.05, .25))
        require_material(solid, probe, 'center')
        with self.assertRaisesRegex(AssertionError, 'interference'):
            require_clear(solid, probe, 'injected collision')
        with self.assertRaisesRegex(AssertionError, 'missing'):
            require_material(bead_envelope([]), probe, 'removed layer')

    def test_radius_arcs_select_short_and_long_sweeps(self):
        for command, end in [('G2', [0, -1]), ('G3', [0, 1])]:
            short = extrusion_segments(f'G0 X1 Y0 Z.2\n{command} X0 Y{end[1]} R1 E1')
            long = extrusion_segments(f'G0 X1 Y0 Z.2\n{command} X0 Y{end[1]} R-1 E1')
            np.testing.assert_allclose(short[-1][2], end)
            self.assertGreater(len(long), len(short) * 2)
        with self.assertRaisesRegex(AssertionError, 'radius'):
            extrusion_segments('G2 X3 Y0 R1 E1')
