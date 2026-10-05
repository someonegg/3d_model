"""Exported-mesh checks and conservative beam screening; no fatigue claim."""
from collections import OrderedDict
from time import perf_counter
import itertools
import json
import os
from pathlib import Path
import numpy as np
import manifold3d as mf
import trimesh
from assembly import verify_assembly
from geometry import P
MODULI = (1860.0, 2140.0)

def solid(mesh):
    return mf.Manifold(mf.Mesh(np.asarray(mesh.vertices, dtype=np.float32), np.asarray(mesh.faces, dtype=np.uint32)))

def overlap(a, b):
    # Disjoint axis-aligned bounds prove zero overlap; all other cases still
    # use the exact mesh boolean, including touching bounds.
    if a.is_empty() or b.is_empty():
        return 0.0
    aa, bb = a.bounding_box(), b.bounding_box()
    if any(aa[i + 3] < bb[i] or bb[i + 3] < aa[i] for i in range(3)):
        return 0.0
    return max(0.0, (a ^ b).volume())

def clear(a, b, label):
    amount = overlap(a, b)
    assert amount < 0.003, f'{label}: {amount:.5f} mm3'

def elastic_mesh(mesh):
    # Refine by physical edge length; uniform subdivision wastes most faces
    # on already tiny frame fillets, without improving the long spring edges.
    raw = solid(mesh).refine_to_length(.6).to_mesh()
    return trimesh.Trimesh(np.asarray(raw.vert_properties)[:, :3],
                           np.asarray(raw.tri_verts), process=True)

class MotionProfile:
    """Exclusive stage timings; kept outside the deterministic geometry report."""
    def __init__(self):
        self.seconds = {}
        self.calls = {}

    def add(self, stage, elapsed):
        self.seconds[stage] = self.seconds.get(stage, 0.) + elapsed
        self.calls[stage] = self.calls.get(stage, 0) + 1

    def call(self, stage, function, *args):
        started = perf_counter()
        try:
            return function(*args)
        finally:
            self.add(stage, perf_counter() - started)


class ElasticStateCache:
    """Per-check LRU: exact deformation and placement, fixed obstacles only."""
    def __init__(self, mesh, solids, profile, capacity=128):
        if capacity < 0:
            raise ValueError('cache capacity must be nonnegative')
        self.mesh, self.solids, self.profile = mesh, solids, profile
        self.capacity = capacity
        self.entries = OrderedDict()
        self.hits = self.misses = self.peak_entries = 0

    def get(self, returns, clicks, sinks, fx, fy, label):
        # Do not round: even a tiny change near contact requires a new check.
        key = tuple(values[side] for values in (returns, clicks, sinks)
                    for side in (-1, 1)) + (fx, fy)
        if key in self.entries:
            self.hits += 1
            self.entries.move_to_end(key)
            return self.entries[key]
        self.misses += 1
        bent = deformed(self.mesh, returns, clicks, sinks, self.profile).translate((fx, fy, 0))
        for fixed in ('shell', 'base'):
            self.profile.call('elastic_fixed_collision', clear, bent, self.solids[fixed], f'elastic/{fixed}/{label}')
        # Cache only after all checks succeed; moving-plunger checks never live here.
        if self.capacity:
            self.entries[key] = bent
            if len(self.entries) > self.capacity:
                self.entries.popitem(last=False)
            self.peak_entries = max(self.peak_entries, len(self.entries))
        return bent

    def info(self):
        return dict(capacity=self.capacity, hits=self.hits, misses=self.misses,
                    peak_entries=self.peak_entries,
                    hit_rate=self.hits / (self.hits + self.misses) if self.hits + self.misses else 0.)


