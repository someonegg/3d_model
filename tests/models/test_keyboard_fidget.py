"""Ensure curved toolpaths cannot masquerade as missing spring material."""
import importlib.util
from pathlib import Path
import unittest
import sys
from unittest.mock import patch
import numpy as np
from tools.slicing_geometry import bead_envelope
spec = importlib.util.spec_from_file_location('keyboard_slice', Path(__file__).resolve().parents[2] / 'models/keyboard-fidget-fdm/src/slice.py')
slicing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(slicing)

class KeyboardToolpathTests(unittest.TestCase):

    def test_arc_coverage_and_following_modal_position(self):
        paths = slicing.extrusion_segments('M83\n; Z_HEIGHT: 0.2\n; FEATURE: Outer wall\nG0 X1 Y0\nG3 X0 Y1 I-1 J0 E1\nG1 X0 Y2 E1\nG2 X1 Y1 I1 J0 E1\n')
        np.testing.assert_allclose(paths[0][1], [1, 0])
        first_arc = [a for z, a, b, feature in paths if b[1] <= 1 and a[0] >= 0]
        self.assertTrue(any((np.linalg.norm(a - np.sqrt(0.5)) < 0.04 for a in first_arc)))
        line = next((row for row in paths if np.allclose(row[2], [0, 2])))
        np.testing.assert_allclose(line[1], [0, 1])
        np.testing.assert_allclose(paths[-1][2], [1, 1])
        self.assertTrue(all((row[0] == 0.2 and row[3] == 'Outer wall' for row in paths)))

    def test_envelope_uses_actual_width_and_layer_height(self):
        rows=slicing.extrusion_segments('M83\n; Z_HEIGHT: 0.4\n; LAYER_HEIGHT: 0.2\n; LINE_WIDTH: 0.6\nG0 X0 Y0\nG1 X2 E1\n',dimensions=True)
        self.assertEqual(rows[0][4:],(.6,.2))
        envelope=bead_envelope(rows)
        bounds=envelope.bounding_box()
        np.testing.assert_allclose([bounds[2],bounds[5]],[.2,.4])
        self.assertAlmostEqual(bounds[4],.3,places=6)
        with self.assertRaisesRegex(AssertionError,'dimensions'):
            slicing.extrusion_segments('M83\n; Z_HEIGHT: 0.2\nG1 X1 E1',dimensions=True)

    def test_missing_peak_is_rejected(self):
        import manifold3d as mf
        paths=[(z,np.array([0.,0.]),np.array([2.,0.]),'Outer wall',.42,.2) for z in (.2,.4,.6)]
        plateau=mf.Manifold.cube((1,.1,.1)).translate((.5,-.05,.25))
        slicing.require_material(bead_envelope(paths),plateau,'cam plateau')
        with self.assertRaisesRegex(AssertionError,'cam plateau'):
            slicing.require_material(bead_envelope([r for r in paths if r[0]!=.4]),plateau,'cam plateau')

    def test_filled_clearance_is_rejected(self):
        import manifold3d as mf
        gap=mf.Manifold.cube((1,.1,.1)).translate((.5,-.05,.05))
        narrow=bead_envelope([(.2,np.array([0.,.5]),np.array([2.,.5]),'Outer wall',.4,.2)])
        slicing.require_clear(narrow,gap,'snap pocket')
        filled=bead_envelope([(.2,np.array([0.,.5]),np.array([2.,.5]),'Outer wall',1.2,.2)])
        with self.assertRaisesRegex(AssertionError,'filled'):
            slicing.require_clear(filled,gap,'snap pocket filled')

    def test_locating_slot_frame_toolpath_interference(self):
        import manifold3d as mf
        # Printed cartridge is translated on the plate and 6.2 mm above the
        # assembly origin. This bead is outside the old Y=9..17 contact mask.
        row=dict(assembly_to_print=np.eye(4).tolist(), plate_xy=[55,-35])
        row['assembly_to_print'][2][3]=-6.2
        mask=mf.Manifold.cube((4,10,3.2)).translate((18.05,-16,6.2))
        def frame(width):
            paths=[(.2,np.array([74.,-47.]),np.array([74.,-45.]),'Outer wall',width,.2)]
            return slicing.deposited_region(paths,row,np.zeros(2),mask)
        narrow=frame(.4)
        wide=frame(1.2)
        self.assertGreater(wide.volume(),narrow.volume())
        # Both seated and lifted endpoints clear; only the swept path collides.
        shell=mf.Manifold.cube((.3,1,.2)).translate((19.4,-11.5,2.5))
        empty=mf.Manifold()
        slicing.inspect_snap_frame_path(shell,empty,narrow,.1)
        for dz in (0,14.5):
            slicing.require_clear(shell.translate((0,0,dz)),wide,'endpoint')
        with self.assertRaisesRegex(AssertionError,'snap/frame insert'):
            slicing.inspect_snap_frame_path(shell,empty,wide,.1)
        # Starting at the opposite endpoint also traverses the same obstruction.
        with self.assertRaisesRegex(AssertionError,'snap/frame extract'):
            with patch.object(slicing.np,'linspace',side_effect=[[],np.linspace(0,14.5,146)]):
                slicing.inspect_snap_frame_path(shell,empty,wide,.1)

    def test_return_interference_is_rejected(self):
        import manifold3d as mf
        moving=mf.Manifold.cube((1,1,1))
        obstacle=moving.translate((0,0,2))
        slicing.require_clear(moving,obstacle,'return start')
        with self.assertRaisesRegex(AssertionError,'return'):
            for stroke in np.linspace(0,3,13):
                slicing.require_clear(moving.translate((0,0,float(stroke))),obstacle,'return path')

class KeyboardOverlapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        source=Path(__file__).resolve().parents[2]/'models/keyboard-fidget-fdm/src'
        with patch.dict(os.environ, MODEL_OUTPUT_DIR='/tmp'), patch.object(sys,'path',[str(source),*sys.path]):
            spec=importlib.util.spec_from_file_location('keyboard_overlap_verify',source/'verify.py')
            cls.verify=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.verify)

    def test_bounds_filter_preserves_exact_overlap(self):
        import manifold3d as mf
        a=mf.Manifold.cube((2,3,4)).rotate((13,27,41))
        # Include overlap, disjoint bounds, touching and overlapping bounds
        # without material overlap (the probe sits inside the hollow box).
        hollow=mf.Manifold.cube((4,4,4))-mf.Manifold.cube((2,2,2)).translate((1,1,1))
        pairs=[(a,a.translate(offset)) for offset in ((0,0,0),(.1,.2,.3),(20,0,0),(0,-20,0),(0,0,20))]
        pairs += [(mf.Manifold.cube((1,1,1)),mf.Manifold.cube((1,1,1)).translate((1,0,0))),
                  (hollow,mf.Manifold.cube((1,1,1)).translate((1.5,1.5,1.5))),
                  (a,mf.Manifold())]
        for left,right in pairs:
            self.assertAlmostEqual(self.verify.overlap(left,right),max(0.,(left^right).volume()),places=9)
            self.assertAlmostEqual(self.verify.overlap(right,left),max(0.,(left^right).volume()),places=9)

    def test_interference_is_detected_in_each_direction(self):
        import manifold3d as mf
        a=mf.Manifold.cube((1,1,1))
        for axis in range(3):
            for sign in (-1,1):
                offset=np.zeros(3);offset[axis]=sign*1.1
                self.verify.clear(a,a.translate(offset),'clear')
                offset[axis]=sign*.9
                with self.assertRaisesRegex(AssertionError,'injected'):
                    self.verify.clear(a,a.translate(offset),'injected')

