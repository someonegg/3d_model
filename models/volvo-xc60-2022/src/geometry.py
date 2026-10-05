"""Original parameterized XC60 approximation. Millimetres, front -X, left +Y, up +Z."""
from pathlib import Path
import json
import math
import numpy as np
from scipy.interpolate import PchipInterpolator
import manifold3d as m
import trimesh

HERE = Path(__file__).resolve().parents[1]
P = json.loads((HERE / 'parameters.json').read_text())
L = P['vehicle_mm']['length'] / P['scale']
WB = P['vehicle_mm']['wheelbase'] / P['scale']
AXLES = (P['front_axle_x_mm'], P['front_axle_x_mm'] + WB)
COLORS = {'white': [232, 236, 232, 255], 'black': [32, 38, 44, 255],
          'silver': [158, 169, 179, 255], 'red': [162, 26, 39, 255],
          'light': [218, 236, 245, 255], 'interior': [115, 83, 61, 255]}


def union(*items):
    return m.Manifold.batch_boolean(list(items), m.OpType.Add)


def box(size, center):
    return m.Manifold.cube(size, center=True).translate(center)


def cyl(radius, height, center, axis='z', segments=64):
    obj = m.Manifold.cylinder(height, radius, circular_segments=segments, center=True)
    if axis == 'y':
        obj = obj.rotate((90, 0, 0))
    elif axis == 'x':
        obj = obj.rotate((0, 90, 0))
    return obj.translate(center)


def rod(a, b, radius=0.6):
    a, b = np.asarray(a), np.asarray(b)
    direction = b - a
    mesh = trimesh.creation.cylinder(radius=radius, height=np.linalg.norm(direction), sections=24)
    tf = trimesh.geometry.align_vectors([0, 0, 1], direction)
    tf[:3, 3] = (a + b) / 2
    mesh.apply_transform(tf)
    return solid(mesh)


def solid(mesh):
    return m.Manifold(m.Mesh(np.asarray(mesh.vertices, np.float32), np.asarray(mesh.faces, np.uint32)))


def mesh(obj):
    # Quantize the constructive result before triangulated export. Boolean
    # intersections can introduce sub-micron edges that STL float32 collapses.
    # Weld only this 0.0001 mm grid and omit collapsed index triangles; no hole
    # filling or repair is applied to exported files or validation inputs.
    raw = obj.simplify(.002).to_mesh64()
    vertices, inverse = np.unique(np.round(raw.vert_properties[:, :3], 4), axis=0, return_inverse=True)
    faces = inverse[raw.tri_verts]
    keep = (faces[:,0]!=faces[:,1]) & (faces[:,1]!=faces[:,2]) & (faces[:,0]!=faces[:,2])
    canonical = m.Manifold(m.Mesh64(vertices, np.asarray(faces[keep], np.uint64))).simplify(.002)
    raw = canonical.to_mesh()
    vertices, inverse = np.unique(raw.vert_properties[:, :3], axis=0, return_inverse=True)
    faces = inverse[raw.tri_verts]
    keep = (faces[:,0]!=faces[:,1]) & (faces[:,1]!=faces[:,2]) & (faces[:,0]!=faces[:,2])
    return trimesh.Trimesh(vertices=vertices, faces=faces[keep], process=False)



def prism_xz(points, y0, y1, offset=0):
    points = np.asarray(points)
    if np.sum(points[:, 0]*np.roll(points[:, 1], -1)-points[:, 1]*np.roll(points[:, 0], -1)) < 0:
        points = points[::-1]
    section = m.CrossSection([points])
    if offset:
        section = section.offset(offset, m.JoinType.Round, circular_segments=24)
    # Extrusion +Z becomes -Y. Cross-section Y becomes vehicle Z.
    return section.extrude(y1-y0).rotate((90, 0, 0)).translate((0, y1, 0))


def rounded_box(size, center, radius=1):
    sx, sy, sz = size
    outline = m.CrossSection.square((sx-2*radius, sy-2*radius), center=True).offset(radius, circular_segments=32)
    return outline.extrude(sz).translate((center[0], center[1], center[2]-sz/2))