def deformed(mesh, returns, clicks, sinks=None, profile=None):
    started = perf_counter()
    q = mesh.copy()
    v = q.vertices.copy()
    for side in (-1, 1):
        x = side * v[:, 0]
        y = side * v[:, 1]
        mask = (x > 2.49) & (x < 7.51) & (y > -17) & (y < 14.01)
        t = np.clip((y + 17) / P['return_contact_length'], 0, 1)
        shape = t * t * (3 - t) / 2
        v[mask, 2] -= returns[side] * shape[mask]
    for side in (-1, 1):
        x = side * v[:, 0]
        y = v[:, 1]
        mask = (x > P['click_x']-1.81) & (x < P['click_x']+1.41) & (y > -15) & (y < 17.01)
        t = np.clip((y + 15) / P['click_length'], 0, 1)
        shape = t * t * (3 - t) / 2
        shape[y >= 10.8] = 1
        v[mask, 0] += side * clicks[side] * shape[mask]
        if sinks is not None:
            v[mask, 2] -= sinks[side] * shape[mask]
    q.vertices = v
    if profile is not None:
        profile.add('vertex_deformation', perf_counter() - started)
    started = perf_counter()
    result = solid(q)
    assert result.status() == mf.Error.NoError, 'invalid deformed mesh'
    if profile is not None:
        profile.add('solid_rebuild', perf_counter() - started)
    return result

def check_supports(solids):
    """Measure final mesh coverage at the full lateral and locating envelope."""
    checks = []
    for side in (-1, 1):
        shoe = solids['cartridge'] ^ mf.Manifold.cube((3.4, 6.2, 3.2), center=True).translate((side*P['click_x'], 13.9, 7.8))
        for fx, fy in itertools.product((-.1, 0, .1), repeat=2):
            for travel in (0, .5):
                shifted = shoe.translate((side*max(travel, -side*fx)+fx, fy, 0))
                footprint = shifted.project().extrude(.02).translate((0, 0, 5.98))
                assert (footprint-solids['base']).volume() < .0001, 'unsupported free end'
                clear(shifted, solids['base'], 'nominal free end gap')
                # Downward sweep reaches the actual shelf after .20 mm.
                clear(shifted.translate((0,0,-.199)), solids['base'], 'premature support')
                assert overlap(shifted.translate((0,0,-.21)), solids['base']) > .01
                edge = side*shifted.bounding_box()[3 if side == 1 else 0]
                clearance = P['window_edge']-edge
                assert clearance >= .6-1e-5
                checks.append(dict(side=side, offset_xy_mm=[fx,fy], lateral_mm=travel, clearance_mm=clearance))
    for side in (-1, 1):
        for y in np.arange(-17., 17.01, .5):
            wall = mf.Manifold.cube((P['side_wall']-.02, .48, 3.18), center=True).translate((side*(P['frame_half']+P['window_edge'])/2,float(y),7.8))
            # Preserve the locating notch and post clearance in the outer edge.
            wall -= mf.Manifold.cube((2.5,8.5,4),center=True).translate((side*P['snap_x'],-11,7.8))
            if side == -1:
                wall -= mf.Manifold.cube((2.2,6.2,4),center=True).translate((-19.8,0,7.8))
            assert (wall-solids['cartridge']).volume() < .0001, 'discontinuous side frame'
            gap = mf.Manifold.cube((.02, .48, .1), center=True).translate((side*(P['window_edge']-.02),float(y),7.8))
            clear(gap, solids['cartridge'], 'stepped inner frame')
    # Mirror only the modified shoe/shelf region: cartridge locating keys differ.
    region = mf.Manifold()
    for side in (-1,1):
        region += mf.Manifold.cube((3.8, 7.6, 4), center=True).translate((side*P['shelf_x'],13.9,5))
    local = solids['base'] ^ region
    assert (local-local.mirror((1,0,0))).volume() < .003
    return dict(samples=len(checks), maximum_sink_mm=.20, minimum_lateral_clearance_mm=min(r['clearance_mm'] for r in checks), remaining_frame_wall_mm=P['side_wall'], checks=checks)


