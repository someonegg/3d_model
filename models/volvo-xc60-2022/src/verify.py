"""Acceptance of final exported meshes in their recovered assembly coordinates."""
from pathlib import Path
import json
import hashlib
import os
import sys
import numpy as np
import trimesh
from geometry import P, AXLES, mesh, solid, union, cyl, open_door

OUT = Path(os.environ.get('MODEL_OUTPUT_DIR', Path(__file__).resolve().parents[1]))


def load_part(row):
    obj = trimesh.load(OUT/'parts'/f"{row['name']}.stl", process=False)
    vertices, inverse = np.unique(obj.vertices, axis=0, return_inverse=True)
    obj = trimesh.Trimesh(vertices, inverse[obj.faces], process=False)
    assert obj.is_watertight and obj.is_winding_consistent, row['name']
    assert np.all(obj.area_faces > 1e-12), (row['name'], 'degenerate face')
    components = obj.split(only_watertight=False, repair=False)
    assert len(components) == 1 and components[0].volume > 0, (row['name'], len(components))
    assert abs(obj.bounds[0, 2]) < 2e-4, (row['name'], 'not on print bed')
    assert np.all(obj.extents <= [240, 240, 240]), row['name']
    obj.apply_transform(np.linalg.inv(row['assembly_to_print']))
    np.testing.assert_allclose(obj.bounds, row['bounds'], atol=.008)
    return solid(obj)


def ray_hits(obj, origin, direction):
    # Independent Moller-Trumbore intersections on the exported surface.
    tri=mesh(obj).triangles
    e1=tri[:,1]-tri[:,0]; e2=tri[:,2]-tri[:,0]
    cross=np.cross(direction,e2); det=(e1*cross).sum(axis=1)
    valid=np.abs(det)>1e-8
    inv=np.divide(1,det,out=np.zeros_like(det),where=valid)
    delta=np.asarray(origin)-tri[:,0]
    u=(delta*cross).sum(axis=1)*inv; q=np.cross(delta,e1)
    v=(q*direction).sum(axis=1)*inv; distance=(e2*q).sum(axis=1)*inv
    selected=valid&(u>=-1e-6)&(v>=-1e-6)&(u+v<=1.000001)&(distance>=0)
    return np.unique(np.round(distance[selected],4))