class KeyboardElasticCacheTests(unittest.TestCase):
    setUpClass = classmethod(KeyboardOverlapTests.setUpClass.__func__)

    def make_cache(self, capacity=2):
        import manifold3d as mf
        self.block=mf.Manifold.cube((1,1,1))
        fixed={name:self.block.translate((10,10,10)) for name in ('shell','base')}
        self.profile=self.verify.MotionProfile()
        return self.verify.ElasticStateCache(None,fixed,self.profile,capacity)

    def test_exact_keys_include_every_deformation_and_placement(self):
        cache=self.make_cache(capacity=16)
        def get(values):
            return cache.get(dict(zip((-1,1),values[:2])),dict(zip((-1,1),values[2:4])),
                             dict(zip((-1,1),values[4:6])),*values[6:],'test')
        original=[.1]*8
        with patch.object(self.verify,'deformed',return_value=self.block) as build:
            first=get(original)
            self.assertIs(get(original),first)
            for index in range(8):
                changed=original.copy();changed[index]=np.nextafter(.1,1.)
                get(changed)
            self.assertEqual(build.call_count,9)
        self.assertEqual(cache.hits,1)
        self.assertEqual(self.profile.calls['elastic_fixed_collision'],18)
        # A new moving obstacle must still be tested after a cache hit.
        with self.assertRaisesRegex(AssertionError,'moving obstacle'):
            self.verify.clear(first,first,'moving obstacle')

    def test_lru_bound_and_disabled_cache(self):
        for capacity in (0,2):
            cache=self.make_cache(capacity)
            with patch.object(self.verify,'deformed',return_value=self.block) as build:
                for x in (0,1,0,2,1):
                    cache.get({-1:0,1:0},{-1:0,1:0},{-1:0,1:0},x,0,'lru')
                self.assertEqual(build.call_count,5 if capacity==0 else 4)
            self.assertLessEqual(cache.peak_entries,capacity)
            self.assertLessEqual(len(cache.entries),capacity)

    def test_failed_fixed_collision_is_never_cached(self):
        cache=self.make_cache()
        cache.solids['base']=self.block
        with patch.object(self.verify,'deformed',return_value=self.block) as build:
            for _ in range(2):
                with self.assertRaisesRegex(AssertionError,'elastic/base'):
                    cache.get({-1:0,1:0},{-1:0,1:0},{-1:0,1:0},0,0,'injected')
            self.assertEqual(build.call_count,2)
        self.assertFalse(cache.entries)

class KeyboardStructureTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[2] / 'models/keyboard-fidget-fdm/src'
        with patch.object(sys, 'path', [str(source), *sys.path]):
            spec = importlib.util.spec_from_file_location('keyboard_build', source / 'geometry.py')
            cls.build = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.build)
        cls.parts = cls.build.make_parts()

    def test_five_connected_print_parts(self):
        self.assertEqual(set(self.parts), {'shell','base','plunger','keycap','cartridge'})
        for name, part in self.parts.items():
            mesh, _ = self.build.printing(part, name)
            self.assertTrue(mesh.is_watertight, name)
            self.assertEqual(len(mesh.split()), 1, name)
            self.assertAlmostEqual(mesh.bounds[0, 2], 0, places=5)

    def test_wrong_cartridge_orientation_is_physically_rejected(self):
        for angle in (90, 180, 270):
            self.assertGreater((self.parts['cartridge'].rotate((0, 0, angle)) ^ self.parts['base']).volume(), 1)

    def test_symmetric_guide_accepts_reverse_orientation(self):
        self.assertLess((self.parts['plunger'].rotate((0, 0, 180)) ^ self.parts['shell']).volume(), .003)

    def test_surfaces_outside_edit_regions_match_baseline(self):
        expected = dict(shell=(10317.031350150453,9312.270612198388),
                        base=(6361.375346645979,5740.892495438256),
                        plunger=(4940.184509232189,2752.164634125348),
                        keycap=(1706.314958932425,1680.2869947598954),
                        cartridge=(1513.7380466303186,2982.5555884404084))
        b=self.build
        for name,part in self.parts.items():
            mask=b.box(.01,.01,.01,z=-10)
            for side in (-1,1):
                if name in ('shell','base'):
                    mask+=b.box(4,10,13,x=side*20.05,y=-11,z=2.3)
                if name=='plunger':
                    mask+=b.box(4,6.02,1.5,x=side*13.3,y=13,z=10.24)
                    mask+=b.box(4,1.12,1.5,x=side*13.3,y=-15.45,z=10.24)
                if name=='cartridge':
                    mask+=b.box(1.4,4,1,x=side*14,y=13,z=8.7)
            clipped=part-mask
            np.testing.assert_allclose([clipped.volume(),clipped.surface_area()],expected[name],rtol=0,atol=1e-5,err_msg=name)

    def test_support_and_snap_checks_on_final_meshes(self):
        import os
        source=Path(__file__).resolve().parents[2]/'models/keyboard-fidget-fdm/src'
        with patch.dict(os.environ, MODEL_OUTPUT_DIR='/tmp'), patch.object(sys,'path',[str(source),*sys.path]):
            spec=importlib.util.spec_from_file_location('keyboard_verify',source/'verify.py')
            verify=importlib.util.module_from_spec(spec);spec.loader.exec_module(verify)
        solids={name:verify.solid(self.build.mesh_of(part)) for name,part in self.parts.items()}
        self.assertGreaterEqual(verify.check_supports(solids)['minimum_lateral_clearance_mm'],.6-1e-5)
        result=verify.check_snaps(solids)
        self.assertTrue(result['hard_seat'])
        self.assertTrue(result['seated_clear'])
        self.assertAlmostEqual(result['maximum_required_wall_displacement_mm'],.2)
        self.assertFalse(result['elastic_insertion_verified'])
        self.assertEqual({r['direction'] for r in result['samples']},{'insert','extract'})

    def test_unmodified_keycap_vertices(self):
        import hashlib
        for name,digest in dict(keycap='1e4186021eaa93f22d9be5eac8fccdd3f679afb61bef818278cfeee024ef29c9').items():
            vertices=np.unique(self.build.mesh_of(self.parts[name]).vertices.round(5),axis=0)
            self.assertEqual(hashlib.sha256(vertices.astype('<f8').tobytes()).hexdigest(),digest,name)

    def test_keycap_interface_matches_previous_mesh_vertices(self):
        import hashlib
        vertices = self.build.mesh_of(self.parts['plunger']).vertices
        vertices = np.unique(vertices[vertices[:,2]>21.40001].round(5), axis=0)
        self.assertEqual(hashlib.sha256(vertices.astype('<f8').tobytes()).hexdigest(),
                         '0b93df444bfbbf4ff9d0fd15c20412a746cd2d89a3c7f174ebf65e53b6c7cc50')
    def test_layer_aligned_contact_and_cam_plateau(self):
        b=self.build
        self.assertAlmostEqual(b.P['contact_height'],.6)
        self.assertAlmostEqual((b.P['contact_bottom']-b.P['frame_bottom'])/.2,13)
        for side in (-1,1):
            for z in (10.9,11.1):
                material=b.box(.02,2,.02,x=side*13.57,y=13,z=z)
                self.assertAlmostEqual((material^self.parts['plunger']).volume(),material.volume(),places=6)
            void=b.box(.02,2,.02,x=side*13.64,y=13,z=11)
            self.assertLess((void^self.parts['plunger']).volume(),1e-7)

    def test_bottom_releases_contact_across_full_support_sink(self):
        b=self.build
        for side in (-1,1):
            pad=self.parts['cartridge']^b.box(1.21,3.81,.6,x=side*14,y=13,z=8.8)
            for dx in (-.2,0,.2):
                for fx in (-.1,.1):
                    for sink in np.linspace(0,.2,5):
                        contact=pad.translate((fx,0,-float(sink)))
                        plunger=self.parts['plunger'].translate((dx,0,-3))
                        self.assertLess((contact^plunger).volume(),1e-6,
                                        (side,dx,fx,sink))

    def test_printed_release_step_clears_sunk_contact(self):
        b=self.build
        pad=self.parts['cartridge']^b.box(1.21,3.81,.6,x=14,y=13,z=8.8)
        pad=pad.translate((-.1,0,-.2))
        def last_layer(exit_x):
            # Final .20 mm layer uses the profile at its centre (1.30 mm
            # above the plunger bed); its material reaches the layer top.
            edge=b.P['cam_peak']+(exit_x-b.P['cam_peak'])*.75
            paths=[(1.4,np.array([edge-.21,11.]),np.array([edge-.21,15.]),'Outer wall',.42,.2)]
            return bead_envelope(paths).translate((.2,0,10.25-3))
        slicing.require_clear(last_layer(b.P['cam_exit']),pad,'printed return release')
        with self.assertRaisesRegex(AssertionError,'return'):
            slicing.require_clear(last_layer(13.0),pad,'printed return interference')

    def test_local_plate_edge_clears_combined_lateral_offsets(self):
        b=self.build
        self.assertAlmostEqual(b.P['click_x'],15.2)
        self.assertAlmostEqual(b.P['window_edge'],17.7)
        for side in (-1,1):
            # The lip is .20 mm inside the planned plate edge; the full
            # .20 guide + .10 locating offsets require another .11 mm relief.
            probe=b.box(.01,.5,.8,x=side*(b.P['plate_edge']+.02),y=10.5,z=10.35)
            self.assertLess((probe ^ self.parts['plunger']).volume(),1e-7)
            self.assertGreaterEqual(b.P['shoe_inner']-b.P['plate_edge'],.30)

    def test_round_corner_clearance_is_radial(self):
        b = self.build
        for angle in np.linspace(0, np.pi/2, 13):
            for radius, filled in ((1.18, False),(1.22, True)):
                probe=b.box(.005,.005,.1,x=6+radius*np.cos(angle),y=13+radius*np.sin(angle),z=14)
                volume=(probe ^ self.parts['shell']).volume()
                self.assertAlmostEqual(volume,probe.volume() if filled else 0,places=7)
        # A square +/-0.20 mm envelope is physically outside the round offset.
        self.assertGreater((self.parts['plunger'].translate((.2,.2,0)) ^ self.parts['shell']).volume(), .5)

    def test_guide_lands_reliefs_and_mouths(self):
        b = self.build
        # Probe actual solids, including all four faces and both axial ramps.
        for angle in (0, 90, 180, 270):
            half, land = (7, 12) if angle % 180 == 0 else (14, 5)
            for z in (11.27, 11.56, 12, 14, 17.9, 18.29, 18.58):
                relief = .4 * min(1, (z-11.26)/.6, (18.59-z)/.6)
                for y in (-land, land):
                    probe = b.box(.02,.02,.01,x=half-.03,y=y,z=z).rotate((0,0,angle))
                    self.assertAlmostEqual((probe ^ self.parts['plunger']).volume(), probe.volume(), places=6)
                probe = b.box(.01,.1,.01,x=half-relief+.015,z=z).rotate((0,0,angle))
                self.assertLess((probe ^ self.parts['plunger']).volume(), 1e-7)
        for z in (11.3,11.5,12,15,18.15,18.35):
            mouth = max(0, .4-min(z-11.25,18.4-z))
            for angle in (0,90,180,270):
                half = 7.2 if angle % 180 == 0 else 14.2
                inside = b.box(.01,.1,.01,x=half+mouth-.03,z=z).rotate((0,0,angle))
                outside = b.box(.01,.1,.01,x=half+mouth+.03,z=z).rotate((0,0,angle))
                self.assertLess((inside ^ self.parts['shell']).volume(),1e-7)
                self.assertAlmostEqual((outside ^ self.parts['shell']).volume(),outside.volume(),places=6)

    def test_rigid_stops_reject_overtravel(self):
        self.assertGreater((self.parts['plunger'].translate((0, 0, 0.1)) ^ self.parts['shell']).volume(), 1)
        self.assertGreater((self.parts['keycap'].translate((0, 0, -3.1)) ^ self.parts['shell']).volume(), 1)

    def test_internal_bosses_and_full_shell_insertion(self):
        for name in ('shell','base'):
            bounds=np.array(self.parts[name].bounding_box())
            np.testing.assert_allclose(bounds[[0,1,3,4]],[-22.5,-22.5,22.5,22.5])
        for offset in np.linspace(0,40,81):
            shell=self.parts['shell'].translate((0,0,float(offset)))
            for fixed in ('cartridge','plunger'):
                self.assertLess((shell ^ self.parts[fixed]).volume(),.003)
        import manifold3d as mf
        for x,y in self.build.P['screw_centers']:
            bore=mf.Manifold.cylinder(7.5,.8,.8,64).translate((x,y,.5))
            self.assertLess((bore ^ self.parts['base']).volume(),.003)
            self.assertLess((bore ^ self.parts['shell']).volume(),.003)
            roof=mf.Manifold.cylinder(1,.8,.8,64).translate((x,y,12))
            self.assertGreater((roof ^ self.parts['shell']).volume(),1)

    def test_replacement_bundle_has_only_new_parts(self):
        import json
        root = Path(__file__).resolve().parents[2] / 'models/keyboard-fidget-fdm'
        bundle = json.loads((root / 'bundle.json').read_text())
        files = [r['path'] for r in bundle['files']]
        self.assertEqual(len(files), len(set(files)))
        self.assertEqual({n for n in files if n.endswith('.stl')}, {n + '.stl' for n in self.parts} | {'all-parts.stl'})
if __name__ == '__main__':
    unittest.main()
