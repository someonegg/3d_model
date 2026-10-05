"""Coin dimensions, sampled surfaces and printable topology."""
from pathlib import Path
import json
import numpy as np

SOURCE = Path(__file__).resolve().parents[1]
P = json.loads((SOURCE / 'parameters.json').read_text())
DIAMETER, BASE, RELIEF, RIM = (P[k] for k in ('diameter_mm', 'base_mm', 'relief_mm', 'rim_mm'))
RADIUS = DIAMETER / 2
RINGS, SECTORS = P['rings'], P['sectors']


def heights(x, y, side, fields):
    # Pixel centers/radius measured from the 1000 x 500 reference photograph.
    cx, cy, radius = (248.5, 249.0, 230.0) if side == 'obverse' else (748.5, 249.0, 230.0)
    px = np.clip(cx + x / RADIUS * radius, 0, fields[side].shape[1] - 2)
    py = np.clip(cy - y / RADIUS * radius, 0, fields[side].shape[0] - 2)
    ix, iy = px.astype(int), py.astype(int)
    fx, fy = px - ix, py - iy
    data = fields[side]
    sampled = ((1-fx)*(1-fy)*data[iy, ix] + fx*(1-fy)*data[iy, ix+1]
               + (1-fx)*fy*data[iy+1, ix] + fx*fy*data[iy+1, ix+1])
    h = sampled
    radius_mm = np.hypot(x, y)
    # Replace photographic rim with a clean manufactured annulus.
    blend = np.clip((radius_mm - (RADIUS - 1.9)) / 0.5, 0, 1)
    rim = RIM - 0.20 * np.clip((radius_mm - (RADIUS - 0.3)) / 0.3, 0, 1)
    return (1-blend)*h + blend*rim


def topology():
    theta = np.arange(SECTORS) * 2*np.pi/SECTORS
    radius = np.arange(1, RINGS+1) * (DIAMETER/2/RINGS)
    xy = np.vstack(([0, 0], np.column_stack((
        (radius[:, None]*np.cos(theta)).ravel(),
        (radius[:, None]*np.sin(theta)).ravel()))))
    j = np.arange(SECTORS)
    triangles = [np.column_stack((np.zeros(SECTORS, int), 1+j, 1+(j+1)%SECTORS))]
    for ring in range(RINGS-1):
        a, b = 1+ring*SECTORS+j, 1+ring*SECTORS+(j+1)%SECTORS
        c, d = a+SECTORS, b+SECTORS
        triangles.extend((np.column_stack((a,c,d)), np.column_stack((a,d,b))))
    TOP = np.vstack(triangles)
    EDGE = np.arange(1+(RINGS-1)*SECTORS, 1+RINGS*SECTORS)
    return xy, TOP, EDGE


def save_mesh(out, fields, topology_data, name, front, back=None):
    xy, TOP, EDGE = topology_data
    j = np.arange(SECTORS)
    n = len(xy)
    top = np.column_stack((xy, BASE + heights(xy[:,0], xy[:,1], front, fields)))
    if back:
        # A 180-degree flip around X reveals the reverse upright (coin alignment).
        lower = np.column_stack((xy, -BASE-heights(xy[:,0], -xy[:,1], back, fields)))
        verts = np.vstack((top, lower))
        faces = [TOP, TOP[:, ::-1]+n]
        a, b = EDGE, np.roll(EDGE,-1)
        faces.extend((np.column_stack((a,a+n,b+n)), np.column_stack((a,b+n,b))))
    else:
        lower = np.column_stack((xy[EDGE], np.zeros(SECTORS)))
        verts = np.vstack((top, lower, [0,0,0]))
        a, b = EDGE, np.roll(EDGE,-1)
        c, d = n+j, n+(j+1)%SECTORS
        faces = [TOP, np.column_stack((a,c,d)), np.column_stack((a,d,b)),
                 np.column_stack((np.full(SECTORS,n+SECTORS),d,c))]
    verts[:,2] -= verts[:,2].min()
    faces = np.vstack(faces)
    edge_pairs = np.concatenate((faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]))
    _, counts = np.unique(np.sort(edge_pairs,axis=1),axis=0,return_counts=True)
    assert np.all(counts == 2), 'Non-manifold mesh'
    # Every directed edge must occur with exactly one reversed partner.
    directed = edge_pairs[:,0].astype(np.int64)*len(verts)+edge_pairs[:,1]
    reversed_edges = edge_pairs[:,1].astype(np.int64)*len(verts)+edge_pairs[:,0]
    assert np.array_equal(np.sort(directed),np.sort(reversed_edges)), 'Inconsistent winding'
    v = verts[faces]
    normals = np.cross(v[:,1]-v[:,0],v[:,2]-v[:,0])
    areas2 = np.linalg.norm(normals,axis=1)
    assert areas2.min() > 1e-9
    volume = np.einsum('ij,ij->i',v[:,0],np.cross(v[:,1],v[:,2])).sum()/6
    assert volume > 0
    record = np.zeros(len(faces),dtype=[('normal','<f4',(3,)),('vertices','<f4',(3,3)),('attr','<u2')])
    record['normal'] = normals/areas2[:,None]
    record['vertices'] = v
    with (out/name).open('wb') as f:
        f.write(f'Sacagawea {DIAMETER:g}mm image-derived relief; units mm'.encode().ljust(80,b' '))
        f.write(np.array([len(faces)],dtype='<u4').tobytes())
        f.write(record.tobytes())
    result = {'file':name,'triangles':len(faces),'dimensions_mm':np.ptp(verts,axis=0).round(4).tolist(),
              'volume_mm3':round(float(volume),3),'closed_manifold':True,'consistent_winding':True,'degenerate_triangles':0}
    print(result,flush=True)
    return result


