"""Shared archive geometry, G-code paths and deposited material envelopes."""
import math
import xml.etree.ElementTree as ET
import numpy as np
import trimesh
import manifold3d as mf
from scipy.spatial import cKDTree

def check_archive_geometry(archive, source, *, tolerance=2e-5):
    """Collect mode cannot attach a stale slice to a newer STL."""
    meshes = []
    for name in archive.namelist():
        if not name.endswith('.model'):
            continue
        for mesh in ET.fromstring(archive.read(name)).findall('.//{*}mesh'):
            vertices = [[float(v.attrib[k]) for k in ('x', 'y', 'z')] for v in mesh.findall('./{*}vertices/{*}vertex')]
            faces = [[int(f.attrib[k]) for k in ('v1', 'v2', 'v3')] for f in mesh.findall('./{*}triangles/{*}triangle')]
            meshes.append(trimesh.Trimesh(vertices, faces, process=False))
    actual = trimesh.util.concatenate(meshes)
    expected = trimesh.load(source, force='mesh')
    assert len(actual.faces) == len(expected.faces), 'stale sliced mesh topology'
    for m in (actual, expected):
        m.apply_translation(-m.bounds.mean(axis=0))
    np.testing.assert_allclose(actual.extents, expected.extents, atol=tolerance)
    for a, b in ((actual, expected), (expected, actual)):
        distances, _ = cKDTree(a.triangles_center).query(b.triangles_center)
        assert max(distances) < tolerance, 'sliced geometry differs from current STL'

def extrusion_segments(gcode, dimensions=False, *, with_width=False, require_layer=False):
    position = np.zeros(4)
    relative_e, relative_xyz, layer, feature = True, False, 0., ''
    width = height = None
    paths = []
    for line in gcode.splitlines():
        if line.startswith('; Z_HEIGHT:'):
            layer = round(float(line.split(':')[1]), 3)
        if line.startswith('; LAYER_HEIGHT:'):
            height = float(line.split(':', 1)[1])
        if line.startswith('; FEATURE:'):
            feature = line.split(':', 1)[1].strip()
        if line.startswith('; LINE_WIDTH:'):
            width = float(line.split(':', 1)[1])
        words = line.split(';', 1)[0].split()
        if not words:
            continue
        if words[0] in ('M82', 'M83'):
            relative_e = words[0] == 'M83'
        if words[0] in ('G90', 'G91'):
            relative_xyz = words[0] == 'G91'
        data = {'XYZE'.index(word[0]): float(word[1:]) for word in words[1:]
                if word[0] in 'XYZE' and len(word) > 1}
        if words[0] == 'G92':
            for axis, value in data.items():
                position[axis] = value
        if words[0] not in ('G0', 'G1', 'G2', 'G3'):
            continue
        old = position.copy()
        amount = data.get(3, 0.) if relative_e else data.get(3, old[3]) - old[3]
        for axis, value in data.items():
            relative = relative_e if axis == 3 else relative_xyz
            position[axis] = old[axis] + value if relative else value
        if (require_layer and layer <= 0) or amount <= 0 or (not any(axis in data for axis in (0, 1)) and words[0] not in ('G2', 'G3')):
            continue
        if dimensions:
            assert width is not None and height is not None and width > 0 and height > 0, 'missing actual extrusion dimensions'
        z = layer if layer > 0 else round(float(position[2]), 3)
        if words[0] in ('G2', 'G3'):
            offsets = {word[0]: float(word[1:]) for word in words[1:] if word[0] in 'IJPR'}
            if 'I' in offsets or 'J' in offsets:
                centre = old[:2] + [offsets.get('I', 0.), offsets.get('J', 0.)]
            else:
                assert 'R' in offsets, 'unsupported extruding arc without centre or radius'
                chord = position[:2] - old[:2]
                length = np.linalg.norm(chord)
                radius = abs(offsets['R'])
                assert length > 0 and length <= 2 * radius + 1e-8, 'invalid arc radius'
                midpoint = (old[:2] + position[:2]) / 2
                normal = np.array([-chord[1], chord[0]]) / length
                distance = math.sqrt(max(0., radius**2 - length**2 / 4))
                direction = 1 if words[0] == 'G3' else -1
                # Positive R selects the minor arc; negative R the major arc.
                centre = midpoint + normal * distance * direction * (1 if offsets['R'] >= 0 else -1)
            radius = np.linalg.norm(old[:2] - centre)
            assert radius > 0, 'zero-radius extruding arc'
            start = math.atan2(old[1] - centre[1], old[0] - centre[0])
            end = math.atan2(position[1] - centre[1], position[0] - centre[0])
            direction = 1 if words[0] == 'G3' else -1
            sweep = direction * ((direction * (end - start)) % (2 * math.pi))
            if abs(sweep) < 1e-8:
                sweep = direction * 2 * math.pi
            sweep += direction * 2 * math.pi * (offsets.get('P', 1) - 1)
            # Approximate arc paths to <=0.005 mm sagitta and 0.05 mm length.
            max_angle = 2 * math.acos(max(-1., 1 - .005 / radius))
            count = max(1, math.ceil(abs(sweep) / max_angle), math.ceil(abs(sweep) * radius / .05))
            angles = np.linspace(start, start + sweep, count + 1)
            radii = np.linspace(radius, np.linalg.norm(position[:2] - centre), count + 1)
            points = centre + np.column_stack((np.cos(angles), np.sin(angles))) * radii[:, None]
            points[0], points[-1] = old[:2], position[:2]
            paths.extend((z, a, b, feature, width, height) if dimensions else ((z, a, b, feature, width) if with_width else (z, a, b, feature))
                         for a, b in zip(points, points[1:]))
        elif 0 in data or 1 in data:
            path = (z, old[:2], position[:2].copy(), feature)
            paths.append((*path, width, height) if dimensions else ((*path, width) if with_width else path))
    return paths


