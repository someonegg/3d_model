"""Regressions for cam direction, independent stops and portable STL precision."""
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np
import trimesh

SOURCE = Path(__file__).resolve().parents[2] / 'models/retractable-shuriken-fdm/src'


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, SOURCE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


geometry = load('shuriken_geometry', 'geometry.py')
with patch.dict(sys.modules, {'geometry': geometry}):
    assembly = load('shuriken_assembly', 'assembly.py')
    slicing = load('shuriken_slicing', 'slice.py')
    with patch.dict(sys.modules, {'assembly': assembly}):
        verify = load('shuriken_verify', 'verify.py')


class RetractableShurikenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parts = geometry.make_parts()

    def test_clearance_variants_follow_the_same_motion(self):
        for gap in (.20, .25, .30):
            with patch.dict(geometry.P, guide_clearance=gap):
                parts = geometry.make_parts()
                for angle in (0, 15, 30, 45, 60):
                    rotor = parts['rotor'].rotate((0, 0, angle))
                    pin = geometry.cylinder(1.6+gap-.01, 1.5,
                                            x=14.5+angle/4, z=geometry.CAM_Z+.3)
                    verify.clear(pin, rotor, f'cam/{gap}/{angle}')
                    wing = parts['wing-1'].translate((angle/4, 0, 0))
                    verify.clear(wing, parts['base'], f'guide/{gap}/{angle}')
        # Reversing the cam winding must fail at an intermediate stroke.
        wrong = self.parts['rotor'].rotate((0, 0, -30))
        with self.assertRaisesRegex(AssertionError, 'intersection'):
            verify.clear(self.parts['wing-1'].translate((7.5, 0, 0)), wrong, 'reversed cam')

    def test_missing_independent_stop_is_rejected(self):
        verify.check_stops(self.parts['base'], self.parts['rotor'])
        defective = self.parts['base'] - geometry.cylinder(1.6, 6, x=8, z=2)
        with self.assertRaisesRegex(AssertionError, 'stop absent'):
            verify.check_stops(defective, self.parts['rotor'])

    def test_stl_remains_closed_after_plate_translation(self):
        for name, part in self.parts.items():
            mesh, _ = geometry.print_mesh(part, name)
            mesh.apply_translation([128.123, 125.678, 0])
            raw = trimesh.load(io.BytesIO(mesh.export(file_type='stl')), file_type='stl', process=False)
            vertices, inverse = np.unique(raw.vertices, axis=0, return_inverse=True)
            result = trimesh.Trimesh(vertices, inverse[raw.faces], process=False)
            self.assertTrue(result.is_watertight, name)
            self.assertTrue(result.is_winding_consistent, name)
            self.assertTrue(np.all(result.area_faces > 1e-12), name)

    def test_gcode_arcs_and_coordinate_modes_do_not_skip_extrusion(self):
        text = '; Z_HEIGHT: 0.2\nM82\nG92 E10\nG1 X1 Y0 E11\nG3 X0 Y1 I-1 J0 E11.5\nG91\nG1 X0 Y1 E11.6\n'
        paths = slicing.extrusion_paths(text)[.2]
        self.assertGreater(len(paths), 6)
        np.testing.assert_allclose(paths[-1][0], [0, 1])
        np.testing.assert_allclose(paths[-1][1], [0, 2])
        arc = np.vstack([a for a, _, _ in paths[1:-1]])
        np.testing.assert_allclose(np.linalg.norm(arc, axis=1), 1, atol=1e-8)


if __name__ == '__main__':
    unittest.main()