def check_snaps(solids):
    """Measure full insertion/extraction; relief is a required displacement,
    not an elastic solution. The solid end walls have no free beam boundary."""
    rows = []
    allowed = mf.Manifold()
    relieved = solids['shell']
    swept_walls = mf.Manifold()
    for side in (-1,1):
        region = mf.Manifold.cube((2.5,8.4,12.5),center=True).translate((side*P['snap_x'],-11,8.55))
        allowed += region
        swept_walls += region ^ solids['shell']
        relieved -= region
        # Both the 1.20 mm outer X wall and the 0.40 mm blind roof remain.
        probe = mf.Manifold.cube((1.19,7,.2),center=True).translate((side*21.9,-11,8))
        assert (probe-solids['shell']).volume() < .003
        roof = mf.Manifold.cube((1.1,8.7,.1),center=True).translate((side*20.65,-11,14.9))
        assert (roof-solids['shell']).volume() < .003
    for direction, offsets in [('insert',np.linspace(14.5,0,146)),('extract',np.linspace(0,14.5,146))]:
        for dz in offsets:
            shell = solids['shell'].translate((0,0,float(dz)))
            contact = shell ^ solids['base']
            assert (contact-allowed.translate((0,0,float(dz)))).volume() < .003
            clear(relieved.translate((0,0,float(dz))),solids['base'],'snap required relief envelope')
            for fixed in ('cartridge','plunger'):
                clear(shell,solids[fixed],f'snap {direction}/{fixed}/{dz}')
            # Evaluate section-to-section displacement, including both flanks.
            demand = 0.
            contact_z = []
            for z in np.linspace(P['snap_start'],P['snap_top'],201):
                local_z = z-dz
                if not 2.3 <= local_z <= P['snap_blind_top']:
                    continue
                post_half = P['snap_stem_half'] + (P['snap_head_half']-P['snap_stem_half'])*max(0,1-abs(z-P['snap_peak']))
                slot_half = P['snap_slot_half'] + (P['snap_pocket_half']-P['snap_slot_half'])*np.clip((local_z-P['snap_transition_bottom'])/(P['snap_transition_top']-P['snap_transition_bottom']),0,1)
                if local_z<2.6:
                    slot_half += .2*np.clip((2.6-local_z)/.3,0,1)
                d=max(0.,post_half-slot_half)
                demand=max(demand,d)
                if d>1e-6:
                    contact_z.append(float(local_z))
            rows.append(dict(direction=direction,offset_mm=float(dz),overlap_mm3=max(0.,contact.volume()),required_wall_displacement_mm=float(demand),contact_z_shell_mm=[min(contact_z),max(contact_z)] if contact_z else []))
    clear(solids['shell'],solids['base'],'seated snap')
    assert max(r['required_wall_displacement_mm'] for r in rows) <= .20+1e-6
    for fx,fy in itertools.product((-.1,.1),repeat=2):
        clear(swept_walls,solids['cartridge'].translate((fx,fy,0)),'snap wall relief/frame')
    assert overlap(solids['base'].translate((0,0,.05)),solids['shell']) > .5
    # The contact surfaces terminate in continuous end walls, connected both to
    # the side panel and roof. Applying a free-cantilever formula to the 12 mm
    # post length would incorrectly assign flexibility to the slot walls.
    return dict(samples=rows,maximum_required_wall_displacement_mm=max(r['required_wall_displacement_mm'] for r in rows),
                outer_slot_wall_mm=1.2,blind_roof_mm=.4,hard_seat=True,seated_clear=True,
                elasticity_screening=dict(status='unresolved',
                    reason='Continuous slot end walls are constrained by roof and side panel; no isolated bending length. Required .20 mm Y displacement needs a constrained solid/contact solve or physical insertion measurement.',
                    shell_print_direction='roof on bed; assembly +Z points toward bed',
                    post_print_direction='base on bed; post axis along build Z',
                    layer_loading='Post root bends across layers; slot opening combines in-plane strain and interlayer shear. Isotropic beam moduli do not validate this joint.'),
                elastic_insertion_verified=False,retention_force_verified=False,disassembly_life_verified=False)