def bead_envelope(segments):
    """Union deposited capsules at their measured widths and layer extents.

    Circular caps are circumscribed (32 sides) so the polygon does not hide a
    collision by shrinking the stated bead radius. This is a material envelope,
    not a melt-flow or dimensional-error prediction.
    """
    layers = {}
    for z,a,b,feature,width,height in segments:
        delta=b-a
        if np.linalg.norm(delta)<1e-9:
            continue
        angle=np.arctan2(delta[1],delta[0])
        # Tangent polygon: preserve the exact straight-side width. Uniform
        # radial inflation would artificially widen every straight bead by
        # ~.001 mm, causing false failures at the .50 mm travel boundary.
        theta=np.r_[-np.pi/2, np.arange(16)*np.pi/16-np.pi/2+np.pi/32, np.pi/2]
        radius=np.r_[width/2,np.full(16,width/2/np.cos(np.pi/32)),width/2]
        theta+=angle
        cap=radius[:,None]*np.column_stack((np.cos(theta),np.sin(theta)))
        polygon=np.vstack((b+cap,a-cap))
        layers.setdefault((z,height),[]).append(mf.CrossSection([polygon.tolist()]))
    solids=[]
    for (z,height),sections in layers.items():
        section=mf.CrossSection.batch_boolean(sections,mf.OpType.Add)
        solids.append(section.extrude(height).translate((0,0,z-height)))
    return mf.Manifold.batch_boolean(solids,mf.OpType.Add) if solids else mf.Manifold()


def require_material(solid, probe, label):
    assert probe.volume()>0 and (probe-solid).volume()<1e-5, f'missing deposited material: {label}'


def require_clear(a,b,label):
    assert (a^b).volume()<.003, f'deposited material interference: {label}'


def deposited_region(segments, row, shift, mask):
    """Select beads touching an assembly-space mask, including their half width."""
    inv = np.linalg.inv(row['assembly_to_print'])
    boxes = [np.array(region.bounding_box()).reshape(2,3) for region in mask.decompose()]
    selected = []
    for z, a, b, feature, width, height in segments:
        ends = np.array([(inv @ [*(point-np.array(row['plate_xy'])-shift), z, 1])[:3]
                         for point in (a, b)])
        bead_lo = ends[:, :2].min(axis=0)-width/2
        bead_hi = ends[:, :2].max(axis=0)+width/2
        if any(np.all(bead_lo <= hi[:2]) and np.all(bead_hi >= lo[:2]) for lo,hi in boxes):
            selected.append((z, a, b, feature, width, height))
    transform = inv.copy()
    transform[:2, 3] -= inv[:2, :2] @ (np.array(row['plate_xy'])+shift)
    return bead_envelope(selected).transform(transform[:3, :]) ^ mask


