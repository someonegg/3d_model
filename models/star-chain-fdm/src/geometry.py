"""Rounded toy geometry. Millimetres, Z up; all moving parts print separately."""
import json
import math
from pathlib import Path

import manifold3d as mf
import numpy as np
import trimesh

HERE = Path(__file__).resolve().parents[1]


def parameters():
    p = json.loads((HERE / 'parameters.json').read_text())
    assert p['links'] == 6 and p['star_span_mm'] == 56
    assert 0.2 <= p['clearance_per_side_mm'] <= 0.4
    assert p['closed_pivot_x_mm'] - p['stroke_mm'] == p['disc_radius_mm'] + p['capture_wall_mm']
    assert p['head_lower_height_mm'] >= 2 and p['capture_wall_mm'] >= 1.2
    assert p['detent_interference_mm'] <= p['detent_depth_mm'] - .15
    assert 0 < p['detent_root_diameter_mm'] < p['flag_width_mm']
    assert 0 < p['detent_lip_depth_mm'] < p['detent_interference_mm']
    assert p['detent_recess_clearance_mm'] > 0
    c = p['clearance_per_side_mm']
    assert p['anchor_wall_minimum_mm'] >= 2.4
    assert p['anchor_end_x_mm'] - p['anchor_start_x_mm'] >= 4
    assert p['anchor_start_x_mm'] - c - (p['closed_pivot_x_mm'] + p['disc_radius_mm'] + c) >= p['anchor_wall_minimum_mm'] - 1e-6
    assert p['link_length_mm'] - p['anchor_end_x_mm'] - c >= p['anchor_wall_minimum_mm'] - 1e-6
    assert p['anchor_width_mm'] > p['neck_width_mm'] + 2 * c + 2 * p['capture_wall_mm']
    assert 0 < p['anchor_corner_radius_mm'] < (p['anchor_end_x_mm'] - p['anchor_start_x_mm']) / 2
    assert 0 < p['anchor_neck_fillet_mm'] < (p['anchor_width_mm'] - p['neck_width_mm']) / 2
    assert 0.1 <= p['locator_clearance_mm'] <= .2
    assert p['locator_engagement_mm'] < p['stroke_mm']
    assert p['base_height_mm'] - p['locator_vertical_clearance_mm'] - p['locator_bottom_mm'] - p['locator_engagement_mm'] >= 2.4 - 1e-6
    assert p['pin_x_mm'] - 1.9 - p['locator_engagement_mm'] - p['locator_clearance_mm'] >= .8
    return p


def neck_z(p):
    return p['slider_z_mm'] + p['head_lower_height_mm']


def slider_top(p):
    return neck_z(p) + p['slider_thickness_mm']


def flag_region(p):
    return box(p['flag_start_x_mm'], p['flag_end_x_mm'],
               -p['flag_width_mm'] / 2, p['flag_width_mm'] / 2,
               p['slider_z_mm'], p['body_height_mm'] + 1)


def rect(x0, x1, y0, y1):
    return mf.CrossSection.square((x1 - x0, y1 - y0)).translate((x0, y0))


def circle(x, y, radius):
    return mf.CrossSection.circle(radius, 64).translate((x, y))


def anchor_section(p, clearance=0):
    r = p['anchor_corner_radius_mm']
    half = p['anchor_width_mm'] / 2
    return rect(p['anchor_start_x_mm'] + r, p['anchor_end_x_mm'] - r,
                -half + r, half - r).offset(r + clearance, circular_segments=32)


def neck_section(p):
    end, half, radius = p['anchor_end_x_mm'], p['neck_width_mm'] / 2, p['anchor_neck_fillet_mm']
    result = rect(end-.3, p['link_length_mm'] + p['closed_pivot_x_mm'], -half, half)
    # Concave quarter circles spread the neck load into the broad solid head.
    arc = [(end+radius+radius*math.cos(a), half+radius+radius*math.sin(a))
           for a in np.linspace(-math.pi/2, -math.pi, 17)]
    points = [(end-.3, half-.1), (end+radius, half-.1), *arc, (end-.3, half+radius)]
    for sign in (-1, 1):
        mirrored = [(x, sign*y) for x, y in points]
        # Mirroring reverses winding; both added contours must remain positive.
        result += mf.CrossSection([mirrored if sign > 0 else mirrored[::-1]])
    return result


def terminal_pivot_x(p):
    return p['link_length_mm'] + 5


def straight_length(p, stroke=0):
    return p['links'] * p['link_length_mm'] + 56 + (p['links']-1) * stroke


def slab(section, z0, z1):
    return section.extrude(z1 - z0).translate((0, 0, z0))


