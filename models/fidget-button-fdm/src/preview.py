"""Public model preview rendering."""
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import trimesh
from geometry import P, make_parts

def draw_preview(out):
    """Orthographic views rendered from the actual delivered meshes."""
    canvas = Image.new('RGB', (1200, 760), '#f5f2eb')
    draw = ImageDraw.Draw(canvas)
    draw.text((40, 24), 'FIDGET BUTTON / KEYED SPRING CUP / 42 mm / 3 mm TRAVEL / 4 mm PROTRUSION', fill='#22313a')
    rotation = trimesh.transformations.euler_matrix(np.radians(-55), 0, np.radians(-30))[:3,:3]
    faces_to_draw = []
    for (name, mesh), color in zip(make_parts(),
            [(80,98,108),(199,128,84),(80,98,108),(126,174,177)]):
        if name in ('外壳', '按帽'):
            mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi, (1,0,0)))
            mesh.apply_translation((0,0,17 if name == '外壳' else P['cap_face_z']))
        else:
            mesh.apply_translation((0,0,-2.4 if name == '底盖' else P['spring_seat_z']))
        vertices = (mesh.vertices - np.array([0,0,8])) @ rotation.T
        faces = vertices[mesh.faces]
        normals = np.cross(faces[:,1]-faces[:,0], faces[:,2]-faces[:,0])
        normals /= np.maximum(np.linalg.norm(normals,axis=1)[:,None],1e-10)
        for face, normal in zip(faces, normals):
            shade = .65+.35*abs(float(normal @ np.array([.25,-.35,.9])))
            fill = tuple(int(c*min(1.,shade)) for c in color)
            faces_to_draw.append((face, fill))
    # Sort all parts together so the shell correctly hides the internal spring.
    for face, fill in sorted(faces_to_draw, key=lambda row: row[0][:,2].mean()):
        draw.polygon([(600+float(x)*13,380-float(y)*13) for x,y,z in face], fill=fill)
    draw.text((40,725), 'ASSEMBLED / 42 mm DIAMETER / 3 mm TRAVEL / 4 mm PROTRUSION', fill='#22313a')
    canvas.save(out / 'preview.png')


