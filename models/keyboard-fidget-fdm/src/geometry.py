"""Model dimensions, geometry and print orientation."""
from pathlib import Path
import json
import numpy as np
import trimesh
import manifold3d as mf

PARAMETERS = json.loads((Path(__file__).resolve().parents[1] / 'parameters.json').read_text())
P = dict(PARAMETERS['dimensions'])
RESOLUTION = PARAMETERS['resolution']
P['window_edge'] = P['frame_half'] - P['side_wall']
P.update(shoe_inner=P['click_x']-1.8, shelf_x=P['click_x']+.2, beam_relief_x=P['click_x']+1.3, strike_x=P['click_x']-2.2, plate_edge=12.7, cam_root=12.6, cam_peak=13.6, cam_entry=13.2, cam_exit=12.9, cam_bottom=10.25, cam_push_height=.60, cam_peak_height=.40, cam_release_height=.40, contact_bottom=8.8, contact_height=.60)
P['return_contact_length'] = P['return_pad_y'] - P['return_pad_depth']/2 - P['return_root_y']
NAMES = dict(shell='外壳', base='底座', plunger='导向柱', keycap='方形键帽', cartridge='弹性盒')
PLACEMENTS = dict(shell=(-55, -35), base=(0, -35), cartridge=(55, -35), plunger=(-45, 25), keycap=(0, 25))

def rect(w, d, r=0):
    if not r:
        return mf.CrossSection.square((w, d), center=True)
    return mf.CrossSection.square((w - 2 * r, d - 2 * r), center=True).offset(r, circular_segments=RESOLUTION['rounded_profile_segments'])

def box(w, d, h, x=0, y=0, z=0, r=0):
    return rect(w, d, r).extrude(h).translate((x, y, z))

def prism_xz(points, y0, y1):
    return mf.CrossSection([points]).extrude(y1 - y0).rotate((90, 0, 0)).translate((0, y1, 0))