def check_motion(solids, meshes, *, profile=None, cache_size=128):
    """Centre, axial/diagonal clearance limits and both tilt/yaw signs, down and up."""
    started = perf_counter()
    timings = MotionProfile()
    flexible = timings.call('mesh_refinement', elastic_mesh, meshes['cartridge'])
    states = ElasticStateCache(flexible, solids, timings, cache_size)
    samples = []
    # These cuts are independent of stroke, pose, locating offset and sink.
    cams = {side: solids['plunger'] ^ mf.Manifold.cube((3, 4, 3), center=True).translate(
        (side * (14.5-P['click_shift']), 13, 11.5)) for side in (-1, 1)}
    # A true offset limits the displacement vector to 0.20 mm at round corners.
    # (+0.20,+0.20) is outside that envelope, rather than a reachable pose.
    diagonal = P['guide_clearance'] / np.sqrt(2)
    poses = [(0, 0, 0, 0, 0)] + [(x, y, 0, 0, 0) for x in (-diagonal, diagonal) for y in (-diagonal, diagonal)]
    poses += [(x, y, 0, 0, 0) for x,y in ((P['guide_clearance'],0),(-P['guide_clearance'],0),(0,P['guide_clearance']),(0,-P['guide_clearance']))]
    poses += [(0, 0, rx, ry, rz) for rx in (-0.25, 0.25) for ry in (-0.25, 0.25) for rz in (-0.1, 0.1)]
    poses += [(.1*np.sign(ry), .1*np.sign(rx), rx, ry, rz) for rx in (-.25,.25) for ry in (-.25,.25) for rz in (-.1,.1)]
    strokes = [("press", v) for v in np.linspace(0, P['travel'], 13)] + [("return", v) for v in np.linspace(P['travel'], 0, 13)]
    for direction, stroke in strokes:
        if direction == 'press':
            print(f'Motion geometry: stroke {stroke:.2f} mm', flush=True)
        if direction == 'return':
            # This frictionless model is memoryless: the same pose has the
            # same deformed mesh in either direction. Reuse its solved state,
            # while retaining explicit return coverage in the report.
            samples.extend(dict(row, direction='return') for row in list(samples)
                           if row['direction']=='press' and abs(row['stroke_mm']-stroke)<1e-9)
            continue
        solved_poses = {}
        for dx, dy, rx, ry, rz in poses:
            # Roof and rest shoulder straighten the key at both endpoints.
            # Prescribe a continuous tilt path, then reject every collision.
            tilt_scale = min(1.0, float(stroke)/0.25, (P['travel']-float(stroke))/0.25)
            rx, ry, rz = rx*tilt_scale, ry*tilt_scale, rz*tilt_scale
            # Exact keys only: no rounded poses or merged near contacts.
            pose_key = (dx, dy, rx, ry, rz)
            if pose_key in solved_poses:
                samples.extend(dict(row) for row in solved_poses[pose_key])
                continue
            first_sample = len(samples)
            matrix = trimesh.transformations.euler_matrix(*np.radians([rx, ry, rz]))
            posed = {}
            for name in ('plunger', 'keycap'):
                posed[name] = solids[name].translate((0, 0, -14.5)).rotate((rx, ry, rz)).translate((dx, dy, 14.5 - float(stroke)))
            for part in posed.values():
                for fixed in ('shell','base'):
                    timings.call('rigid_collision', clear, part, solids[fixed], f'full path rigid/{fixed}/{stroke}/{dx}/{dy}/{rx}/{ry}')
            posed_cams = {side: cam.translate((0, 0, -14.5)).rotate((rx, ry, rz)).translate(
                (dx, dy, 14.5 - float(stroke))) for side, cam in cams.items()}
            normal = matrix[:3, 2]
            origin = matrix[:3, :3] @ np.array([0, 0, 10.25 - 14.5]) + [dx, dy, 14.5 - stroke]
            for fx, fy in [(0, 0)] + [(x, y) for x in (-0.1, 0.1) for y in (-0.1, 0.1)]:
                contact_started = perf_counter()
                clicks = {}
                cam_demand = {}
                widths = []
                for side in (-1, 1):
                    window = posed['plunger'] ^ mf.Manifold.cube((4, 3.8, P['contact_height']), center=True).translate((side * (15-P['click_shift']) + fx, 13 + fy, P['contact_bottom']+P['contact_height']/2))
                    extent = side * window.bounding_box()[3 if side == 1 else 0] if not window.is_empty() else 0
                    cam_demand[side] = max(0.0, extent - (P['shoe_inner'] + side * fx))
                    clicks[side] = max(cam_demand[side], -side * fx, 0)
                    assert clicks[side] <= 0.5 + 1e-05, f'excess click travel {clicks}'
                    bounds = posed_cams[side].bounding_box()
                    width = min(bounds[4], 14.9 + fy) - max(bounds[1], 11.1 + fy)
                    assert width > 3.0, f'contact loses transverse overlap {width}'
                    widths.append(width)
                returns = {side: max(0.0, max((10.4 - (origin[2] - (normal[0] * (side * 5 + fx + px - origin[0]) + normal[1] * (side * 13 + fy + py - origin[1])) / normal[2]) for px in (-2.5, 2.5) for py in (-1, 1)))) for side in (-1, 1)}
                # Sample the entire shelf gap independently of lateral travel.
                # Recompute cam demand at each height; sinking can change facets.
                timings.add('contact_geometry', perf_counter() - contact_started)
                sink_checks = []
                for sink in np.linspace(0., P['support_gap'], 5):
                    sinks = {side: float(sink) for side in (-1, 1)}
                    contact_started = perf_counter()
                    demand = {}
                    for side in (-1, 1):
                        window = posed['plunger'] ^ mf.Manifold.cube((4, 3.8, P['contact_height']), center=True).translate((side*(15-P['click_shift'])+fx, 13+fy, P['contact_bottom']+P['contact_height']/2-sink))
                        extent = side*window.bounding_box()[3 if side == 1 else 0] if not window.is_empty() else 0
                        cam_push = max(0., extent-(P['shoe_inner']+side*fx))
                        if abs(stroke-P['travel']) < 1e-9:
                            assert cam_push < 1e-5, 'cam remains loaded at bottom with shelf sink'
                        demand[side] = max(cam_push, -side*fx)
                        assert demand[side] <= .5+1e-5
                    timings.add('contact_geometry', perf_counter() - contact_started)
                    label = f'{stroke}/{dx}/{dy}/{rx}/{ry}/{fx}/{fy}/{sink}'
                    bent = states.get(returns, {side: value + .003 if value else 0 for side, value in demand.items()}, sinks, fx, fy, label)
                    timings.call('elastic_moving_collision', clear, bent, posed['plunger'], f'elastic/plunger/{label}')
                    sink_checks.append(dict(sink_mm=float(sink), click_displacement_mm=max(demand.values())))
                samples.append(dict(direction=direction, stroke_mm=float(stroke), offset_xy_mm=[dx, dy], frame_offset_xy_mm=[fx, fy], tilt_xy_deg=[rx, ry], yaw_deg=rz, click_displacement_mm=max(r['click_displacement_mm'] for r in sink_checks), click_sink_mm=max(sinks.values()), sink_checks=sink_checks, cam_demand_mm=max(cam_demand.values()), return_deflection_mm=max(returns.values()), contact_overlap_mm=min(widths)))
            solved_poses[pose_key] = samples[first_sample:]
    assert len(samples) == 26 * len(poses) * 5
    assert len(samples) > 13 and any((row['tilt_xy_deg'] != [0, 0] for row in samples))
    assert any((row['offset_xy_mm'] != [0, 0] for row in samples))
    assert all((row['cam_demand_mm'] == 0 for row in samples if row['stroke_mm'] == 3))
    for stroke in np.linspace(0, P['travel'], 13):
        covered = {tuple(row['offset_xy_mm']) for row in samples if row['stroke_mm'] == stroke}
        assert all((dx, dy) in covered for dx, dy, rx, ry, rz in poses[:9]), 'corner translation cannot complete full travel'
    measurements = dict(total_seconds=perf_counter() - started,
                        stage_seconds=timings.seconds, stage_calls=timings.calls,
                        elastic_cache=states.info())
    measurements['other_seconds'] = measurements['total_seconds'] - sum(timings.seconds.values())
    if profile is not None:
        profile.update(measurements)
    if os.environ.get('MOTION_PROFILE') == '1':
        print('Motion profile: ' + json.dumps(measurements, sort_keys=True), flush=True)
    return dict(required_poses_per_stroke=len(poses), verified_samples=len(samples), method='Approximate warped final STL, end-loaded beam shape; combined offset/tilt and locating extremes; vertical click sink sampled every .05 mm across the full .20 mm shelf gap; endpoint stops straighten tilt; no friction or nonlinear contact solve', samples=samples, peak_click_displacement_mm=max((r['click_displacement_mm'] for r in samples)), peak_return_deflection_mm=max((r['return_deflection_mm'] for r in samples)), minimum_contact_overlap_mm=min((r['contact_overlap_mm'] for r in samples)))

