"""Model dimensions, geometry and print orientation."""
from pathlib import Path
import json
import numpy as np
import trimesh
import manifold3d as mf

NAME = 'fidget-button-fdm.stl'
PARAMETERS = json.loads((Path(__file__).resolve().parents[1] / 'parameters.json').read_text())
SEGMENTS = PARAMETERS['segments']
SPRING_THICKNESS = PARAMETERS['spring_thickness']
LOCK_INTERFERENCE = PARAMETERS['lock_interference']
PLUG_BUMP_HEIGHT = PARAMETERS['plug_bump_height']
SHELL_BUMP_HEIGHT = 0.25 + LOCK_INTERFERENCE - PLUG_BUMP_HEIGHT
LOCK_WIDTH_DEG = PARAMETERS['lock_width_deg']
GUIDE_HEIGHT = PARAMETERS['guide_height']
GUIDE_BORE_RADIUS = PARAMETERS['guide_bore_radius']
GUIDE_FLAT_X = PARAMETERS['guide_flat_x']
CAP_FLAT_X = PARAMETERS['cap_flat_x']
P = dict(PARAMETERS['dimensions'])
P['cap_face_z'] = P['shell_top_z'] + P['protrusion']
P['skirt_top'] = P['face_height'] + P['skirt_height']
P['pusher_height'] = P['cap_face_z'] - P['spring_seat_z'] - SPRING_THICKNESS
P['stop_z'] = P['spring_seat_z'] + SPRING_THICKNESS - P['travel']
P['root_x'] = -(P['support_inner_radius']**2-(P['pad_y']+P['arm_width']/2)**2)**0.5 + P['root_fillet']

def revolve(profile, radial_mod=None):
    """Revolve a closed radial/Z polygon, preserving a single vertex on the axis."""
    angles = np.arange(SEGMENTS) * (2 * np.pi / SEGMENTS)
    vertices = []
    rings = []
    for profile_index, (radius, z) in enumerate(profile):
        if radius == 0:
            rings.append([len(vertices)] * SEGMENTS)
            vertices.append((0.0, 0.0, z))
        else:
            indices = []
            for angle in angles:
                indices.append(len(vertices))
                local_radius = radius + (radial_mod(profile_index, angle) if radial_mod else 0)
                vertices.append((local_radius * np.cos(angle), local_radius * np.sin(angle), z))
            rings.append(indices)
    faces = []
    for index in range(len(profile)):
        a = rings[index]
        b = rings[(index + 1) % len(profile)]
        if profile[index][0] == 0 and profile[(index + 1) % len(profile)][0] == 0:
            continue
        for sector in range(SEGMENTS):
            next_sector = (sector + 1) % SEGMENTS
            if profile[index][0] == 0:
                faces.append((a[sector], b[sector], b[next_sector]))
            elif profile[(index + 1) % len(profile)][0] == 0:
                faces.append((a[sector], b[sector], a[next_sector]))
            else:
                faces.extend(((a[sector], b[sector], b[next_sector]),
                              (a[sector], b[next_sector], a[next_sector])))
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.merge_vertices()
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.remove_unreferenced_vertices()
    if mesh.volume < 0:
        mesh.invert()
    return mesh


def lock_weight(angle):
    """Six broad lobes, smooth circumferential entry from either direction."""
    distance = abs((angle + np.pi/6) % (np.pi/3) - np.pi/6)
    return max(0.0, np.cos(np.pi * distance / np.radians(LOCK_WIDTH_DEG))) ** 2 if distance < np.radians(LOCK_WIDTH_DEG/2) else 0.0


def spring_section():
    """Opposed long arms with 1 mm concave root fillets, printed in XY."""
    ring = mf.CrossSection.circle(17.1, SEGMENTS) - mf.CrossSection.circle(P['support_inner_radius'], SEGMENTS)
    span = P['arm_tip'] + 16.2
    for side in (-1, 1):
        arm = mf.CrossSection.square((span, P['arm_width']), center=True).translate(((P['arm_tip']-16.2)/2, P['pad_y']))
        ring += arm if side == 1 else arm.rotate(180)
    closed = ring.offset(P['root_fillet'], circular_segments=64).offset(-P['root_fillet'], circular_segments=64)
    # Only add rounding at the two anchored roots; never close the tip gap.
    for side in (-1, 1):
        root_zone = mf.CrossSection.square((4, P['arm_width']+1.8*P['root_fillet']), center=True).translate((-14.0, P['pad_y']))
        if side == -1:
            root_zone = root_zone.rotate(180)
        ring += closed ^ root_zone
    return ring