def box(x0, x1, y0, y1, z0, z1):
    return slab(rect(x0, x1, y0, y1), z0, z1)


def cylinder(x, y, radius, z0, z1):
    return slab(circle(x, y, radius), z0, z1)


def mesh(solid):
    if solid.status() != mf.Error.NoError or solid.is_empty():
        raise ValueError('invalid solid')
    raw = solid.to_mesh()
    return trimesh.Trimesh(np.asarray(raw.vert_properties)[:, :3],
                           np.asarray(raw.tri_verts), process=True)


def solid(m):
    result = mf.Manifold(mf.Mesh(np.asarray(m.vertices, dtype=np.float32),
                                np.asarray(m.faces, dtype=np.uint32)))
    if result.status() != mf.Error.NoError or result.is_empty():
        raise ValueError('invalid mesh solid')
    return result


def outline(p):
    length, half = p['link_length_mm'], p['link_width_mm'] / 2
    return rect(1, length - 1, -half + 1, half - 1).offset(1, circular_segments=32)


def pocket(p, clearance, upper=False):
    # The lower disc runs behind a full end wall. Only the raised neck exits
    # the upper slot, whose flare is the actual +/-35 degree swept envelope.
    radius = p['disc_radius_mm'] + clearance
    pivot = p['closed_pivot_x_mm'] - p['stroke_mm']
    section = (circle(pivot, 0, radius) +
               rect(pivot, p['closed_pivot_x_mm'], -radius, radius) +
               circle(p['closed_pivot_x_mm'], 0, radius))
    if not upper:
        return section ^ rect(p['capture_wall_mm'], p['link_length_mm'] + radius, -radius, radius)
    angle = math.radians(p['joint_angle_deg'])
    half = p['neck_width_mm'] / 2
    # On x <= pivot, the extreme neck edge is y =
    # (half + (pivot - x) * sin(angle)) / cos(angle). A single wedge avoids
    # coincident facets from unioning dozens of nearly identical rotations.
    end_half = half / math.cos(angle)
    mouth_half = (half + (pivot + 1) * math.sin(angle)) / math.cos(angle)
    sweep = mf.CrossSection([[(-1, -mouth_half), (pivot, -end_half),
                             (pivot, end_half), (-1, mouth_half)]])
    return section + sweep.offset(clearance, circular_segments=16)


def locator_solid(p, sign, female=False):
    c = p['locator_clearance_mm'] if female else 0
    v = p['locator_vertical_clearance_mm']
    length, half, y = p['locator_engagement_mm'], p['locator_width_mm'] / 2, sign * 6.8
    section = mf.CrossSection([[(-.8, y-half), (length-.8, y-half),
        (length, y-half+.8), (length, y+half-.8), (length-.8, y+half), (-.8, y+half)]])
    if female:
        section = section.offset(c, circular_segments=16)
    bottom = p['locator_bottom_mm'] - (v if female else 0)
    top = p['base_height_mm'] + .1 if female else p['base_height_mm'] - v
    end = length + c + .1
    ramp = mf.CrossSection([[(-1, bottom), (0, bottom), (end, bottom+end),
                                    (end, top), (-1, top)]])
    ramp = ramp.extrude(24).rotate((90, 0, 0)).translate((0, 12, 0))
    result = slab(section, bottom, top) ^ ramp
    return result if female else result.translate((p['link_length_mm'], 0, 0))


def base(p, clearance=None, terminal=False):
    c = p['clearance_per_side_mm'] if clearance is None else clearance
    shape = outline(p)
    # 0.2 mm inset foot avoids first-layer spread at the mating edges.
    result = slab(shape.offset(-.2), 0, .2) + slab(shape, .2, p['base_height_mm'])
    result -= slab(pocket(p, c), p['floor_mm'], p['base_height_mm'] + .1)
    result -= slab(pocket(p, c, upper=True), neck_z(p) - .3, p['base_height_mm'] + .1)
    for sign in (-1, 1):
        result -= locator_solid(p, sign, female=True)
        if not terminal:
            result += locator_solid(p, sign)
    if terminal:
        pivot = terminal_pivot_x(p)
        result -= box(18, p['link_length_mm']+.1, -5.6, 5.6, p['floor_mm'], p['base_height_mm'] + .1)
        fork = circle(pivot, 0, 8) + rect(p['link_length_mm']-2, pivot, -8, 8)
        result += slab(fork, 0, 1.6)
        result -= slab(fork, 7.2, p['base_height_mm'] + .1)
        # Circular lug and two posts produce an actual +/-40 degree hard stop.
        stop_angle = math.radians(p['star_angle_deg']) + math.asin(2.04 / 7)
        for sign in (-1, 1):
            result += cylinder(pivot - 7 * math.cos(stop_angle),
                               sign * 7 * math.sin(stop_angle), 1, 1.6, 7.2)
        result -= cylinder(pivot, 0, 1.6, -.1, p['body_height_mm'] + .1)
        result -= cylinder(pivot, 0, 1.9, -.1, .8)
    else:
        # Solid T-head seats from above. Independent end walls capture its lower
        # shoulder; only the raised neck passes through the rear upper opening.
        result -= slab(anchor_section(p, c),
                       p['floor_mm'], p['base_height_mm'] + .1)
        result -= slab(neck_section(p).offset(c, circular_segments=32),
                       neck_z(p) - .3, p['base_height_mm'] + .1)
    for sign in (-1, 1):
        result -= cylinder(p['pin_x_mm'], sign * 6.8, 1.6, -.1, p['base_height_mm'] + .1)
        result -= cylinder(p['pin_x_mm'], sign * 6.8, 1.9, -.1, .8)
    return result