def load_screening(meshes, solids, motion, E):
    """Frictionless normal forces measured from the exported cam facets.
Rigid full-travel bearing area measured from final meshes."""
    G = E / (2 * (1 + 0.35))
    L = P['click_length']
    w = P['click_width']
    t = P['click_thickness']
    mesh = meshes['plunger']
    points = mesh.triangles_center
    normals = mesh.face_normals
    mask = (np.abs(points[:, 0]) > P['cam_entry']) & (points[:, 1] > 11) & (points[:, 1] < 15) & (points[:, 2] > 10.3) & (points[:, 2] < 11.7) & (np.abs(normals[:, 0]) > 0.1)
    ratios = normals[mask, 2] / np.abs(normals[mask, 0])
    assert len(ratios) and min(ratios) < 0 and (max(ratios) > 0)
    kx = E * t * w ** 3 / (4 * L ** 3)
    kz = E * w * t ** 3 / (4 * L ** 3)
    force = kx * motion['peak_click_displacement_mm']
    fz = force * max(abs(ratios))
    dz = fz / kz
    J = t * w ** 3 * (1 / 3 - 0.21 * (w / t) * (1 - (w / t) ** 4 / 12))
    torque = fz * 1.8
    twist = torque * L / (G * J)
    lip_delta = fz * 1.2 ** 3 / (3 * E * (3.8 * P['contact_height'] ** 3 / 12))
    free_sink = dz + 1.8 * twist + lip_delta
    vertical_compliance = free_sink / fz if fz else 0.
    support_reaction = max(0., fz-P['support_gap']/vertical_compliance) if vertical_compliance else 0.
    supported_sink = min(free_sink, P['support_gap'])
    assert supported_sink <= .20 + 1e-8
    assert free_sink < 0.25, 'loaded contact loses vertical margin'
    contact = solids['keycap'].translate((0, 0, -3.01)) ^ solids['shell']
    area = contact.volume() / 0.01
    assert area > 180, 'insufficient rigid bottoming area'
    roof_probe = solids['shell'] ^ mf.Manifold.cube((1, 1, 4), center=True).translate((11, 0, 17))
    roof_bounds = np.array(roof_probe.bounding_box())
    roof_t = roof_bounds[5] - roof_bounds[2]
    np.testing.assert_allclose(roof_t, P['roof_thickness'], atol=1e-5)
    # Conservative cantilever strip: all load at inner opening edge; the
    # perimeter plate and guide sleeve add stiffness omitted from this bound.
    span, strip_width = 20 - (7 + P['guide_clearance']), 20.
    roof_cases = []
    for label, pad_force in (('centre-20N', 10.), ('corner-20N', 20.)):
        delta = pad_force * span**3 / (3 * E * (strip_width * roof_t**3 / 12))
        stress = 6 * pad_force * span / (strip_width * roof_t**2)
        loaded_return_strain = 100 * 1.5 * (motion['peak_return_deflection_mm'] + delta) / P['return_contact_length']**2
        assert stress / E < .006 and loaded_return_strain <= .6
        roof_cases.append(dict(case=label,roof_deflection_bound_mm=float(delta),roof_bending_stress_MPa=float(stress),return_strain_with_stop_deflection_percent=float(loaded_return_strain)))
    shoe = solids['cartridge'] ^ mf.Manifold.cube((3.4,6.2,3.2),center=True).translate((P['click_x'],13.9,7.8))
    bearing_area = shoe.project().area()
    return dict(support_projected_area_mm2=bearing_area, support_mean_pressure_MPa=support_reaction/bearing_area, method='Frictionless exported cam normals; linear lateral/vertical beams and rectangular-section torsion, no friction/impact/creep/fatigue model', E_MPa=E, peak_lateral_force_N=force, vertical_to_lateral_normal_ratio=float(max(abs(ratios))), vertical_force_N=float(fz), vertical_deflection_mm=float(dz), free_tip_sink_bound_mm=float(free_sink), supported_tip_sink_bound_mm=float(supported_sink), support_reaction_N=float(support_reaction), support_model='Unilateral rigid shelf at .20 mm; linear vertical beam, torsion bound; no nonlinear contact or impact solve', torsion_angle_deg=float(np.degrees(twist)), contact_tip_deflection_mm=float(lip_delta), rigid_stop_bearing_area_mm2=area, illustrative_20N_mean_compression_MPa=20 / area, roof_thickness_mm=float(roof_t),roof_linear_load_screening=roof_cases,actual_force_verified=False)

