"""Verify exported geometry, assembly paths and approximate compliant motion."""
from pathlib import Path
import hashlib
import itertools
import json
import os
import numpy as np
import manifold3d as mf
import trimesh

OUT = Path(os.environ.get('MODEL_OUTPUT_DIR', Path(__file__).resolve().parents[1]))


def solid(mesh):
    return mf.Manifold(mf.Mesh(np.asarray(mesh.vertices, dtype=np.float32),
                              np.asarray(mesh.faces, dtype=np.uint32)))


def cube(extents, pos):
    return mf.Manifold.cube(extents, center=True).translate(pos)


def overlap(a, b):
    return max(0., (a ^ b).volume())


def require_clear(a, b, label, tolerance=2e-4):
    amount = overlap(a, b)
    assert amount <= tolerance, f'{label}: {amount:.6f} mm3 intersection'
    return amount


def bent_return(mesh, stroke):
    m=mesh.copy()
    for _ in range(3):
        m=m.subdivide()
    p=m.vertices.copy()
    for side in (-1, 1):
        x=side*p[:, 0]; y=side*p[:, 1]
        mask=(x>-11)&(x<9)&(y>1.39)&(y<3.81)
        distance=np.maximum(0, x+11)
        t=np.minimum(distance/18, 1)
        shape=t*t*(3-t)/2 + np.maximum(0, distance-18)*1.5/18
        p[mask, 2] -= (stroke+.1)*shape[mask]
    m.vertices=p
    return solid(m)


def bent_click(mesh, displacement):
    m=mesh.copy()
    for _ in range(2):
        m=m.subdivide()
    p=m.vertices.copy()
    for side in (-1, 1):
        x=side*p[:, 0]; y=p[:, 1]
        mask=(x>9.2)&(x<12)&(y>-11.5)&(y<3.51)
        mask &= ~((x<10.59)&(y>2.51))
        t=np.clip((y+11.5)/13, 0, 1)
        shape=t*t*(3-t)/2+np.maximum(0,y-1.5)*1.5/13
        p[mask, 0] += side*displacement*shape[mask]
    m.vertices=p
    return solid(m)