def loft(inner=False):
    # Longitudinal stations from front bumper to rear bumper: width, roof height,
    # roof half-width. The interpolator preserves bonnet and roof transitions.
    stations = np.array([
        [-L/2, 31.8, 39.5, 26.0], [-95, 36.0, 43.0, 29.5],
        [-86, 38.5, 45.0, 31.0], [-67, 39.625, 46.2, 31.5],
        [-43, 39.0, 48.1, 32.2], [-36, 38.8, 49.5, 32.0],
        [-16, 38.8, 66.3, 30.0], [-8, 38.8, 68.5, 29.8],
        [17, 39.0, 69.0833, 30.0], [47, 39.5, 68.8, 30.0],
        [65, 39.625, 67.2, 29.6], [73, 39.4, 63.5, 29.6],
        [88, 38.7, 52.0, 31.6], [95, 36.8, 46.0, 31.8],
        [L/2, 32.5, 41.8, 29.0]])
    wall = P['shell_mm'] if inner else 0
    xs = np.unique(np.r_[np.linspace(-L/2 + wall, L/2-wall, 121), stations[1:-1, 0]])
    values = PchipInterpolator(stations[:, 0], stations[:, 1:], axis=0)(xs)
    vertices = []
    for x, (w, h, rw) in zip(xs, values):
        w -= wall
        rw -= wall
        h -= wall
        bottom = -5 if inner else 10.0
        belt = min(44.8-wall, h-1.2)
        # Side creases, chamfered shoulders, tilted greenhouse, gently crowned roof.
        half = [(0, bottom), (.82*w, bottom), (.92*w, 12-wall),
                (.955*w, 18-wall), (.97*w, 25-wall), (w, 37-wall),
                (w*.996, belt-1.3), (.966*w, belt),
                (rw+1.3, h-2.0), (rw, h-.65), (rw*.72, h-.13), (0, h)]
        ring = np.asarray(half + [(-y, z) for y, z in half[-2:0:-1]])
        for _ in range(2):
            following = np.roll(ring, -1, axis=0)
            ring = np.stack((.75*ring+.25*following, .25*ring+.75*following), axis=1).reshape(-1,2)
        ring[:,0] *= w / np.max(np.abs(ring[:,0]))
        ring[:,1] = bottom+(ring[:,1]-bottom)*(h-bottom)/(np.max(ring[:,1])-bottom)
        vertices.extend((x, y, z) for y, z in ring)
    n = len(ring)
    faces = []
    for j in range(len(xs)-1):
        for i in range(n):
            k = (i+1) % n
            faces.extend([(j*n+i, (j+1)*n+i, (j+1)*n+k), (j*n+i, (j+1)*n+k, j*n+k)])
    # End rings are convex enough for a centroid fan, avoiding diagonal crossings.
    for j, reverse in [(0, False), (len(xs)-1, True)]:
        center = np.mean(vertices[j*n:(j+1)*n], axis=0)
        ci = len(vertices)
        vertices.append(center)
        for i in range(n):
            face = (ci, j*n+i, j*n+(i+1) % n)
            faces.append(face[::-1] if reverse else face)
    out = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    if out.volume < 0:
        out.invert()
    result = solid(out)
    if result.status() != m.Error.NoError:
        raise ValueError(f'loft: {result.status()}')
    return result


def mirrored(obj, side):
    return obj if side == 1 else obj.mirror((0, 1, 0))


def open_door(obj, side, angle):
    hx, hy = P['hinge_xy_mm']
    pivot = (hx, side*hy, 0)
    return obj.translate(tuple(-v for v in pivot)).rotate((0, 0, side*angle)).translate(pivot)


DOOR = [(-33.0, 18), (8.0, 18), (8.0, 65.0), (-13.0, 64.5), (-38.0, 45.8), (-38.0, 24.0)]
FRONT_GLASS = [(-33.5, 47.2), (5.2, 47.2), (5.2, 63.0), (-12.0, 63.0)]
REAR_GLASS = [(12.0, 47.2), (46, 47.2), (47, 63.2), (12, 63.2)]
QUARTER_GLASS = [(50.5, 47.2), (79.3, 47.2), (66.0, 62.8), (51.0, 63.2)]