def lid(p, terminal=False):
    bottom_z, top_z = p['base_height_mm'], p['body_height_mm']
    result = slab(outline(p), bottom_z, top_z)
    start, end = p['flag_start_x_mm'], p['flag_end_x_mm']
    half, slit = p['flag_width_mm'] / 2, p['flag_slit_mm']
    for y0, y1 in ((-half - slit, -half), (half, half + slit)):
        result -= box(start, end + slit, y0, y1, bottom_z - .1, top_z + .1)
    result -= box(end, end + slit, -half - slit, half + slit, bottom_z - .1, top_z + .1)
    result -= box(start, end, -half, half, bottom_z - .1, top_z - p['flag_thickness_mm'])
    x = p['closed_pivot_x_mm']
    bottom = slider_top(p) - p['detent_interference_mm']
    root = top_z - p['flag_thickness_mm']
    height = root - bottom
    # Ellipsoidal cap: broad root, rounded tip, no narrow cylindrical stem.
    heights = np.linspace(-.05, height, 65)
    profile = [(0., -.05)] + [(detent_profile_radius(h, p), float(h)) for h in heights]
    result += mf.Manifold.revolve(mf.CrossSection([profile]), 64).rotate((180, 0, 0)).translate((x, 0, root))
    if terminal:
        pivot = terminal_pivot_x(p)
        result += slab(circle(pivot, 0, 8) + rect(p['link_length_mm']-2, pivot, -8, 8), 7.2, p['body_height_mm'])
        result -= cylinder(pivot, 0, 1.6, 7, top_z + .1)
    for sign in (-1, 1):
        result -= cylinder(p['pin_x_mm'], sign * 6.8, 1.6, bottom_z - .1, top_z + .1)
    return result


def detent_profile_radius(depth, p):
    height = p['body_height_mm'] - p['flag_thickness_mm'] - slider_top(p) + p['detent_interference_mm']
    offset = .8
    axis = height + offset
    return p['detent_root_diameter_mm'] / 2 * math.sqrt(max(0.,
        (axis ** 2 - (depth + offset) ** 2) / (axis ** 2 - offset ** 2)))


def detent_recess_profile(p):
    """Clearanced ellipsoidal bowl with a tangent-continuous rolled mouth.

    Coordinates are (radius, depth below the slider top). The deeper bowl leaves
    the seated bump clear of the floor; the Bezier lip joins the flat top smoothly.
    """
    depth, lip = p['detent_depth_mm'], p['detent_lip_depth_mm']
    seated_depth = p['body_height_mm'] - p['flag_thickness_mm'] - slider_top(p)
    radius = detent_profile_radius(seated_depth, p) + p['detent_recess_clearance_mm']
    offset = depth - p['detent_interference_mm']
    axis = depth + offset

    def bowl(d):
        return radius * math.sqrt(max(0., (axis ** 2 - (d + offset) ** 2) /
                                     (axis ** 2 - offset ** 2)))

    end_radius = bowl(lip)
    slope = -radius ** 2 * (lip + offset) / ((axis ** 2 - offset ** 2) * end_radius)
    controls = np.array([[radius + lip, 0], [radius, 0],
                         [end_radius - slope * lip / 3, 2 * lip / 3], [end_radius, lip]])
    profile = []
    for t in np.linspace(0, 1, 17):
        point = ((1-t) ** 3 * controls[0] + 3 * (1-t) ** 2 * t * controls[1] +
                 3 * (1-t) * t ** 2 * controls[2] + t ** 3 * controls[3])
        profile.append(tuple(point))
    profile += [(bowl(d), float(d)) for d in np.linspace(lip, depth, 65)[1:]]
    return profile


