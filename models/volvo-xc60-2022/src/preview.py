"""Public mesh-derived previews and static display scenes."""
import math
import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageFont
from geometry import COLORS, mesh, open_door

def render(parts, destination, angle=0, exploded=False, rear=False):
    width, height, ss = 1500, 960, 2
    canvas = Image.new('RGB', (width*ss, height*ss), '#e9edef')
    draw = ImageDraw.Draw(canvas)
    direction = np.array([.9 if rear else -.95, -1.35, .84])
    direction /= np.linalg.norm(direction)
    right = np.cross([0, 0, 1], direction); right /= np.linalg.norm(right)
    up = np.cross(direction, right)
    basis = np.array([right, up, direction]).T
    meshes = []
    for part in parts:
        shape = part['solid']
        if angle and part['group'].startswith('door-'):
            shape = open_door(shape, 1 if part['group']=='door-left' else -1, angle)
        obj = mesh(shape)
        if exploded:
            n = part['name']
            if n == 'body': obj.apply_translation((0, 0, 43))
            elif part['group'].startswith('door-'):
                obj.apply_translation((0, 34 if part['group']=='door-left' else -34, 25))
            elif part['group']=='wheel':
                obj.apply_translation((0, 26*np.sign(obj.centroid[1]), -8))
            elif n in ['interior','dashboard']: obj.apply_translation((0, 0, 18))
            elif n != 'chassis': obj.apply_translation((0, 0, 43))
        meshes.append((obj, COLORS[part['color']]))
    all_pts = np.concatenate([obj.vertices@basis for obj, _ in meshes])
    lo, hi = all_pts.min(0), all_pts.max(0)
    scale = min((width-150)/(hi[0]-lo[0]), (height-250)/(hi[1]-lo[1]))*ss
    center = (lo+hi)/2
    pixels = np.asarray(canvas).copy()
    depth = np.full((height*ss, width*ss), -np.inf, dtype=np.float32)
    light = np.array([-.5, -.6, 1]); light /= np.linalg.norm(light)
    for obj, color in meshes:
        projected = obj.vertices@basis
        xy = (projected[:, :2]-center[:2])*[scale, -scale]+[width*ss/2, height*ss*.55]
        for face, normal in zip(obj.faces, obj.face_normals):
            if normal@direction <= .001: continue
            tri = xy[face]
            xmin,ymin = np.maximum(np.floor(tri.min(0)).astype(int), 0)
            xmax,ymax = np.minimum(np.ceil(tri.max(0)).astype(int), [width*ss-1,height*ss-1])
            if xmax < xmin or ymax < ymin: continue
            a,b,c=tri
            det=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
            if abs(det)<1e-10: continue
            yy,xx=np.mgrid[ymin:ymax+1,xmin:xmax+1]
            u=((b[1]-c[1])*(xx+.5-c[0])+(c[0]-b[0])*(yy+.5-c[1]))/det
            v=((c[1]-a[1])*(xx+.5-c[0])+(a[0]-c[0])*(yy+.5-c[1]))/det
            w=1-u-v
            z=u*projected[face[0],2]+v*projected[face[1],2]+w*projected[face[2],2]
            region=depth[ymin:ymax+1,xmin:xmax+1]
            visible=(u>=-1e-6)&(v>=-1e-6)&(w>=-1e-6)&(z>region)
            lighting=.56+.44*max(0,normal@light)
            pixels[ymin:ymax+1,xmin:xmax+1][visible]=[int(v*lighting) for v in color[:3]]
            region[visible]=z[visible]
    canvas=Image.fromarray(pixels)
    draw=ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 36*ss)
        small = ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc', 19*ss)
    except OSError:
        font = small = ImageFont.load_default(size=24*ss)
    draw.text((55*ss, 34*ss), 'VOLVO XC60 / 2022', font=font, fill='#263540')
    state = 'EXPLODED ASSEMBLY' if exploded else ('FRONT DOORS / 60 DEG' if angle else 'ZHIYUAN LUXURY / 1:24')
    draw.text((57*ss, 90*ss), state, font=small, fill='#657580')
    draw.text((57*ss, 914*ss), '196.2 mm  |  PLA  |  0.4 mm nozzle  |  Mesh-derived preview', font=small, fill='#657580')
    canvas.resize((width, height), Image.Resampling.LANCZOS).save(destination)


def scene(parts, angle=0):
    result = trimesh.Scene()
    for part in parts:
        shape = part['solid']
        if part['group'].startswith('door-'):
            shape = open_door(shape, 1 if part['group']=='door-left' else -1, angle)
        obj = mesh(shape)
        obj.visual = trimesh.visual.ColorVisuals(obj, vertex_colors=COLORS[part['color']])
        # GLB uses metres and Y-up.
        obj.apply_transform(trimesh.transformations.rotation_matrix(-math.pi/2, [1, 0, 0]))
        obj.apply_scale(.001)
        result.add_geometry(obj, node_name=part['name'], geom_name=part['name'])
    return result