def make_parts():
    parts = []
    def add(name, obj, color, group='fixed', rotation=(0, 0, 0)):
        if obj.is_empty() or obj.status() != m.Error.NoError:
            raise ValueError(f'{name}: {obj.status()}')
        parts.append(dict(name=name, solid=obj, color=color, group=group, rotation=rotation))

    skin = loft() - loft(inner=True)
    # Through wheel openings; lower halves open all the way to the sill.
    arch_cuts = []
    for x in AXLES:
        arch_cuts.extend([cyl(16.8, 110, (x, 0, P['wheel_radius_mm']), 'y'),
                          box((33.6, 110, 30), (x, 0, .4))])
    skin -= union(*arch_cuts)
    # Inset bonnet and tailgate seams, only a shallow engraving.
    seams = []
    for s in [-1, 1]:
        seams.append(rod((-88, s*26, 45), (-42, s*28.5, 48), .35))
    skin -= union(*seams)

    doors = {}
    for s in [1, -1]:
        region = mirrored(prism_xz(DOOR, 20, 55), s)
        doors[s] = skin ^ region
        skin -= mirrored(prism_xz(DOOR, 20, 55, P['door_gap_mm']), s)

    # Flush glass inserts, with continuous inner mounting lips and glue clearance.
    def window(host, outline, side, name, group):
        cut = mirrored(prism_xz(outline, 20, 55), side)
        smaller = mirrored(prism_xz(outline, 20, 55, -.23), side)
        insert = host ^ smaller
        # Flange follows the same compound curvature, inset from outer surface.
        flange = (host ^ mirrored(prism_xz(outline, 20, 55, .7), side)).translate((0, -side*.85, 0))
        insert = union(insert, flange)
        add(name, insert, 'black', group, (side*90, 0, 0))
        return host-cut-insert

    for s, suffix in [(1, 'left'), (-1, 'right')]:
        doors[s] = window(doors[s], FRONT_GLASS, s, 'glass-front-'+suffix, 'door-'+suffix)
        skin = window(skin, REAR_GLASS, s, 'glass-rear-'+suffix, 'fixed')
        skin = window(skin, QUARTER_GLASS, s, 'glass-quarter-'+suffix, 'fixed')
    for name, extent, center in [('windshield', (21, 57, 50), (-25.2, 0, 67)),
                                  ('rear-window', (16, 56, 35), (80.5, 0, 66))]:
        cutter = box(extent, center)
        plug = skin ^ box((extent[0]-.46, extent[1]-.46, extent[2]), center)
        lip = (skin ^ box((extent[0]+1.3, extent[1]+1.3, extent[2]), center)).translate((0, 0, -.85))
        add(name, union(plug, lip), 'black', rotation=(0, -40 if name == 'windshield' else 40, 0))
        skin -= union(cutter, plug, lip)
    # Panoramic roof panel: recessed 0.65 mm, supported by the roof beneath.
    sunroof = rounded_box((53, 43, 1), (23, 0, 68.75), 3)
    skin -= sunroof
    add('panoramic-roof', rounded_box((52.55, 42.55, 1), (23, 0, 68.75), 2.8), 'black')

    hinge_fixed = []
    hx, hy = P['hinge_xy_mm']
    hr = P['hinge_radius_mm']
    for s, suffix in [(1, 'left'), (-1, 'right')]:
        bore = cyl(P['hinge_bore_mm']/2, 26, (hx, hy, 31))
        fixed = union(cyl(hr, 4, (hx, hy, 23)), cyl(hr, 4, (hx, hy, 39)),
                      box((5.8, 3.6, 4), (hx-2.8, hy, 23)),
                      box((5.8, 3.6, 4), (hx-2.8, hy, 39))) - bore
        gap = P['hinge_axial_gap_mm']
        moving = union(cyl(hr, 12-2*gap, (hx, hy, 31)),
                       box((10.5, 3.1, 9.75), (hx+4.5, hy, 31.875)),
                       box((4, 7, 9.75), (hx+7, hy+2, 31.875))) - bore
        def sector(a0, a1, r0, r1, z0, height):
            angles = np.radians(np.linspace(a0, a1, 25))
            pts = [(hx+r1*np.cos(a), hy+r1*np.sin(a)) for a in angles]
            pts += [(hx+r0*np.cos(a), hy+r0*np.sin(a)) for a in angles[::-1]]
            return m.CrossSection([pts]).extrude(height).translate((0, 0, z0))
        moving = union(moving, sector(-12, 0, 2.1, 3.7, 25.25, 1.0))
        fixed = union(fixed, cyl(3.9, .5, (hx, hy, 24.75)),
                      sector(60, 80, 2.5, 3.7, 25.0, 1.25),
                      sector(-30, -12, 2.5, 3.7, 25.0, 1.25)) - bore
        fixed = fixed.translate((0, 0, 6))
        moving = moving.translate((0, 0, 6))
        hinge_fixed.append(mirrored(fixed, s))
        doors[s] = union(doors[s], mirrored(moving, s))
        ledge = box((6, 4, 1.5), (5.3, 34.7, 16.95))
        skin = union(skin, mirrored(ledge, s))
        # Door card remains below glazing and includes armrest; continuous overlap to door skin.
        panel = rounded_box((35, 1.6, 17), (-12, 35.5, 31), .6)
        panel = union(panel, box((14, 3.1, 2.4), (-13, 34.8, 32)))
        # Separate bonded liner, with clearance from white shell.
        doors[s] -= mirrored(panel, s)
        add('door-card-'+suffix, mirrored(panel, s), 'interior', 'door-'+suffix, (s*90, 0, 0))
        # Replaceable friction leaf with keyed socket in the B pillar.
        socket = box((3.4, 7.4, 5), (10.2, 33.5, 26))
        mount = box((5, 5, 7), (10.8, 35, 26)) - socket
        skin = union(skin, mirrored(mount, s))
        clip = union(box((3, 3.4, 4.6), (10.2, 35, 26)),
                     box((6, 1.2, 4), (6, 34.25, 26)))
        add('door-clip-'+suffix, mirrored(clip, s), 'black', rotation=(0, 90, 0))
        # Handle and wing mirror are supported by locating recesses on the door.
        handle = rounded_box((5.7, 1.6, 1.4), (1, 39.2, 41), .5)
        doors[s] = union(doors[s], mirrored(handle, s))
        mirror = union(box((3.4, 5.0, 2.4), (-31, 39, 46)),
                       rounded_box((7.2, 5.6, 3.8), (-31.4, 42.2, 47.1), 1.4))
        mirror_cut = box((3.8, 3.2, 2.8), (-31, 37.7, 46))
        doors[s] -= mirrored(mirror_cut, s)
        add('mirror-'+suffix, mirrored(mirror, s), 'white', 'door-'+suffix)
        add('door-'+suffix, doors[s], 'white', 'door-'+suffix, (s*90, 0, 0))

    # Rear door engraved seams and rear handles.
    for s in [-1, 1]:
        groove = prism_xz([(48, 34), (49, 44.5), (49.65, 44.5), (48.65, 34)], 38, 43)
        skin -= mirrored(groove, s)
        skin = union(skin, mirrored(rounded_box((5.7, 1.5, 1.4), (40.5, 39.25, 41), .5), s))
    # Roof rails have broad feet bonded directly to the roof.
    for s, suffix in [(1, 'left'), (-1, 'right')]:
        rail = union(rod((-9, s*28.4, 68.0), (52, s*28.4, 68.9), .65),
                     box((4, 1.7, 1.8), (-7, s*28.4, 67.9)),
                     box((4, 1.7, 1.8), (50, s*28.4, 68.8)))
        skin -= rail
        add('roof-rail-'+suffix, rail, 'silver', rotation=(90, 0, 0))

    # M2 pilot bosses accessible from below. Broad tabs intersect the shell.
    mounts = [(-82, -24), (-82, 24), (84, -24), (84, 24)]
    for x, y in mounts:
        boss = union(cyl(3.8, 6.4, (x, y, 15.8)), box((8, 15, 3), (x, np.sign(y)*29.5, 14.1)))
        boss -= cyl(.85, 8, (x, y, 13.8))
        skin = union(skin, boss)

    # Front grille separate silver slats over black recessed backing.
    grille_outline = [(-19, 29), (19, 29), (21, 40), (18.5, 42), (-18.5, 42), (-21, 40)]
    # Cross-section coordinates become vehicle Y,Z; extrusion becomes X.
    def front_prism(poly, x0, depth):
        return m.CrossSection([poly]).extrude(depth).rotate((90, 0, 90)).translate((x0, 0, 0))
    grille = front_prism(grille_outline, -98.4, 2.8)
    skin -= grille
    backing = front_prism(grille_outline, -97.0, 1.15)
    add('grille-backing', backing, 'black', rotation=(0, 90, 0))
    section = m.CrossSection([grille_outline])
    frame = (section-section.offset(-.85)).extrude(1.4).rotate((90, 0, 90)).translate((-98.4, 0, 0))
    bars = [box((1.3, .8, 11.5), (-97.75, y, 35.5)) for y in np.arange(-17.5, 18, 2.5)]
    slash = rod((-98.6, -17, 29.7), (-98.6, 17, 41.2), .65)
    badge = cyl(2.6, 1.0, (-98.9, 0, 35.5), 'x') - cyl(1.75, 2, (-98.9, 0, 35.5), 'x')
    grille_silver = union(frame, *bars, slash, badge)
    add('grille-silver', grille_silver, 'silver', rotation=(0, -90, 0))
    lower = front_prism([(-24, 18), (24, 18), (20, 25), (-20, 25)], -98.35, 3.2)
    skin -= lower
    add('lower-intake', lower.translate((.05, 0, 0)), 'black', rotation=(0, 90, 0))
    # Headlight surround and Thor hammer inserts on front corners.
    for s, suffix in [(1, 'left'), (-1, 'right')]:
        housing = box((2.3, 13.2, 4.5), (-97.2, 27.8, 39.7))
        skin -= mirrored(housing, s)
        add('headlamp-'+suffix, mirrored(housing, s), 'black', rotation=(0, 90, 0))
        hammer = union(box((1.0, 12.5, .85), (-98.5, 27.6, 40.0)),
                       box((1.0, .9, 3.7), (-98.5, 24.2, 39.7)))
        next(p for p in parts if p['name']=='headlamp-'+suffix)['solid'] -= mirrored(hammer, s)
        add('daylight-'+suffix, mirrored(hammer, s), 'light', rotation=(0, -90, 0))
        vent = box((3.5, 6, 7), (-96.6, 28.8, 22))
        skin -= mirrored(vent, s)
        add('bumper-vent-'+suffix, mirrored(vent, s), 'black', rotation=(0, 90, 0))
        # Sculpted vertical tail lamps following hatch corners, with horizontal hook.
        lamp = union(rod((72, 32.3, 61.5), (85, 36.0, 49.7), 1.2),
                     rod((85, 36.0, 49.7), (94, 35.7, 37.6), 1.25),
                     rod((94, 35.7, 37.6), (95.9, 23.3, 37.6), 1.15))
        skin -= mirrored(lamp, s)
        add('tail-lamp-'+suffix, mirrored(lamp, s), 'red', rotation=(s*90, 0, 0))
    # Rear wordmark engraved with 0.65 mm strokes, plus recessed number plates.
    strokes = {
        'V': [[(0,2.4),(1,0),(2,2.4)]],
        'O': [[(.4,0),(1.6,0),(2,.4),(2,2),(1.6,2.4),(.4,2.4),(0,2),(0,.4),(.4,0)]],
        'L': [[(0,2.4),(0,0),(2,0)]]}
    engraving=[]
    for i,letter in enumerate('VOLVO'):
        for path in strokes[letter]:
            for a,b in zip(path,path[1:]):
                engraving.append(rod((98.0, 7.5-i*3.5-a[0], 36+a[1]),
                                     (98.0, 7.5-i*3.5-b[0], 36+b[1]), .325))
    skin -= union(*engraving)
    for name,x,z in [('front-numberplate',-98.05,27),('rear-numberplate',97.95,29)]:
        plate = box((1.1,14,3.0), (x,0,z))
        skin -= plate
        add(name, plate, 'black', rotation=(0,90,0))
    # Reinforced continuous sills link the front clip to the passenger shell.
    for side in [-1, 1]:
        rail = box((57, 3.4, 3.0), (-15, side*36.0, 16.1))
        skin = union(skin, rail)
    skin = union(skin, box((5, 76, 35), (-39, 0, 31.5)) ^ loft())
    # Conservative continuous sweep: convex hull of adjacent poses plus a
    # 0.12 mm cube offset. At 0.5 degree intervals this encloses the rotational
    # arc (sagitta < 0.001 mm for every point of this door).
    for side in [-1, 1]:
        door_hull = doors[side].hull()
        hulls = []
        offsets = np.array([[x,y,z] for x in [-.12,.12] for y in [-.12,.12] for z in [-.12,.12]])
        for a in np.arange(0, P['door_open_deg'], .5):
            points = np.concatenate([mesh(open_door(door_hull,side,float(t))).vertices for t in [a,a+.5]])
            hulls.append(m.Manifold.hull_points((points[:,None,:]+offsets[None,:,:]).reshape(-1,3)))
        envelope = union(*hulls)
        skin -= envelope
        for v in parts:
            if v['name']=='windshield':
                # Materialize each trimmed insert before the next Boolean chain.
                v['solid'] = solid(mesh(v['solid'] - envelope))
    skin = union(skin, *hinge_fixed)
    for side in [-1, 1]:
        skin -= cyl(P['hinge_bore_mm']/2,32,(hx,side*hy,37))
    for x in AXLES:
        for side in [-1, 1]:
            skin -= cyl(16.2, 15, (x, side*35, P['wheel_radius_mm']), 'y')
    for clip in [v for v in parts if v['name'].startswith('door-clip')]:
        # Retain only the 0.15 mm flexible contact at the door liner.
        skin -= clip['solid']
    add('body', skin, 'white')

    # Chassis, with wheel wells cut clear and screw heads recessed from below.
    chassis = rounded_box((185, 69, 2.4), (0, 0, 11.2), 5)
    for x in AXLES:
        for s in [-1, 1]:
            chassis -= box((34.4, 25, 20), (x, s*34, 11))
        # Axle bearings separated from the floor, with foot fusion.
        for y in [-18, 18]:
            bearing = box((7, 7, 7), (x, y, 14.3)) - cyl(P['axle_bore_mm']/2, 10, (x, y, P['wheel_radius_mm']), 'y')
            chassis = union(chassis, bearing)
    for x, y in mounts:
        chassis -= union(cyl(1.2, 12, (x, y, 11)), cyl(2.1, 1.4, (x, y, 10.4)))
    # Interior locating posts and corresponding sockets.
    for x in [-10, 34]:
        chassis = union(chassis, cyl(1.5, 3, (x, 0, 13)))
    chassis -= skin
    add('chassis', chassis, 'black')

    tray = rounded_box((88, 61, 1.6), (9.5, 0, 14.2), 3)
    for x in [-10, 34]:
        tray -= cyl(1.7, 6, (x, 0, 14))
    # Front buckets and rear bench have printable connected headrests.
    seats = []
    for y in [-18, 18]:
        seats.extend([rounded_box((20, 18, 6), (-4, y, 20), 3),
                      rounded_box((4.5, 18, 19), (4.5, y, 29), 1.8),
                      rounded_box((4.7, 10, 7), (4.5, y, 41), 1.5),
                      box((3, 12, 4), (-4, y, 16))])
    seats.extend([rounded_box((21, 53, 6), (36, 0, 20), 3),
                  rounded_box((5, 53, 18), (44, 0, 29), 2)])
    for y in [-18, 0, 18]:
        seats.append(rounded_box((5, 10, 7), (44, y, 40), 1.4))
    # All seats joined to tray with pedestals.
    seats.append(box((15, 47, 5), (36, 0, 16.5)))
    cabin = union(tray, *seats, box((38, 7, 11), (-5, 0, 20)))
    for x in AXLES:
        for side in [-1, 1]:
            cabin -= cyl(16.8, 15, (x, side*35, P['wheel_radius_mm']), 'y')
    for x in [-10, 34]:
        cabin -= cyl(1.7, 4.5, (x, 0, 14.2))
    add('interior', cabin, 'interior')
    dash = union(rounded_box((9, 62, 7), (-29, 0, 38), 2),
                 box((3, 8, 21), (-30, -23, 25.5)), box((3, 8, 21), (-30, 23, 25.5)),
                 box((3, 9, 10), (-23, 0, 35)))
    steering = cyl(6, 1.5, (-20.5, 18, 38.5), 'x') - cyl(4.8, 4, (-20.5, 18, 38.5), 'x')
    spokes = [rod((-20.5, 18, 38.5), (-20.5, 18+4.9*math.cos(a), 38.5+4.9*math.sin(a)), .65) for a in [0, math.pi, -math.pi/2]]
    dash = union(dash, steering, *spokes, cyl(1.2, 7, (-24, 18, 38.5), 'x'))
    add('dashboard', dash, 'black')

    # 235/55 R19 tyres: outer diameter 30.89, wheel rim diameter 20.11.
    for axle_index, x in enumerate(AXLES):
        for s, suffix in [(1, 'left'), (-1, 'right')]:
            y = s*P['wheel_center_y_mm']
            z = P['wheel_radius_mm']
            tyre = cyl(z, P['wheel_width_mm'], (x, y, z), 'y', 128) - cyl(10.25, 13, (x, y, z), 'y', 96)
            # Three circumferential tread grooves, 0.65 wide and 0.45 deep.
            for dy in [-2.5, 0, 2.5]:
                groove = cyl(z+.2, .65, (x, y+dy, z), 'y', 128) - cyl(z-.45, 1, (x, y+dy, z), 'y', 128)
                tyre -= groove
            rim = cyl(10.0, 8.9, (x, y, z), 'y', 96) - cyl(8.5, 12, (x, y, z), 'y', 96)
            hub = cyl(3.4, 8.9, (x, y, z), 'y')
            spoke_parts = []
            for a in np.linspace(0, 2*math.pi, 5, endpoint=False):
                for delta in [-.11, .11]:
                    spoke_parts.append(rod((x+2.8*math.cos(a), y+s*3.4, z+2.8*math.sin(a)),
                                           (x+9.1*math.cos(a+delta), y+s*3.4, z+9.1*math.sin(a+delta)), .7))
            rim = union(rim, hub, *spoke_parts) - cyl(1.1, 20, (x, y, z), 'y')
            add(f'tyre-{axle_index}-{suffix}', tyre, 'black', 'wheel', (90, 0, 0))
            add(f'rim-{axle_index}-{suffix}', rim, 'silver', 'wheel', (90, 0, 0))
            # Outside cap bonds to hub AFTER axle insertion, enclosing its end.
            cap = cyl(3.5, 1.0, (x, y+s*5.0, z), 'y')
            add(f'hubcap-{axle_index}-{suffix}', cap, 'silver', 'wheel', (90, 0, 0))
            spacer = cyl(2.3, 7.9, (x, s*25.7, z), 'y') - cyl(1.2, 10, (x, s*25.7, z), 'y')
            add(f'axle-spacer-{axle_index}-{suffix}', spacer, 'black', 'wheel', (90, 0, 0))
    return parts


