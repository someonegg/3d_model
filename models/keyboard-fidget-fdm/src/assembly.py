"""Assembly animation generated from the five final solids."""
import json
import struct
import numpy as np
from tools.assembly_gltf import AssemblyWriter
COLORS = dict(shell='#354d5a', base='#728995', plunger='#cf8d52', keycap='#efad61', cartridge='#55a797')
STEPS = [('弹性盒落座', '两种宽定位缺口对准底座定位块，捏住外框平放。', ['cartridge'], (0, 0, 8)), ('放入导向柱', '承压板对准两只加高回弹接触垫，凸轮朝向两侧段落臂触头；导向无防呆，反向不能正常工作。', ['plunger'], (0, 0, 12)), ('罩合外壳', '从上方垂直罩合，确认凸轮仍朝向段落臂触头；垂直压下，使定位柱双斜面凸头越过窄槽并进入上端落位槽，固定座抵住底座后安装螺钉；拆卸先退出螺钉，再垂直拉开。', ['shell'], (0, 0, 18)), ('底面拧入螺钉', '扶住外壳，从底面交替轻拧两颗 ST2.2 × 8 mm、90° 沉头塑料自攻螺钉；头径不超过 4.4 mm，不夹压弹性盒。', ['base', 'shell'], (20.0, 20.0, 0)), ('安装键帽', '宽插口对准导向柱并压至止肩，检查中心和四角复位。', ['keycap'], (0, 0, 24))]

def xyz(v):
    x, y, z = v
    return [x / 1000, z / 1000, -y / 1000]

def write_assembly(parts, mesh_of, path):
    writer = AssemblyWriter(25, steps=[dict(title=t, hint=h, targets=targets, transparentTargets=['shell'] if i < 4 else [], start=i * 5, end=i * 5 + 3, marker=xyz(marker)) for i, (t, h, targets, marker) in enumerate(STEPS)])
    for name, part in parts.items():
        m = mesh_of(part)
        vertices = np.array([xyz(v) for v in m.vertices])
        normals = m.vertex_normals[:, [0, 2, 1]].copy()
        normals[:, 2] *= -1
        color = COLORS[name]
        rgba = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)] + [1]
        mesh = writer.mesh(name, vertices, normals, m.faces, rgba)
        node = len(writer.data['nodes'])
        offset = (0, 0, 0) if name == 'base' else (0, 0, 40)
        writer.data['nodes'].append(dict(name=name, mesh=mesh, translation=xyz(offset)))
        writer.data['nodes'][0]['children'].append(node)
        if name == 'base':
            continue
        step = next((i for i, s in enumerate(STEPS) if name in s[2]))
        start = step * 5
        times = [0, start, start + 3, 25] if start else [0, 3, 25]
        poses = [xyz(offset), xyz(offset), [0, 0, 0], [0, 0, 0]] if start else [xyz(offset), [0, 0, 0], [0, 0, 0]]
        writer.track(node, 'translation', times, poses, 'VEC3')
    writer.write(path)

def verify_assembly(path, assembled):
    """Check exported binary geometry and animation end poses against print parts.
STL loading may reorder vertices; compare the unique coordinate sets."""
    raw = path.read_bytes()
    magic, version, length = struct.unpack_from('<4sII', raw)
    assert magic == b'glTF' and version == 2 and (length == len(raw))
    json_length, kind = struct.unpack_from('<II', raw, 12)
    assert kind == 1313821514
    data = json.loads(raw[20:20 + json_length])
    binary = raw[28 + json_length:]

    def values(index):
        row = data['accessors'][index]
        view = data['bufferViews'][row['bufferView']]
        width = {'SCALAR': 1, 'VEC3': 3, 'VEC4': 4}[row['type']]
        dtype = '<f4' if row['componentType'] == 5126 else '<u4'
        return np.frombuffer(binary, dtype=dtype, count=row['count'] * width, offset=view.get('byteOffset', 0) + row.get('byteOffset', 0)).reshape(-1, width)
    guide = data['scenes'][0]['extras']['assembly']
    assert guide['version'] == 1 and guide['duration'] == 25 and (len(guide['steps']) == 5)
    meshes = {node['name']: node for node in data['nodes'] if 'mesh' in node}
    assert set(meshes) == set(assembled)
    for i, step in enumerate(guide['steps']):
        assert step['targets'] == STEPS[i][2]
        assert step['transparentTargets'] == (['shell'] if i < 4 else [])
        assert 'part' not in step
    for name, node in meshes.items():
        primitive = data['meshes'][node['mesh']]['primitives'][0]
        actual = values(primitive['attributes']['POSITION']).copy()
        expected = np.array([xyz(v) for v in assembled[name].vertices])
        np.testing.assert_allclose(np.unique(actual.round(7), axis=0), np.unique(expected.round(7), axis=0), atol=1.1e-07)
    animation = data['animations'][0]
    assert len(animation['channels']) == 4
    for channel in animation['channels']:
        sampler = animation['samplers'][channel['sampler']]
        times = values(sampler['input']).ravel()
        poses = values(sampler['output'])
        assert times[0] == 0 and times[-1] == guide['duration'] and np.all(np.diff(times) > 0)
        name = data['nodes'][channel['target']['node']]['name']
        if channel['target']['path'] == 'rotation':
            np.testing.assert_allclose(poses[-1], [0, 0, 0, 1])
        else:
            np.testing.assert_allclose(poses[-1], [0, 0, 0])
        if name == 'cartridge':
            assert np.all(poses[:, [0, 2]] == 0) and np.all(np.diff(poses[:, 1]) <= 0)
            assert poses[0, 1] > 0.03
    return {'parts': 5, 'steps': 5, 'duration_seconds': 25, 'geometry_matches_print_parts': True, 'final_poses_match': True, 'cartridge_insertion_axis': '-Z'}
