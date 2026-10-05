"""Seven-part, manually operated blunt-wing toy; dimensions in millimetres."""
import json
from pathlib import Path

import manifold3d as mf
import numpy as np
import trimesh

HERE = Path(__file__).resolve().parents[1]
P = json.loads((HERE / 'parameters.json').read_text())
FLOOR = P['floor_thickness']
WING_Z = FLOOR + P['axial_clearance'] / 2
CAM_Z = WING_Z + P['wing_thickness'] + P['axial_clearance'] / 2
CAM_TOP = CAM_Z + P['cam_thickness']
LID_Z = CAM_TOP + P['axial_clearance'] / 2
LID_TOP = LID_Z + P['lid_thickness']
KNOB_TOP = LID_TOP + P['knob_exposed_height']
WINGS = [f'wing-{i + 1}' for i in range(4)]


def circle(radius, x=0, y=0):
    return mf.CrossSection.circle(radius, 96).translate((x, y))


def rect(w, d, x=0, y=0, r=0):
    section = mf.CrossSection.square((w - 2*r, d - 2*r), center=True)
    if r:
        section = section.offset(r, circular_segments=32)
    return section.translate((x, y))


def box(w, d, h, x=0, y=0, z=0, r=0):
    return rect(w, d, x, y, r).extrude(h).translate((0, 0, z))


def cylinder(radius, height, x=0, y=0, z=0):
    return circle(radius, x, y).extrude(height).translate((0, 0, z))


def profile_prism(points, x0, x1):
    """YZ polygon extruded along X."""
    return mf.CrossSection([points]).extrude(x1-x0).rotate((90, 0, 90)).translate((x0, 0, 0))


def bed_relief(solid, depth=.24, inset=.20):
    """Chamfer outer and inner edges of the bottom footprint, preserving holes."""
    section = solid.slice(.001)
    # Replace the bottom slab instead of subtracting a coincident perimeter:
    # clipping a nearly coincident curved perimeter creates float32 slivers.
    solid -= box(300, 300, depth+.01, z=-.01)
    for lo, hi, delta in ((0, depth/2, inset), (depth/2, depth, inset/2)):
        solid += section.offset(-delta, circular_segments=32).extrude(hi-lo).translate((0, 0, lo))
    return solid


def wing_profile():
    r = P['wing_tip_radius']
    return mf.CrossSection.batch_hull([
        circle(r, x, y)
        for x, y in ((14.3, -2), (14.3, 2), (25, -2), (25, 2),
                     (P['wing_tip_x']-r, 0))
    ])


def cam_track(clearance=None):
    gap = P['guide_clearance'] if clearance is None else clearance
    # Analytic normal offsets avoid the tiny slivers made by unioning hundreds
    # of overlapping circles. Chord error is below .001 mm at this sampling.
    angles = np.linspace(0, np.radians(P['rotation_degrees']), 241)
    radii = P['follower_start_radius'] + P['travel'] * angles / angles[-1]
    points = np.column_stack((radii*np.cos(angles), -radii*np.sin(angles)))
    width = P['follower_radius'] + gap
    dr = P['travel'] / angles[-1]
    tangents = np.column_stack((dr*np.cos(angles)-radii*np.sin(angles),
                               -dr*np.sin(angles)-radii*np.cos(angles)))
    tangents /= np.linalg.norm(tangents, axis=1)[:, None]
    normals = tangents[:, [1, 0]] * [-1, 1]
    left, right = points + width*normals, points - width*normals
    end_angle = np.arctan2(normals[-1, 1], normals[-1, 0])
    start_angle = np.arctan2(-normals[0, 1], -normals[0, 0])
    end_arc = np.linspace(end_angle, end_angle-np.pi, 49)[1:-1]
    start_arc = np.linspace(start_angle, start_angle-np.pi, 49)[1:-1]
    return mf.CrossSection([np.vstack((left,
        points[-1] + width*np.column_stack((np.cos(end_arc), np.sin(end_arc))),
        right[::-1], points[0] + width*np.column_stack((np.cos(start_arc), np.sin(start_arc)))))[::-1]])


def stop_slot():
    # Tangential boundaries contact a separate 3 mm stop pin at precisely
    # 0/60 degrees. Radial clearance remains .25 mm on each side.
    margin = np.degrees(np.arcsin(1.5 / 8))
    angles = np.radians(np.linspace(-P['rotation_degrees']-margin, margin, 180))
    outer = np.column_stack((9.75*np.cos(angles), 9.75*np.sin(angles)))
    inner = np.column_stack((6.25*np.cos(angles[::-1]), 6.25*np.sin(angles[::-1])))
    return mf.CrossSection([np.vstack((outer, inner))])


def hook():
    # The wider in-plane tongue supports a stem shifted outward within the original base interface.
    # Keep the retaining shoulder at Z=4.25; extend only the radial engagement.
    # A longer 45-degree insertion ramp prints upward from the inverted lid.
    stem = box(2, 1.0, LID_Z-3.25, x=5, y=34.0, z=3.25)
    tip = 34.65 + P['clip_deflection']
    ramp_bottom = 4.05 - (tip - 34.4)
    catch = profile_prism([(34.35, ramp_bottom), (34.4, ramp_bottom), (tip, 4.05),
                          (tip, 4.25), (34.35, 4.25)], 4, 6)
    return stem + catch


def clip_slots():
    half_gap = P['clip_width']/2 + .35
    return (rect(P['clip_length'], .7, x=-1, y=33.8-half_gap)
            + rect(P['clip_length'], .7, x=-1, y=33.8+half_gap)
            + rect(.7, P['clip_width']+1.4, x=6.35, y=33.8))


