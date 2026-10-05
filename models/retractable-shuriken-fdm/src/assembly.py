"""Static views and an assembly/operation guide made from the printable meshes."""
import numpy as np
import trimesh

from tools.assembly_gltf import AssemblyWriter
from geometry import P, WINGS, LID_Z, mesh_of, pose

COLORS = {'base': '#344b5b', 'lid': '#536f80', 'rotor': '#e9b45f',
          **{name: '#78bdb0' for name in WINGS}}


def xyz(values):
    a = np.asarray(values)
    return (a[..., [0, 2, 1]] * [1, 1, -1] / 1000).tolist()


def rgba(name):
    return [int(COLORS[name][i:i+2], 16)/255 for i in (1, 3, 5)] + [1]


def write_static(parts, path, degrees):
    scene = trimesh.Scene()
    for name, solid in pose(parts, degrees).items():
        mesh = mesh_of(solid)
        mesh.vertices = np.array(xyz(mesh.vertices))
        # Keep the planar lid, guide walls and slot rims visually flat instead
        # of averaging their normals into a falsely rounded surface.
        mesh.unmerge_vertices()
        mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
            baseColorFactor=np.array(rgba(name)), metallicFactor=0, roughnessFactor=.65))
        scene.add_geometry(mesh, node_name=name)
    path.write_bytes(scene.export(file_type='glb'))


def write_assembly(parts, path):
    steps = [
        dict(title='放入四个滑翼', hint='底座平放，四个圆钝翼依次落入导轨；一体销朝上，全部推至内侧。',
             start=0, end=4, targets=WINGS, transparentTargets=[], marker=xyz([14.5, 0, 4.5])),
        dict(title='安装联动转盘', hint='对准中央轴、偏心止挡销与四条曲线槽，轻放转盘；切勿用力压弯销柱。',
             start=6, end=10, targets=['rotor'], transparentTargets=[], marker=xyz([8, 0, 5])),
        dict(title='扣合上盖', hint='转盘露出中央孔；对齐四个卡扣位置，逐个轻压上盖。动画不模拟卡扣弹性。',
             start=12, end=16, targets=['lid'], transparentTargets=['lid'], opacity=.30,
             marker=xyz([20, 28, LID_Z])),
        dict(title='手动伸缩检查', hint='握住外壳，旋转中央转盘约 60°，四翼同步伸缩。到止挡即停止；实物手感和耐久待试打。',
             start=18, end=24, targets=['rotor', *WINGS], transparentTargets=['lid'], opacity=.22,
             marker=xyz([0, 0, 12])),
    ]
    writer = AssemblyWriter(24, steps=steps)
    for name, solid in parts.items():
        mesh = mesh_of(solid)
        mesh.unmerge_vertices()
        normals = mesh.vertex_normals[:, [0, 2, 1]] * [1, 1, -1]
        index = writer.mesh(name, xyz(mesh.vertices), normals, mesh.faces, rgba(name))
        node = len(writer.data['nodes'])
        offset = 28 if name in WINGS else 48 if name == 'rotor' else 68 if name == 'lid' else 0
        writer.data['nodes'].append(dict(name=name, mesh=index, translation=xyz([0, 0, offset])))
        writer.data['nodes'][0]['children'].append(node)
        if name in WINGS:
            a = WINGS.index(name)*np.pi/2
            extended = xyz([P['travel']*np.cos(a), P['travel']*np.sin(a), 0])
            writer.track(node, 'translation', [0, 4, 18, 21, 24],
                         [xyz([0, 0, offset]), [0, 0, 0], [0, 0, 0], extended, [0, 0, 0]], 'VEC3')
        elif name in ('rotor', 'lid'):
            start = 6 if name == 'rotor' else 12
            writer.track(node, 'translation', [0, start, start+4, 24],
                         [xyz([0, 0, offset]), xyz([0, 0, offset]), [0, 0, 0], [0, 0, 0]], 'VEC3')
        if name == 'rotor':
            a = np.radians(P['rotation_degrees'])/2
            writer.track(node, 'rotation', [0, 18, 21, 24],
                         [[0, 0, 0, 1], [0, 0, 0, 1], [0, np.sin(a), 0, np.cos(a)], [0, 0, 0, 1]], 'VEC4')
    writer.write(path)
