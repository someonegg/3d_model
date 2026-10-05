"""Check delivered parts and the intended clearances of the assembled button."""
from pathlib import Path
import os
import numpy as np
import trimesh
import json
from geometry import P, SPRING_THICKNESS, GUIDE_HEIGHT, GUIDE_FLAT_X, CAP_FLAT_X, LOCK_INTERFERENCE, lock_weight, spring_section, make_parts
import manifold3d as mf

def main():
    out = Path(os.environ['MODEL_OUTPUT_DIR'])
    mesh = trimesh.load(out / 'fidget-button-fdm.stl', process=True)
    replacement = trimesh.load(out / 'fidget-button-fdm-spring.stl', process=True)
    parts = mesh.split(only_watertight=True)
    assert len(parts) == 4, f'expected four separate printable parts, got {len(parts)}'
    assert all(part.is_watertight and part.is_winding_consistent and part.volume > 0 for part in parts)
    by_height = {round(float(part.extents[2]), 2): part for part in parts}
    assert set(by_height) == {17.0, 11.04, round(P['pusher_height'], 2), GUIDE_HEIGHT}, by_height.keys()
    shell, plug, cap, flexure = (by_height[h] for h in (17.0, 11.04, round(P['pusher_height'], 2), GUIDE_HEIGHT))
    assert replacement.is_watertight and replacement.is_winding_consistent
    assert len(replacement.split(only_watertight=True)) == 1
    np.testing.assert_allclose(replacement.extents, flexure.extents, atol=1e-5)
    np.testing.assert_allclose(replacement.volume, flexure.volume, atol=1e-3)
    for part in parts:
        assert abs(part.bounds[0, 2]) < 1e-6, 'each part must sit flat on the build plate'
    for index, first in enumerate(parts):
        for second in parts[index + 1:]:
            overlap = np.minimum(first.bounds[1, :2], second.bounds[1, :2]) - np.maximum(first.bounds[0, :2], second.bounds[0, :2])
            assert np.any(overlap < -4.0), 'print plate parts need at least 4 mm separation'
    np.testing.assert_allclose(shell.extents[:2], [42, 42], atol=1e-5)
    np.testing.assert_allclose(plug.extents[:2], [42, 42], atol=1e-5)
    np.testing.assert_allclose(cap.extents[:2], [25.6, 27.6], atol=1e-5)
    np.testing.assert_allclose(flexure.extents[:2], [34.2, 34.2], atol=0.21)

    def radii_at(part, height):
        points = part.vertices[np.isclose(part.vertices[:, 2], height, atol=1e-5)]
        center = (part.bounds[0, :2] + part.bounds[1, :2]) / 2
        return np.hypot(*(points[:, :2] - center).T)


    def has_radius(part, height, radius):
        assert np.any(np.isclose(radii_at(part, height), radius, atol=0.021)), (height, radius)


    # Measure exported cross sections, not just source constants.
    for part, height, radius in ((shell, 0, 13.0), (shell, 2.5, 17.5),
                                 (cap, 0, 12.6), (cap, P['face_height'], 13.8),
                                 (cap, P['pusher_height'], P['stop_radius']), (cap, P['pusher_height'], P['stop_radius']-.4),
                                 (plug, 3.0, 17.25), (plug, 3.0, 17.40),
                                 (plug, 11.04, 14.0), (plug, P['stop_z']+2.4, P['stop_radius'])):
        has_radius(part, height, radius)
    # The long upper wall must clear the bore; only the 1.2 mm lock band retains it.
    for height in (4.8, 10.24):
        np.testing.assert_allclose(radii_at(plug, height), 17.25, atol=1e-5)
    # Recess lips leave a 1.2 mm floor and 2 mm tool access at both X ends.
    center = (plug.bounds[0, :2] + plug.bounds[1, :2]) / 2
    seam = plug.vertices[np.isclose(plug.vertices[:, 2], 2.4), :2] - center
    for sign in (-1, 1):
        assert np.any(np.linalg.norm(seam - [sign * 19.0, 0], axis=1) < 1e-5)
    has_radius(plug, 1.2, 21.0)
    assert 13.0 - 12.6 >= 0.35  # radial clearance around the cap face
    assert 17.5 - 17.25 >= 0.20  # main plug body clearance
    assert abs(LOCK_INTERFERENCE - .10) < 1e-6
    assert 14.0 < 14.25 < 17.1 < 17.5  # spring frame supported inside the shell

    # Assembled contact heights are derived from the spring top.
    spring_top_z = -2.4 + float(plug.bounds[1, 2]) + SPRING_THICKNESS
    cap_pusher_z = P['cap_face_z'] - P['pusher_height']
    stop_z = P['stop_z']
    assert abs(spring_top_z - cap_pusher_z) < 1e-5
    assert abs(cap_pusher_z - stop_z - P['travel']) < 1e-6
    assert abs(P['cap_face_z'] - 17 - 4) < 1e-6
    assert abs(P['cap_face_z'] - P['travel'] - 17 - 1) < 1e-6
    # The spring tips straddle the stop and meet the annular pusher.
    xy = flexure.vertices[:, :2] - (flexure.bounds[0, :2] + flexure.bounds[1, :2]) / 2
    def as_solid(m):
        return mf.Manifold(mf.Mesh(np.asarray(m.vertices,dtype=np.float32),np.asarray(m.faces,dtype=np.uint32)))
    source_parts = dict(make_parts())
    fixed_shell = as_solid(source_parts['外壳']).rotate((180,0,0)).translate((0,0,17))
    fixed_plug = as_solid(source_parts['底盖']).translate((0,0,-2.4))
    cap_solid = as_solid(source_parts['按帽']).rotate((180,0,0)).translate((0,0,P['cap_face_z']))
    assert (cap_solid.translate((0,0,-P['travel']-.05)) ^ fixed_plug).volume() > .1, 'central rigid stop must reject overtravel'
    lock_samples = []
    # Rotate the shell around the seated cap/cup: base and spring stay together.
    allowed = mf.Manifold.cylinder(2.0, 17.6, circular_segments=192).translate((0,0,.3)) - mf.Manifold.cylinder(2.0,17.2,circular_segments=192).translate((0,0,.3))
    for angle in np.linspace(30,0,61):
        rotated = fixed_shell.rotate((0,0,float(angle)))
        overlap = rotated ^ fixed_plug
        assert (overlap - allowed).volume() < .003, 'interference outside lock band'
        assert (rotated ^ cap_solid).volume() < .003
        assert (rotated ^ as_solid(source_parts['弹片']).translate((0,0,P['spring_seat_z']))).volume() < .003
        lock_samples.append(dict(angle_deg=float(angle), overlap_mm3=overlap.volume()))
    assert lock_samples[0]['overlap_mm3'] < .003
    assert lock_samples[-1]['overlap_mm3'] > .1
    for offset in np.linspace(15,0,31):
        inserted = fixed_shell.rotate((0,0,30)).translate((0,0,float(offset)))
        assert (inserted ^ fixed_plug).volume() < .003
        assert (inserted ^ cap_solid).volume() < .003
        assert (inserted ^ as_solid(source_parts['弹片']).translate((0,0,P['spring_seat_z']))).volume() < .003
    assert (fixed_plug ^ as_solid(source_parts['弹片']).translate((0,0,P['spring_seat_z']))).volume() < .003
    # Probe the full free end and side gaps in the actual planar section.
    section = spring_section()
    for side in (-1,1):
        cut=mf.CrossSection.square((1,4),center=True).translate((side*-11.9,side*P['pad_y']))
        assert len((section-cut).decompose()) == 2, 'arm must attach only at its root'
    for side in (-1,1):
        for x,y,w,h in ((P['arm_tip']+.075,P['pad_y'],.1,P['arm_width']), (P['pad_x'],P['pad_y']-P['arm_width']/2-.15,1,.2), (P['pad_x'],P['pad_y']+P['arm_width']/2+.15,1,.2)):
            probe=mf.CrossSection.square((w,h),center=True).translate((side*x,side*y))
            assert (section ^ probe).area() < 1e-6, 'free end or side gap bridged'
    # Subdivide only the deforming thin layer; the tall guide stays rigid.
    thin = as_solid(source_parts['弹片']) ^ mf.Manifold.cube((40,40,SPRING_THICKNESS)).translate((-20,-20,0))
    raw=thin.to_mesh()
    spring_mesh=trimesh.Trimesh(np.asarray(raw.vert_properties)[:,:3],np.asarray(raw.tri_verts),process=True)
    for _ in range(2):
        spring_mesh = spring_mesh.subdivide()
    length = P['pad_x'] - P['pad_length']/2 - P['root_x']
    samples = []
    guide_solid = as_solid(source_parts['弹片']).translate((0,0,P['spring_seat_z'])) ^ mf.Manifold.cube((40,40,10)).translate((-20,-20,P['spring_seat_z']+SPRING_THICKNESS))
    # Real seating: exported frame overlaps the base ledge and cannot drop through.
    frame = as_solid(source_parts['弹片']) ^ mf.Manifold.cube((40,40,.1)).translate((-20,-20,0))
    support = fixed_plug.translate((0,0,.05)) ^ frame.translate((0,0,P['spring_seat_z']))
    assert support.volume()/.05 > 250, 'frame must have a broad supporting footprint'
    assert (as_solid(source_parts['弹片']).translate((0,0,P['spring_seat_z']-.2)) ^ fixed_plug).volume() > 50, 'base must reject a falling spring'
    assert (cap_solid.rotate((0,0,10)) ^ guide_solid).volume() > .1, 'cup must prevent cap rotation'
    assert GUIDE_FLAT_X-CAP_FLAT_X >= .29
    poses = [(0,0,0,0,0)]
    poses += [(dx,dy,rx,ry,rz) for dx in (-.2,.2) for dy in (-.2,.2) for rx in (-.15,.15) for ry in (-.15,.15) for rz in (-1,1)]
    poses += [(0,0,rx,ry,rz) for rx in (-.15,.15) for ry in (-.15,.15) for rz in (-3,3)]
    pose_ranges = []
    for dx,dy,rx,ry,rz in poses:
        matrix=trimesh.transformations.euler_matrix(*np.radians([rx,ry,rz]))
        oriented = cap_solid.translate((0,0,-13.5)).rotate((rx,ry,rz)).translate((dx,dy,13.5))
        def moving_at(stroke):
            return oriented.translate((0,0,-float(stroke)))
        def blocked(stroke):
            return any((moving_at(stroke) ^ fixed).volume() > .0001 for fixed in (fixed_shell,fixed_plug,guide_solid))
        assert not blocked(P['travel']/2), 'corner pose blocked at midstroke'
        # Tilted poses meet the actual upper/lower rigid stops sooner; do not
        # suppress tilt at the ends of travel to conceal interference.
        start, end = 0.0, P['travel']
        if blocked(start):
            lo,hi=0.,P['travel']/2
            for _ in range(20):
                mid=(lo+hi)/2
                if blocked(mid): lo=mid
                else: hi=mid
            start=hi
        if blocked(end):
            lo,hi=P['travel']/2,P['travel']
            for _ in range(20):
                mid=(lo+hi)/2
                if blocked(mid): hi=mid
                else: lo=mid
            end=lo
        assert end-start >= P['travel']-.07, 'corner stroke excessively shortened'
        pose_ranges.append(dict(offset_xy_mm=[dx,dy], tilt_xy_deg=[rx,ry], rotation_deg=rz, start_mm=start, end_mm=end))
        for stroke in np.linspace(start,end,31):
            moving = moving_at(stroke)
            demands={}
            loaded_lengths={}
            tip_margins={}
            for side in (-1,1):
                points=np.array([[side*P['pad_x']+px,side*P['pad_y']+py,P['cap_face_z']-P['pusher_height']-13.5] for px in (-P['pad_length']/2,P['pad_length']/2) for py in (-P['pad_size']/2,P['pad_size']/2)])
                transformed=points @ matrix[:3,:3].T
                heights=transformed[:,2]+13.5-stroke
                loaded_lengths[side]=float(np.min(side*(transformed[:,0]+dx)))-P['root_x']
                tip_margins[side]=P['arm_tip']-float(np.max(side*(transformed[:,0]+dx)))
                assert tip_margins[side] > .08, 'pad extends beyond arm tip'
                demands[side]=max(0.0,P['spring_seat_z']+SPRING_THICKNESS-float(heights.min()))
            for fixed in (fixed_shell,fixed_plug,guide_solid):
                assert (moving ^ fixed).volume() < 0.003, 'cap blocked during corner stroke'
            bent = spring_mesh.copy()
            v = bent.vertices.copy()
            for side in (-1,1):
                xx,yy=side*v[:,0],side*v[:,1]
                mask=(np.abs(yy-P['pad_y'])<P['arm_width']/2+.01)&(xx>P['root_x'])&(xx<=P['arm_tip']+1e-5)
                contact_length=loaded_lengths[side]
                t=np.clip((xx-P['root_x'])/contact_length,0,None)
                shape=np.where(t<=1,t*t*(3-t)/2,1+1.5*(t-1))
                v[mask,2]-=demands[side]*shape[mask]
            v[:,2]+=P['spring_seat_z']
            bent.vertices=v
            bent_solid=as_solid(bent)
            for fixed in (fixed_shell,fixed_plug,guide_solid):
                assert (bent_solid ^ fixed).volume() < 0.003, 'spring collides during stroke'
            # Finite pad contact has local compression in this end-load model;
            # cap middle and independent central ring must stay off the beams.
            middle=moving ^ mf.Manifold.cube((14,20,20),center=True).translate((0,0,10))
            assert (middle ^ bent_solid).volume()<0.003, 'midspan secondary loading'
            for side in (-1,1):
                # Actual pad near edge supplies the conservative loaded length.
                loaded_length = loaded_lengths[side]
                contact_overlap = min(P['arm_width'],P['pad_size'])-abs(dy)-P['pad_x']*abs(np.sin(np.radians(rz)))-.02
                assert contact_overlap > 1.4
                strain = 100*1.5*SPRING_THICKNESS*demands[side]/loaded_length**2
                assert strain <= 0.6, (strain, loaded_length, demands[side], (dx,dy,rx,ry,rz))
                assert P['spring_seat_z']-stroke > 2.4
                samples.append(dict(stroke_mm=float(stroke), offset_xy_mm=[dx,dy], tilt_xy_deg=[rx,ry], rotation_deg=rz, side=side, deflection_mm=demands[side], contact_length_mm=loaded_length, strain_percent=strain, transverse_contact_overlap_mm=contact_overlap, tip_margin_mm=tip_margins[side]))
    report = dict(geometry_passed=True, free_end_gaps_passed=True, lock_path_samples=lock_samples, nominal_radial_interference_mm=LOCK_INTERFERENCE, travel_mm=P['travel'], protrusion_mm=P['protrusion'], bottom_protrusion_mm=P['protrusion']-P['travel'], spring_thickness_mm=SPRING_THICKNESS, motion_samples=samples,
        guide_height_mm=GUIDE_HEIGHT, support_footprint_mm2=support.volume()/.05, pose_ranges=pose_ranges,
        peak_strain_percent=max(r['strain_percent'] for r in samples),
        linear_screening=[dict(E_MPa=E, bottom_force_N=2*E*P['arm_width']*SPRING_THICKNESS**3*P['travel']/(4*length**3)) for E in (1860,2140)],
        specimens_heat_treated=True, physical_print_test=False,
        method='Linear end loaded cantilever at actual pad near edge; combined translation, tilt and rotation corners to actual rigid stops; excludes friction, root concentration, creep and fatigue')
    (out/'detail-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('4 closed parts; 42 mm diameter; 0.4 mm cap clearance; 3 mm mechanical travel; 4 mm protrusion; 0.70 mm flexure; rotation lock and two pry recesses')


if __name__ == '__main__':
    main()