def make_coupon():
    base = rounded_box((72, 45, 2.0), (0, 0, 1), 2)
    for i, diameter in enumerate([1.7, 1.85, 2.0, 2.2, 2.4, 2.6]):
        x = -19 + i*7.6
        tube = cyl(2.8, 8, (x, 4, 6)) - cyl(diameter/2, 12, (x, 4, 6))
        base = union(base, tube)
        base -= cyl(diameter/2, 5, (x, 4, 1))
        # Binary-free tactile count: one to six shallow notches on the front edge.
        for j in range(i+1):
            base -= box((.55, 1.8, .7), (x-2.4+j*.8, -11.9, 1.8))
    fixed = union(box((15, 9, 2), (-13, -5, 3)), cyl(2.3, 4, (-13, -5, 5)), cyl(2.3, 4, (-13, -5, 21)),
                  box((3, 6, 18), (-17, -5, 12)), box((5, 3, 4), (-15, -5, 21)))
    fixed -= cyl(P['hinge_bore_mm']/2, 30, (-13, -5, 12))
    base = union(base, fixed)
    # Separated movable knuckle; print upright, then place in the fork using a metal pin.
    moving = union(cyl(2.3, 11.5, (7, -5, 5.75)), box((10, 3, 11.5), (12, -5, 5.75)))
    moving -= cyl(P['hinge_bore_mm']/2, 14, (7, -5, 5.75))
    sliders=[]
    for x,gap in [(-22,.25),(0,.35),(22,.45)]:
        channel = box((10,8,3), (x,16,3.5)) - box((4+2*gap,10,4), (x,16,4))
        base=union(base,channel)
        sliders.append(box((4,6,3),(x,-32,1.5)))
    moving = moving.rotate((90,0,0))
    low = np.asarray(moving.bounding_box()[:3])
    moving = moving.translate(np.asarray([45.,-12.,0.])-low)
    return (base, moving, *sliders)