def main():
    """Confirm actual compliant cross-sections and snap displacement requirements."""
    OUT = Path(os.environ['MODEL_OUTPUT_DIR'])
    data = json.loads((OUT / 'assembly.json').read_text())
    meshes = {}
    solids = {}
    for row in data['parts']:
        m = trimesh.load(OUT / row['file'], force='mesh')
        assert m.is_watertight and m.is_winding_consistent and (m.volume > 0) and (len(m.split()) == 1), row['id']
        assert abs(m.bounds[0, 2]) < 1e-05
        m.apply_transform(np.linalg.inv(row['assembly_to_print']))
        meshes[row['id']] = m
        solids[row['id']] = solid(m)
    assert len(solids) == 5
    plate = trimesh.load(OUT / 'all-parts.stl', force='mesh')
    assert len(plate.split()) == 5
    np.testing.assert_allclose(meshes['keycap'].extents, [24, 24, 4], atol=1e-05)
    for a, b in itertools.combinations(solids, 2):
        if {a, b} in ({'cartridge', 'plunger'}, {'keycap', 'plunger'}, {'shell', 'base'}):
            continue
        clear(solids[a], solids[b], f'assembled {a}/{b}')
    for offset in np.linspace(0, 40, 81):
        clear(solids['cartridge'].translate((0, 0, float(offset))), solids['base'], f'cartridge drop {offset}')
        for fixed in ('plunger', 'cartridge'):
            clear(solids['shell'].translate((0, 0, float(offset))), solids[fixed], f'shell drop/{fixed}/{offset}')
    for stroke in np.linspace(0, P['travel'], 31):
        for moving in ('plunger', 'keycap'):
            for fixed in ('shell', 'base'):
                clear(solids[moving].translate((0, 0, -float(stroke))), solids[fixed], f'{moving}/{fixed}/{stroke}')
    assert overlap(solids['keycap'].translate((0, 0, -3.15)), solids['shell']) > 1
    for name, xyz, size, expected in (('cartridge', (5, 0, 7), (1, 2, 4), (1, 2, 1)), ('cartridge', (P['click_x'], 0, 8), (3, 1, 5), (1.6, 1, 3.2))):
        probe = solids[name] ^ mf.Manifold.cube(size, center=True).translate(xyz)
        bounds = np.array(probe.bounding_box())
        np.testing.assert_allclose(bounds[3:] - bounds[:3], expected, atol=1e-05)
    screw_checks = []
    for x,y in P['screw_centers']:
        # Nominal screw envelope: recessed 90-degree head and full major diameter.
        head = mf.Manifold.cylinder(1.1,2.2,1.1,64).translate((x,y,.2))
        shaft = mf.Manifold.cylinder(6.9,1.1,1.1,64).translate((x,y,1.3))
        clear(head+shaft, solids['base'], 'screw/base clearance')
        for fixed in ('cartridge','plunger','keycap'):
            clear(head+shaft,solids[fixed],f'screw/{fixed}')
        pilot = mf.Manifold.cylinder(9.49,.84,.84,64).translate((x,y,2.4))
        clear(pilot,solids['shell'],'blind pilot depth')
        blind_end = mf.Manifold.cylinder(.1,.84,.84,64).translate((x,y,11.91))
        assert overlap(blind_end,solids['shell']) > .2, 'pilot must be blind'
        radial_wall = (mf.Manifold.cylinder(5.8,2.19,2.19,64)-mf.Manifold.cylinder(5.8,1.11,1.11,64)).translate((x,y,2.4))
        assert (radial_wall-solids['shell']).volume() < .003, 'boss wall below 1.1 mm'
        floor = (mf.Manifold.cylinder(1.09,2.19,2.19,64)-mf.Manifold.cylinder(1.09,1.21,1.21,64)).translate((x,y,1.31))
        assert (floor-solids['base']).volume() < .003, 'thin countersink floor'
        window = mf.Manifold.cube((5,5,1),center=True).translate((x,y,2.4))
        bearing = solids['shell'] ^ solids['base'].translate((0,0,.05)) ^ window
        assert bearing.volume() > .5, 'rigid floor must bear tightening load'
        screw_checks.append(dict(center_xy_mm=[x,y],spec='ST2.2 x 8 mm, 90 degree countersunk plastic screw, head <= 4.4 mm',head_recess_mm=P['head_recess'],engagement_mm=P['screw_length']+P['head_recess']-2.4,pilot_depth_mm=9.5,minimum_radial_wall_mm=1.1,remaining_base_thickness_mm=1.1,roof_clearance_mm=7.4))
    for name in ('shell','base'):
        np.testing.assert_allclose(meshes[name].bounds[:,:2],[[-22.5,-22.5],[22.5,22.5]],atol=1e-5)
    cap_contact = overlap(solids['keycap'], solids['plunger'])
    assert 0 < cap_contact < 1, 'invalid keycap wedge fit'
    for offset in np.linspace(0, 40, 81):
        cap_insert = solids['keycap'].translate((0, 0, float(offset)))
        assert overlap(cap_insert, solids['plunger']) <= cap_contact + 0.003
        for fixed in ('shell', 'base'):
            clear(cap_insert, solids[fixed], f'keycap insertion/{fixed}/{offset}')
    for angle in (90, 180, 270):
        assert overlap(solids['cartridge'].rotate((0, 0, angle)), solids['base']) > 1
    assert overlap(solids['plunger'].translate((0, 0, 0.1)), solids['shell']) > 1
    clear(solids['plunger'].rotate((0, 0, 180)), solids['shell'], 'symmetric unkeyed guide')
    supports = check_supports(solids)
    snaps = check_snaps(solids)
    motion = check_motion(solids, meshes)
    preloaded = deformed(elastic_mesh(meshes['cartridge']), {-1: 0.15, 1: 0.15}, {-1: 0, 1: 0})
    for offset in np.linspace(0, 40, 81):
        insert = solids['plunger'].translate((0, 0, float(offset)))
        clear(insert, preloaded, f'plunger insertion/{offset}')
        clear(insert, solids['base'], f'plunger/base insertion/{offset}')
    loads = [load_screening(meshes, solids, motion, E) for E in MODULI]
    E = MODULI[0]
    strain = 100 * 1.5 * P['return_thickness'] * motion['peak_return_deflection_mm'] / P['return_contact_length'] ** 2
    assert strain <= 0.6
    click_k = E * P['click_thickness'] * P['click_width'] ** 3 / (4 * P['click_length'] ** 3)
    force = click_k * P['click_deflection']
    report = dict(passed=False, geometry_screening_passed=True, acceptance_status='geometry-screened-snap-elasticity-unresolved', parts=5, travel_mm=3, screw_checks=screw_checks, free_end_support=supports, snap_fit=snaps, material=dict(name="PLA Tough+", moduli_MPa=MODULI, specimens_heat_treated=True, default_annealing=False), geometry=dict(watertight=True, connected=True, on_bed=True, rigid_travel_samples=31, vertical_insertion_samples=81), elastic_motion=motion, load_screening=loads, assembly_animation=verify_assembly(OUT / 'assembly.glb', meshes), spring_screening=dict(method='Linear end-loaded cantilever; nominal sections, E=1860 MPa; excludes friction, impact, creep and fatigue', return_peak_strain_percent=strain, return_contact_length_mm=P['return_contact_length'], return_force_at_bottom_N=2 * E * P['return_width'] * P['return_thickness'] ** 3 * motion['peak_return_deflection_mm'] / (4 * P['return_contact_length'] ** 3), click_lateral_strain_percent=100 * 1.5 * P['click_width'] * P['click_deflection'] / P['click_length'] ** 2, click_force_N=force, click_vertical_stiffness_N_per_mm=E * P['click_width'] * P['click_thickness'] ** 3 / (4 * P['click_length'] ** 3), physical_loads_verified=False), physical_print_test=False, force_and_sound_verified=False, elastic_geometric_screening_passed=True, actual_elastic_motion_verified=False, printable_validation_complete=False)
    (OUT / 'detail-validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print('Five connected parts; rigid travel, seats and animation checked; approximate elastic motion checked')
if __name__ == '__main__':
    main()