def base_clip_cut():
    pocket = box(2.6, 4, LID_Z, x=5, y=32.65, z=2.8)
    window = box(2.6, 6, 1.75, x=5, y=35, z=2.8)
    return pocket + window


def make_parts():
    radius = P['body_radius']
    base = cylinder(radius, FLOOR)
    wall = (circle(radius) - circle(33.6)).extrude(LID_Z-FLOOR).translate((0, 0, FLOOR))
    for i in range(4):
        # Drop-in assembly requires open-top channels, then the cam acts as roof.
        wall -= box(80, P['wing_width']+2*P['guide_clearance'], LID_Z+1).rotate((0, 0, i*90))
    base += wall
    guide_top = CAM_Z - .15
    for i in range(4):
        ribs = mf.Manifold()
        for side in (-1, 1):
            ribs += box(22, 1.6, guide_top-FLOOR, x=23,
                        y=side*(P['wing_width']/2+P['guide_clearance']+.8), z=FLOOR)
        base += ribs.rotate((0, 0, i*90))
    base += cylinder(5.5, guide_top-FLOOR, z=FLOOR)
    base += cylinder(P['axle_radius'], LID_Z-FLOOR, z=FLOOR)
    base += cylinder(1.5, CAM_TOP-.2-FLOOR, x=8, z=FLOOR)
    for angle in P['clip_angles']:
        # Local reinforcement keeps the ledge >1.2 mm thick near the rim.
        base += box(4.4, 2.5, LID_Z-FLOOR, x=5, y=35.05,
                    z=FLOOR, r=.4).rotate((0, 0, angle))
        base -= base_clip_cut().rotate((0, 0, angle))
    base = bed_relief(base)

    wing = wing_profile().extrude(P['wing_thickness'])
    wing += cylinder(P['follower_radius'], CAM_TOP-.2-WING_Z-P['wing_thickness'],
                     x=P['follower_start_radius'], z=P['wing_thickness'])
    wing = bed_relief(wing).translate((0, 0, WING_Z))

    cam = circle(P['cam_radius']).extrude(P['cam_thickness'])
    track = cam_track().extrude(P['cam_thickness']+.2).translate((0, 0, -.1))
    for i in range(4):
        cam -= track.rotate((0, 0, 90*i))
    cam += cylinder(P['knob_radius'], KNOB_TOP-CAM_TOP, z=P['cam_thickness'])
    cam -= cylinder(P['axle_radius']+P['guide_clearance'], KNOB_TOP-CAM_Z+1, z=-.1)
    cam -= stop_slot().extrude(P['cam_thickness']+.001).translate((0, 0, -.001))
    for angle in range(0, 360, 45):
        notch = cylinder(1.6, 4, x=P['knob_radius']+.8, z=LID_TOP-CAM_Z+.2)
        cam -= notch.rotate((0, 0, angle))
    cam = bed_relief(cam).translate((0, 0, CAM_Z))

    lid = (circle(radius) - circle(P['knob_radius']+P['guide_clearance'])).extrude(P['lid_thickness']).translate((0, 0, LID_Z))
    for angle in P['clip_angles']:
        lid -= clip_slots().extrude(P['lid_thickness']+.2).translate((0, 0, LID_Z-.1)).rotate((0, 0, angle))
        lid += hook().rotate((0, 0, angle))
    # The lid prints inverted, so relieve its upper face before returning it.
    lid = bed_relief(lid.rotate((180, 0, 0)).translate((0, 0, LID_TOP)))
    lid = lid.translate((0, 0, -LID_TOP)).rotate((180, 0, 0))
    return {'base': base, **{name: wing.rotate((0, 0, i*90)) for i, name in enumerate(WINGS)},
            'rotor': cam, 'lid': lid}


def mesh_of(solid):
    # Boolean boundaries may differ by nanometres. Simplify first, then discard
    # only triangles whose two endpoints become identical in float32. This is
    # source tessellation cleanup, never a repair of the final exported files.
    raw = solid.simplify(.0001).to_mesh()
    # A 0.1 um grid keeps identical vertices identical after plate translation.
    mesh = trimesh.Trimesh(np.asarray(raw.vert_properties)[:, :3].astype(float).round(4),
                           np.asarray(raw.tri_verts), process=True)
    repeated = np.any(np.diff(np.sort(mesh.faces, axis=1), axis=1) == 0, axis=1)
    mesh.update_faces(~repeated)
    mesh.remove_unreferenced_vertices()
    return mesh


def print_mesh(solid, name):
    mesh = mesh_of(solid)
    transform = trimesh.transformations.rotation_matrix(np.pi if name == 'lid' else 0, [1, 0, 0])
    if name in WINGS:
        transform = trimesh.transformations.rotation_matrix(-WINGS.index(name)*np.pi/2, [0, 0, 1])
    mesh.apply_transform(transform)
    shift = trimesh.transformations.translation_matrix([-mesh.bounds.mean(axis=0)[0],
                                                       -mesh.bounds.mean(axis=0)[1], -mesh.bounds[0, 2]])
    mesh.apply_transform(shift)
    return mesh, shift @ transform


def pose(parts, degrees):
    result = dict(parts)
    for i, name in enumerate(WINGS):
        a = i*np.pi/2
        distance = P['travel'] * degrees/P['rotation_degrees']
        result[name] = parts[name].translate((distance*np.cos(a), distance*np.sin(a), 0))
    result['rotor'] = parts['rotor'].rotate((0, 0, degrees))
    return result