def make_parts():
    """Base seats are wall-supported columns; there are no elevated bridges.
Two different-width keys prevent rotation of the cartridge.
Wall-connected ledges retain the plunger at rest.
Bottoming occurs at the keycap underside against the thick roof.
Blind screw bosses seat directly on the base floor.
Effective span along Y: -17 to +13; opposite arm rotated 180°.
Rigid strike contact touches relaxed shoe from inside, not its beam.
Flat flange on bed; raised contact pads keep the arms below it."""
    base = box(P['body'], P['body'], 2.4, r=3)
    rim = rect(39, 39, 1) - rect(34, 34, 0.5)
    base += rim.extrude(3.8).translate((0, 0, 2.4))
    for side in (-1, 1):
        base -= box(7, 3, 0.25, x=side * 5, y=-side * 18, z=5.95)
    # Lower the old zero-clearance rim beneath both free ends. The new
    # wall-connected shelves carry only the shoe/tail, never the bending span.
    for side in (-1, 1):
        base -= box(5.4, 8.6, .3, x=side*P['shelf_x'], y=14.2, z=6.0)
        base += box(4.8, 8.2, 3.6, x=side*P['shelf_x'], y=14.2, z=2.4)
        # Keep the side-shifted main beam clear even at the shelf sink limit.
        base -= box(1.0, 25.6, .5, x=side*P['beam_relief_x'], y=-2.5, z=5.8)
    keys = [(-19.8, 0, 2, 6), (0, 17.5, 4, 2)]
    for x, y, w, d in keys:
        base += box(w, d, 7, x=x, y=y, z=2.4)
    for side in (-1, 1):
        post = prism_xz([(-3.8, 2.4), (3.8, 2.4),
                         (3.8, P['snap_start']), (4.2, P['snap_peak']),
                         (3.8, P['snap_top']), (-3.8, P['snap_top']),
                         (-4.2, P['snap_peak']), (-3.8, P['snap_start'])], -1, 1)
        base += post.rotate((0, 0, 90)).translate((side*P['snap_x'], -11, 0))
    shell = box(P['body'], P['body'], 16, z=2.4, r=3) - box(40, 40, 16.1 - P['roof_thickness'], z=2.3, r=1)
    for x, y, w, d in keys:
        shell -= box(w + 0.5, d + 0.5, 8, x=x, y=y, z=2.3)
    shell += box(18.5, 32.5, 5.25, z=11.25, r=0.6)
    guide = rect(14, 28, P['guide_radius']).offset(P['guide_clearance'], circular_segments=RESOLUTION['rounded_profile_segments']).simplify(1e-5)
    shell -= guide.extrude(10).translate((0, 0, 11.24))
    # Offset both profiles: the 45 degree mouth relief also follows the corners.
    c = P['guide_chamfer']
    mouth = guide.offset(c, circular_segments=RESOLUTION['rounded_profile_segments']).simplify(1e-5)
    for z, lower, upper in ((11.25, mouth, guide), (18.4-c, guide, mouth)):
        shell -= (lower.extrude(.001).translate((0,0,z)) + upper.extrude(.001).translate((0,0,z+c))).hull()
    for side in (-1, 1):
        # One blind-slot cutter avoids coincident seams at the transition.
        slot = prism_xz([(-4.2,2.3),(4.2,2.3),(4,2.6),(4,12.8),
                         (4.4,13.2),(4.4,14.8),(-4.4,14.8),
                         (-4.4,13.2),(-4,12.8),(-4,2.6)],-1.25,1.25)
        shell -= slot.rotate((0,0,90)).translate((side*P['snap_x'],-11,0))
    for x, y in P['screw_centers']:
        # Wall-connected blind bosses bear on the rigid floor, never the cartridge.
        boss = mf.Manifold.cylinder(16, P['boss_radius'], P['boss_radius'], RESOLUTION['cylinder_segments']).translate((x,y,2.4))
        boss ^= box(P['body'],P['body'],16,z=2.4,r=3)
        shell += boss
        shell -= mf.Manifold.cylinder(9.6,P['pilot_radius'],P['pilot_radius'],RESOLUTION['cylinder_segments']).translate((x,y,2.3))
        relief = mf.Manifold.cylinder(4, P['boss_radius']+.25,P['boss_radius']+.25,RESOLUTION['cylinder_segments']).translate((x,y,2.4))
        base -= relief
        base -= mf.Manifold.cylinder(2.6,P['clearance_radius'],P['clearance_radius'],RESOLUTION['cylinder_segments']).translate((x,y,-.1))
        # Overlap cutters slightly to avoid coincident faces in float32 STL.
        base -= mf.Manifold.cylinder(.3,P['countersink_radius'],P['countersink_radius'],RESOLUTION['cylinder_segments']).translate((x,y,-.1))
        base -= mf.Manifold.cylinder(1.11,P['countersink_radius']+.01,P['clearance_radius'],RESOLUTION['cylinder_segments']).translate((x,y,.19))
    frame = rect(39, 39, 1) - rect(2*P['window_edge'], 2*(P['frame_half']-P['end_wall']), 0.5)
    for x, y, w, d in keys:
        frame -= rect(w + 0.2, d + 0.2).translate((x, y))
    for side in (-1, 1):
        frame -= rect(2.5, 8.5).translate((side * P['snap_x'], -11))
    for side in (-1, 1):
        frame -= rect(2.5, 2.1).translate((side * P['strike_x'], 17.2))
    for x, y in P['screw_centers']:
        frame -= mf.CrossSection.circle(P['boss_radius']+.35,RESOLUTION['cylinder_segments']).translate((x,y))
    cartridge = frame.extrude(3.2).translate((0, 0, 6.2))
    for side in (-1, 1):
        beam = rect(P['return_width'], P['return_length']+2, 0.5).translate((5, -2))
        beam += mf.CrossSection.circle(P['return_width']/2, 32).translate((5, P['return_root_y']))
        arm = beam.extrude(P['return_thickness']).translate((0, 0, P['frame_bottom']))
        arm += box(P['return_width'], P['return_pad_depth'], P['frame_thickness'], x=5, y=P['return_pad_y'], z=P['frame_bottom']+P['return_thickness'], r=0.3)
        cartridge += arm if side == 1 else arm.rotate((0, 0, 180))
        click = rect(P['click_width'], P['click_length']+1.6, 0.3).translate((P['click_x'], -1.2))
        # A 1.6 mm root radius fills the centre with 0.50 mm first-layer paths.
        click += mf.CrossSection.circle(P['click_root_radius'], 32).translate((P['click_x'], -17))
        click += rect(2.6, 4.4, 0.4).translate((P['click_x'], 13))
        click += rect(2.4, 2.8, 0.2).translate((P['click_x'], 15.6))
        part = click.extrude(P['click_thickness']).translate((0, 0, P['frame_bottom']))
        part += box(1.2, 3.8, P['contact_height'], x=P['click_x']-1.2, y=13, z=P['contact_bottom'], r=0.2)
        cartridge += part if side == 1 else part.mirror((1, 0, 0))
        base += box(2, 1.6, 7, x=side * P['strike_x'], y=17.2, z=2.4)
    stem = rect(14, 28, P['guide_radius'])
    plunger = box(28, 32, 1, z=10.25, r=0.5) + rect(14, 28, P['guide_radius']).extrude(8.35).translate((0, 0, 10.25))
    for side in (-1, 1):
        plunger -= box(P['click_shift']+1, 6, 1.02, x=side*(P['plate_edge']+(P['click_shift']+1)/2), y=13, z=10.24)
        # Inward root fillets also enter the rear flange corners during travel.
        plunger -= box(P['click_shift']+1, 1.1, 1.02, x=side*(P['plate_edge']+(P['click_shift']+1)/2), y=-15.45, z=10.24)
    # Four longitudinal reliefs; 3 mm lands include the rounded face ends.
    for width, depth, angle in ((28,14,0),(14,28,90)):
        half = depth/2
        for side in (-1,1):
            cutter = prism_xz([(half,11.26),(half-P['guide_relief'],11.26+P['guide_ramp']),
                               (half-P['guide_relief'],18.59-P['guide_ramp']),(half,18.59),
                               (half+1,18.59),(half+1,11.26)][::-1],
                              -(width/2-P['guide_land']), width/2-P['guide_land'])
            plunger -= cutter.rotate((0,0,angle + (180 if side < 0 else 0)))
    plunger += stem.extrude(2.8, scale_top=(1, 14.4 / 28)).translate((0, 0, 18.6))
    plunger += rect(14, 14, 0.5).extrude(2.8, scale_top=(13.8 / 14, 13.8 / 14)).translate((0, 0, 21.4))
    for side in (-1, 1):
        z = P['cam_bottom']
        peak = z + P['cam_push_height']
        release = peak + P['cam_peak_height']
        top = release + P['cam_release_height']
        cam = prism_xz([(P['cam_root'],z),(P['cam_entry'],z),
                        (P['cam_peak'],peak),(P['cam_peak'],release),
                        (P['cam_exit'],top),(P['cam_root'],top)],11,15)
        plunger += cam if side == 1 else cam.mirror((1,0,0))
    cap = box(P['key'], P['key'], 4, z=21.4, r=2) - box(13.95, 13.95, 3.1, z=21.3, r=0.4)
    return dict(shell=shell, base=base, plunger=plunger, keycap=cap, cartridge=cartridge)

def mesh_of(solid):
    raw = solid.to_mesh()
    m = trimesh.Trimesh(np.asarray(raw.vert_properties)[:, :3], np.asarray(raw.tri_verts), process=True)
    m.remove_unreferenced_vertices()
    assert m.is_watertight and m.is_winding_consistent
    return m

def printing(solid, name):
    """Orient each print part on the bed."""
    m = mesh_of(solid)
    rotation = 180 if name in ('shell', 'keycap') else 0
    matrix = trimesh.transformations.rotation_matrix(np.radians(rotation), [1, 0, 0])
    m.apply_transform(matrix)
    shift = trimesh.transformations.translation_matrix([0, 0, -m.bounds[0, 2]])
    m.apply_transform(shift)
    return (m, shift @ matrix)