def detent_recess(p, x):
    profile = detent_recess_profile(p)
    polygon = [(0, -.1), (profile[0][0], -.1), *profile]
    return mf.Manifold.revolve(mf.CrossSection([polygon]), 64).rotate((180, 0, 0)).translate((x, 0, slider_top(p)))


def slider(p):
    cx = p['link_length_mm'] + p['closed_pivot_x_mm']
    anchor = anchor_section(p)
    head = circle(cx, 0, p['disc_radius_mm'])
    neck = neck_section(p)
    result = slab(anchor + head, p['slider_z_mm'], slider_top(p))
    result += slab(neck, neck_z(p), slider_top(p))
    result -= detent_recess(p, cx)
    return result


def lock_pin(p):
    # Print the unchanged head down; straight shaft has no retention feature.
    return (cylinder(0, 0, 2.5, 0, 1.2) +
            cylinder(0, 0, 1.48, 1.19, 1.2 + p['pin_shaft_length_mm']))


def star(p):
    r = p['star_span_mm'] / 2 - p['star_tip_radius_mm']
    section = mf.CrossSection([[(r, 0), (8, 8), (0, r), (-8, 8),
        (-r, 0), (-8, -8), (0, -r), (8, -8)]]).offset(p['star_tip_radius_mm'], circular_segments=64)
    # Local hinge at (-23, 0). Entire outline has a 3 mm rounded perimeter.
    section += circle(-23, 0, 5)
    section += (circle(-27, 0, 1) + circle(-30, 0, 1)).hull()
    result = slab(section, 1.9, 1.9 + p['star_thickness_mm'])
    result -= cylinder(-23, 0, 1.9, 1, 8)
    return result


def parts(p, clearance=None):
    return {'link-base': base(p, clearance), 'terminal-base': base(p, clearance, True),
            'link-lid': lid(p), 'terminal-lid': lid(p, True),
            'slider': slider(p), 'lock-pin': lock_pin(p), 'star-head': star(p)}


def print_transform(name, p):
    transform = np.eye(4)
    if name.endswith('lid'):
        transform[1, 1] = -1
        transform[2, 2] = -1
        transform[2, 3] = p['body_height_mm']
    elif name == 'slider':
        # Raised neck and both thicker ends all start on the bed; no bridge
        # between the two ends is needed. The detent recess faces the bed.
        transform[1, 1] = -1
        transform[2, 2] = -1
        transform[2, 3] = slider_top(p)
    elif name == 'star-head':
        transform[2, 3] = -p['slider_z_mm']
    return transform


def pose(p, stroke=0., angles=None, star_angle=0.):
    """Local part transforms for a chain rooted at link zero."""
    angles = [0.] * 5 if angles is None else angles
    rows = []
    frame = np.eye(4)
    pin_flip = np.diag([1., -1., -1., 1.])
    pin_flip[2, 3] = p['body_height_mm'] + 1.2
    for index in range(p['links']):
        terminal = index == p['links'] - 1
        for name in ('terminal-base', 'terminal-lid') if terminal else ('link-base', 'link-lid', 'slider'):
            rows.append((f'{name}-{index + 1}', name, frame.copy()))
        for sign in (-1, 1):
            offset = np.eye(4)
            offset[:3, 3] = (p['pin_x_mm'], sign * 6.8, 0)
            rows.append((f'lock-pin-{index + 1}-{sign}', 'lock-pin', frame @ offset @ pin_flip))
        if terminal:
            angle = math.radians(star_angle)
            rotation = trimesh.transformations.rotation_matrix(angle, (0, 0, 1))
            pivot = trimesh.transformations.translation_matrix((terminal_pivot_x(p), 0, 0))
            center = trimesh.transformations.translation_matrix((23, 0, 0))
            rows.append(('star-head', 'star-head', frame @ pivot @ rotation @ center))
            rows.append(('star-pivot-pin', 'lock-pin', frame @ pivot @ pin_flip))
        else:
            rotation = trimesh.transformations.rotation_matrix(math.radians(angles[index]), (0, 0, 1))
            pivot = trimesh.transformations.translation_matrix((p['link_length_mm'] + p['closed_pivot_x_mm'], 0, 0))
            inlet = trimesh.transformations.translation_matrix((-(p['closed_pivot_x_mm'] - stroke), 0, 0))
            frame = frame @ pivot @ rotation @ inlet
    return rows