def main():
    meta = json.loads((OUT/'assembly.json').read_text())
    assert meta['parameters'] == P, 'stale assembly parameters'
    rows = meta['parts']
    parts = {row['name']:load_part(row) for row in rows}
    assert len(parts) == 52
    body_bounds = np.asarray(parts['body'].bounding_box()).reshape(2, 3)
    assert abs(body_bounds[1,0]-body_bounds[0,0]-4708/24) < .02
    assert abs(AXLES[1]-AXLES[0]-2865/24) < 1e-8
    hood=ray_hits(parts['body'],(-70,0,0),(0,0,1))
    roof=ray_hits(parts['body'],(20,25,0),(0,0,1))
    sides=ray_hits(parts['body'],(50,-60,35),(0,1,0))
    assert len(hood)==2 and len(roof)==2 and len(sides)==4
    walls={'hood':float(hood[1]-hood[0]),'roof':float(roof[1]-roof[0]),
           'left_side':float(sides[3]-sides[2]),'right_side':float(sides[1]-sides[0])}
    assert min(walls.values())>=1.45, walls
    # Every assembled pair is disjoint, except the explicitly elastic door clips.
    overlaps = []
    items = list(parts.items())
    for i, (name, a) in enumerate(items):
        for other, b in items[i+1:]:
            volume = (a^b).volume()
            elastic = {name,other} in [ {'door-card-left','door-clip-left'}, {'door-card-right','door-clip-right'} ]
            if elastic:
                assert .05 < volume < 2, (name,other,volume)
                overlaps.append({'parts':[name,other], 'intentional_friction_mm3':round(volume,6)})
            else:
                assert volume < .025, (name,other,'assembly collision',volume)
    sweeps = []
    hx, hy = P['hinge_xy_mm']
    for side, suffix in [(1,'left'),(-1,'right')]:
        moving = union(*(parts[row['name']] for row in rows if row['group']=='door-'+suffix))
        stationary = union(*(parts[row['name']] for row in rows
                             if not row['group'].startswith('door-') and not row['name'].startswith('door-clip-')))
        maximum = 0
        for angle in np.arange(0, P['door_open_deg']+.01, 2):
            collision = (open_door(moving,side,float(angle))^stationary).volume()
            maximum = max(maximum,collision)
            assert collision < .025, (suffix,angle,collision)
        # Between-pose fender envelope: hull of consecutive poses enlarged by
        # 0.01 mm (larger than 2 degree sagitta at this door's radius).
        # Cylindrical hinge region has intentional near contacts and is checked
        # separately by the knuckle clearance, pin path and stop tests below.
        fixed_fender = union(parts['body'], parts['windshield']) - cyl(5.0, 25, (hx, side*hy, 37), 'z')
        max_envelope = 0
        for angle in np.arange(0, P['door_open_deg'], 2):
            points = np.concatenate([mesh(open_door(parts['door-'+suffix].hull(), side, float(t))).vertices for t in [angle,angle+2]])
            import manifold3d as m
            offsets=np.array([[x,y,z] for x in [-.01,.01] for y in [-.01,.01] for z in [-.01,.01]])
            envelope = m.Manifold.hull_points((points[:,None,:]+offsets[None,:,:]).reshape(-1,3))
            collision = (envelope^fixed_fender).volume()
            max_envelope=max(max_envelope,collision)
        assert max_envelope < .03, (suffix,'continuous fender envelope',max_envelope)
        # The 1.5 mm pin can be inserted from the bottom; stop blocks overtravel.
        pin = cyl(P['hinge_pin_mm']/2, 20, (hx,side*hy,37))
        assert (pin^union(parts['body'], parts['door-'+suffix])).volume() < .002
        overtravel = (open_door(parts['door-'+suffix],side,61)^parts['body']).volume()
        assert overtravel > .025, ('missing opening stop',suffix,overtravel)
        assert (open_door(parts['door-'+suffix],side,-1)^parts['body']).volume() > .025, ('missing closing stop',suffix)
        assert (open_door(moving,side,3)^parts['door-clip-'+suffix]).volume() < .01
        sweeps.append({'side':suffix,'degrees':[0,60], 'sample_step_deg':2,
                       'max_collision_mm3':round(maximum,6), 'fender_envelope_collision_mm3':round(max_envelope,6),
                       'stop_collision_at_61_deg_mm3':round(overtravel,6)})
    # Exported axle bores, wheel wells and screw pilot paths.
    for x in AXLES:
        shaft = cyl(1, 77, (x,0,P['wheel_radius_mm']), 'y')
        assert (shaft^parts['chassis']).volume() < .002
        for suffix in ['left','right']:
            index = 0 if x == AXLES[0] else 1
            tyre = parts[f'tyre-{index}-{suffix}']
            assert abs(mesh(tyre).extents[0] - 2*P['wheel_radius_mm']) < .02
            assert (tyre^parts['body']).volume() < .002
    for x,y in [(-82,-24),(-82,24),(84,-24),(84,24)]:
        assert (cyl(.8,5,(x,y,15.0))^parts['body']).volume() < .002
        assert (cyl(1.05,3,(x,y,11.2))^parts['chassis']).volume() < .002
    for plate in meta['plates']:
        obj=trimesh.load(OUT/plate['file'],process=True)
        assert np.all(obj.bounds[0]>=-2e-4) and np.all(obj.bounds[1]<=[248,248,240]), plate['file']
        assert len(obj.split(only_watertight=False,repair=False))==len(plate['parts']), plate['file']
    slicing=json.loads((OUT/'slicing-validation.json').read_text())
    if slicing['status']=='complete':
        expected={'fit-coupon.stl', *(r['file'] for r in meta['plates'])}
        assert {r['file'] for r in slicing['plates']}==expected
        for row in slicing['plates']:
            assert row['sha256']==hashlib.sha256((OUT/row['file']).read_bytes()).hexdigest(), 'stale slicing report'
            assert row['return_code']==0
    report={'passed':True,'print_parts':len(parts),'scale':24,'body_length_mm':round(float(np.diff(body_bounds[:,0])[0]),4),
            'wheelbase_mm':round(AXLES[1]-AXLES[0],4),'sampled_shell_mm':walls,'door_checks':sweeps,'elastic_contacts':overlaps,
            'plate_count':len(meta['plates']),'physical_print_test':False}
    (OUT/'detail-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    main()