def spring():
    section = spring_section()
    # Broad frame doubles as a keyed cup; the beams remain independently parameterized in thickness.
    bore = mf.CrossSection.circle(GUIDE_BORE_RADIUS, SEGMENTS) ^ mf.CrossSection.square((2*GUIDE_FLAT_X, 40), center=True)
    guide = mf.CrossSection.circle(17.0, SEGMENTS) - bore
    raw = (section.extrude(SPRING_THICKNESS) + guide.extrude(GUIDE_HEIGHT)).to_mesh()
    return trimesh.Trimesh(np.asarray(raw.vert_properties)[:,:3], np.asarray(raw.tri_verts), process=True)


def make_parts():
    # Shell prints with its top face on the bed; the cavity grows upward.
    shell = revolve([(13.0, 0), (P['outer_radius'], 0), (P['outer_radius'], 17.0),
                     (17.5, 17.0), (17.5, 16.7), (17.5, 16.4),
                     (17.5, 15.2), (17.5, 14.9), (17.5, 2.5), (13.0, 2.5)],
                    radial_mod=lambda i, a: -SHELL_BUMP_HEIGHT * lock_weight(a) if i in (5, 6) else 0)
    # Cap prints face down. Its annular pusher leaves room for the center stop.
    cap = revolve([(0, 0), (12.6, 0), (12.6, P['face_height']), (13.8, P['face_height']),
                   (13.8, P['skirt_top']), (0, P['skirt_top'])])
    cap_solid = mf.Manifold(mf.Mesh(np.asarray(cap.vertices, dtype=np.float32), np.asarray(cap.faces, dtype=np.uint32)))
    cap_solid ^= mf.Manifold.cube((2*CAP_FLAT_X, 40, 20), center=True)
    ring = (mf.CrossSection.circle(P['stop_radius'], 96) - mf.CrossSection.circle(P['stop_radius']-.4, 96)).extrude(P['pusher_height']-P['skirt_top']).translate((0,0,P['skirt_top']))
    cap_solid += ring
    for side in (-1, 1):
        cap_solid += mf.Manifold.cube((P['pad_length'], P['pad_size'], P['pusher_height']-P['skirt_top'])).translate((side*P['pad_x']-P['pad_length']/2, -side*P['pad_y']-P['pad_size']/2,P['skirt_top']))
    raw = cap_solid.to_mesh()
    cap = trimesh.Trimesh(np.asarray(raw.vert_properties)[:,:3], np.asarray(raw.tri_verts), process=True)
    # The plug supports the spring rim and stops the cap after the specified travel.
    def grip(profile_index, angle):
        # Broad lobes with axial and circumferential lead-in/out ramps.
        if profile_index in (5, 6):
            return PLUG_BUMP_HEIGHT * lock_weight(angle)
        # Two opposed recesses at the seam; the bottom stays flat and full-size.
        if profile_index == 3:
            return -2.0 * max(0.0, np.cos(2 * angle)) ** 16
        return 0.0

    plug = revolve([(0, 0), (P['outer_radius'], 0), (P['outer_radius'], 1.2), (P['outer_radius'], 2.4),
                    (17.25, 2.4), (17.25, 3.0), (17.25, 4.2),
                    (17.25, 4.8), (17.25, 10.24), (17.05, 11.04),
                    (14.0, 11.04), (14.0, 2.4), (P['stop_radius'], 2.4),
                    (P['stop_radius'], P['stop_z']+2.4), (0, P['stop_z']+2.4)], radial_mod=grip)
    def mark(mesh, angles, z):
        solid = mf.Manifold(mf.Mesh(np.asarray(mesh.vertices,dtype=np.float32), np.asarray(mesh.faces,dtype=np.uint32)))
        for angle in angles:
            solid -= mf.Manifold.cube((1.2,.8,.8),center=True).translate((P['outer_radius'],0,z)).rotate((0,0,angle))
        raw = solid.to_mesh()
        return trimesh.Trimesh(np.asarray(raw.vert_properties)[:,:3],np.asarray(raw.tri_verts),process=True)
    shell = mark(shell, (60,), 16.6)
    plug = mark(plug, (60,90,93), 1.9)
    return [('外壳', shell), ('按帽', cap), ('底盖', plug), ('弹片', spring())]