def main():
    assembly=json.loads((OUT/'assembly.json').read_text())
    print_meshes={}; assembled={}; solids={}
    for row in assembly['parts']:
        name=row['id']; m=trimesh.load(OUT/row['file'], force='mesh')
        assert len(m.split())==1 and m.is_watertight and m.is_winding_consistent and m.volume>0, name
        assert abs(m.bounds[0,2])<1e-5, f'{name}: not on bed'
        print_meshes[name]=m.copy()
        m.apply_transform(np.linalg.inv(row['assembly_to_print']))
        assembled[name]=m; solids[name]=solid(m)
    assert len(solids)==6
    plate=trimesh.load(OUT/'all-parts.stl', force='mesh')
    chunks=list(plate.split())
    assert len(chunks)==6
    for row in assembly['parts']:
        expected=print_meshes[row['id']].copy()
        expected.apply_translation((*row['plate_xy'],0))
        found=min(chunks, key=lambda m:np.linalg.norm(m.bounds-expected.bounds))
        np.testing.assert_allclose(found.bounds, expected.bounds, atol=1e-5)
        assert abs(found.volume-expected.volume)<.002
        chunks.remove(found)
    for a,b in itertools.combinations(list(plate.split()),2):
        gap=np.maximum(b.bounds[0,:2]-a.bounds[1,:2],a.bounds[0,:2]-b.bounds[1,:2])
        assert max(gap)>=5-1e-5
    coupon=trimesh.load(OUT/'fit-coupon.stl', force='mesh')
    assert len(coupon.split())==2
    np.testing.assert_allclose(assembled['keycap'].extents, [24,24,4], atol=1e-5)
    np.testing.assert_allclose(assembled['shell'].extents, [39,32,18], atol=1e-5)
    spring=assembled['return-spring']
    assert abs(spring.extents[2]-.8)<1e-5
    # Probe actual exported interfaces, not source parameters.
    guide=cube((18.48,8.48,4.8),(0,0,15.5))
    # Rounded guide corners are excluded from this rectangular probe.
    guide=mf.Manifold.cube((17.2,8.48,4.8),center=True).translate((0,0,15.5)) + cube((18.48,7.2,4.8),(0,0,15.5))
    guide -= mf.CrossSection([[(-1, 12), (12, -1), (12, 12)]]).extrude(20)
    require_clear(solids['shell'],guide,'guide opening')
    bore=mf.Manifold.cylinder(5.2,1.99,1.99,48).translate((-18.6,0,12.9))
    require_clear(solids['shell'],bore,'keyring bore')
    assert overlap(solids['shell'],mf.Manifold.cylinder(1,4.4,4.4,48).translate((-18.6,0,15)))>45
    for a,b in itertools.combinations(solids,2):
        if {a,b} in ({'keycap','plunger'}, {'return-spring','plunger'}):
            continue
        require_clear(solids[a],solids[b],f'assembly {a}/{b}')
    # Misoriented parts must be rejected by physical keys, not just instructions.
    assert overlap(solids['plunger'].rotate((0,0,180)),solids['shell'])>1
    for name in ('return-spring','click-spring'):
        assert overlap(solids[name].rotate((0,0,90)),solids['shell'])>.1
        assert overlap(solids[name].rotate((0,0,180)),solids['shell'])>.1
    # Keycap rib interference is deliberate, confined to the removable peg.
    peg_contact=solids['keycap'] ^ solids['plunger']
    assert .1<peg_contact.volume()<.8
    require_clear(peg_contact, cube((40,40,40),(0,0,1)), 'peg interference outside socket')
    # Sliding cover path; detents are the only permitted insertion interference.
    for offset in np.linspace(0,34,35):
        lid=solids['base'].translate((float(offset),0,0))
        rigid=lid
        for side in (-1,1):
            rigid -= cube((3,1.2,.6),(12+float(offset),side*14,2.2))
        require_clear(rigid,solids['shell'],f'cover insertion {offset}')
    samples=[]
    for stroke in np.linspace(0,3,13):
        stroke=float(stroke)
        plunger=solids['plunger'].translate((0,0,-stroke))
        cap=solids['keycap'].translate((0,0,-stroke))
        for name in ('shell','base'):
            require_clear(plunger,solids[name],f'plunger/{name} at {stroke}')
            require_clear(cap,solids[name],f'cap/{name} at {stroke}')
        # Follower occupies Z 9..9.8; use the maximum cam extent in that slab.
        cam=plunger ^ cube((5,1, .8),(10,2,9.4))
        displacement=max(0.,cam.bounding_box()[3]-9.25) if not cam.is_empty() else 0.
        clicked=bent_click(assembled['click-spring'],displacement+.015 if displacement else 0.)
        returned=bent_return(spring,stroke)
        assert clicked.status()==mf.Error.NoError and returned.status()==mf.Error.NoError
        require_clear(plunger,clicked,f'deformed click/{stroke}',.003)
        require_clear(plunger,returned,f'deformed return/{stroke}',.003)
        for fixed in ('shell','base'):
            require_clear(clicked,solids[fixed],f'click/{fixed}/{stroke}')
            require_clear(returned,solids[fixed],f'return/{fixed}/{stroke}')
        require_clear(clicked,returned,f'cartridges/{stroke}')
        samples.append(dict(stroke_mm=stroke, follower_displacement_mm=round(displacement,4)))
    assert max(r['follower_displacement_mm'] for r in samples)>.5
    assert samples[0]['follower_displacement_mm']==0 and samples[-1]['follower_displacement_mm']==0
    # Confirm both stops oppose overtravel.
    assert overlap(solids['plunger'].translate((0,0,.15)),solids['shell'])>.1
    assert overlap(solids['keycap'].translate((0,0,-3.15)),solids['shell'])>1
    report=dict(passed=True, parts=6, travel_mm=3, guide_clearance_per_side_mm=.25,
                keyring_hole_mm=4, samples=samples,
                spring_screening=dict(method='Small-deflection end-loaded cantilever; conservative effective lengths',
                    assumed_E_MPa=2500, return_effective_length_mm=18,
                    return_peak_strain_percent=round(100*1.5*.8*3.1/18**2,3),
                    return_force_at_bottom_N=round(2*2500*2.4*.8**3*3.1/(4*18**3),3),
                    click_effective_length_mm=13,
                    click_peak_strain_percent=round(100*1.5*.8*.65/13**2,3)),
                physical_print_test=False, force_and_sound_verified=False)
    slicing=json.loads((OUT/'slicing-validation.json').read_text())
    if slicing.get('status')=='complete':
        for row in slicing['plates']:
            assert hashlib.sha256((OUT/row['file']).read_bytes()).hexdigest()==row['sha256'], 'stale slicing report'
    (OUT/'detail-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('Six parts; full travel and insertion paths checked')


if __name__=='__main__':
    main()
