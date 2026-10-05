"""Protect the paired long-arm cap and spring geometry."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np
import manifold3d as mf
import trimesh

spec=importlib.util.spec_from_file_location('round_button_geometry',Path(__file__).resolve().parents[2]/'models/fidget-button-fdm/src/geometry.py')
build=importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

def solid(m):
    return mf.Manifold(mf.Mesh(np.asarray(m.vertices,dtype=np.float32),np.asarray(m.faces,dtype=np.uint32)))

class ButtonTests(unittest.TestCase):
    def assert_end_loading(self, parts):
        spring=solid(parts['弹片'])
        cap=solid(parts['按帽']).rotate((180,0,0)).translate((0,0,build.SPRING_THICKNESS+build.P['pusher_height']))
        allowed_contacts=mf.Manifold()
        for side in (-1,1):
            tip=mf.Manifold.cube((build.P['pad_length'],build.P['pad_size'],.2),center=True).translate((side*build.P['pad_x'],side*build.P['pad_y'],build.SPRING_THICKNESS))
            self.assertGreater((spring ^ tip).volume(),.09*build.P['pad_length']*build.P['pad_size'])
            self.assertGreater((cap.translate((0,0,-.1)) ^ tip).volume(),.09*build.P['pad_length']*build.P['pad_size'])
            allowed_contacts += mf.Manifold.cube((build.P['pad_length'],build.P['pad_size'],20),center=True).translate((side*build.P['pad_x'],side*build.P['pad_y'],build.SPRING_THICKNESS))
        unwanted=(spring ^ cap.translate((0,0,-.1))) - allowed_contacts
        self.assertLess(unwanted.volume(),.003,'contact outside the end pads')

    def test_protrusion_travel_and_internal_guide_position(self):
        self.assertEqual(build.P['travel'], 3)
        self.assertEqual(build.P['cap_face_z']-build.P['shell_top_z'], 4)
        self.assertEqual(build.P['cap_face_z']-build.P['travel']-build.P['shell_top_z'], 1)
        self.assertAlmostEqual(build.P['cap_face_z']-build.P['face_height'], 14.5)
        self.assertAlmostEqual(build.P['cap_face_z']-build.P['skirt_top'], 12.5)
        self.assertAlmostEqual(build.P['cap_face_z']-build.P['pusher_height'], build.P['spring_seat_z']+build.SPRING_THICKNESS)
        self.assertAlmostEqual(build.P['spring_seat_z']+build.SPRING_THICKNESS-build.P['stop_z'], 3)
        self.assertGreaterEqual(build.SPRING_THICKNESS, .68)

    def test_only_end_pads_load_arms(self):
        self.assert_end_loading(dict(build.make_parts()))

    def test_midspan_and_root_contacts_are_rejected(self):
        parts=dict(build.make_parts())
        for x,y in ((8,build.P['pad_y']),(-10,build.P['pad_y']),(-8,-build.P['pad_y'])):
            with self.subTest(contact_xy=(x,y)):
                # Model-space Y reverses when the face-down cap is assembled.
                cap=solid(parts['按帽']) + mf.Manifold.cube((2,2,build.P['pusher_height']-build.P['skirt_top'])).translate((x-1,-y-1,build.P['skirt_top']))
                raw=cap.to_mesh()
                mutant=trimesh.Trimesh(np.asarray(raw.vert_properties)[:,:3],np.asarray(raw.tri_verts),process=True)
                with self.assertRaisesRegex(AssertionError,'contact outside the end pads'):
                    self.assert_end_loading(parts | {'按帽':mutant})
    def test_keyed_cup_seats_and_guides_cap(self):
        parts=dict(build.make_parts())
        cup=solid(parts['弹片']).translate((0,0,build.P['spring_seat_z']))
        base=solid(parts['底盖']).translate((0,0,-2.4))
        self.assertLess((cup ^ base).volume(),.003)
        self.assertGreater((cup.translate((0,0,-.2)) ^ base).volume(),50)
        cap=solid(parts['按帽']).rotate((180,0,0)).translate((0,0,build.P['cap_face_z']))
        self.assertLess((cup ^ cap).volume(),.003)
        self.assertGreater((cup ^ cap.rotate((0,0,10))).volume(),.1)
        self.assertGreater((cup ^ cap.translate((.5,0,0))).volume(),.1)

    def test_free_tips_and_side_gaps_remain_open(self):
        section = build.spring_section()
        for side in (-1, 1):
            # Separating the root must leave exactly one detached arm.
            cut = mf.CrossSection.square((1, 4), center=True).translate((side*-11.9, side*build.P['pad_y']))
            self.assertEqual(len((section-cut).decompose()), 2)
            for x,y,w,h in ((build.P['arm_tip']+.075,build.P['pad_y'],.1,build.P['arm_width']), (build.P['pad_x'],build.P['pad_y']-build.P['arm_width']/2-.15,1,.2), (build.P['pad_x'],build.P['pad_y']+build.P['arm_width']/2+.15,1,.2)):
                gap = mf.CrossSection.square((w,h),center=True).translate((side*x,side*y))
                self.assertLess((section ^ gap).area(), 1e-6)

    def test_four_connected_flat_parts(self):
        parts=build.make_parts()
        self.assertEqual([name for name,m in parts],['外壳','按帽','底盖','弹片'])
        for name,m in parts:
            self.assertTrue(m.is_watertight,name)
            self.assertEqual(len(m.split()),1,name)
            self.assertAlmostEqual(m.bounds[0,2],0,places=5)
if __name__=='__main__':
    unittest.main()
