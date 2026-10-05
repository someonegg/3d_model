"""Generate a self-contained glTF assembly guide from the actual part meshes."""
import json
import struct
import numpy as np
from tools.assembly_gltf import AssemblyWriter

COLORS = {'shell': '#354d5a', 'keycap': '#efad61', 'plunger': '#cf8d52',
          'base': '#728995', 'return-spring': '#55a797', 'click-spring': '#c7a367'}
STEPS = [
    ('穿入导向柱', '外壳开口朝上；削角对齐长导向孔，两个防脱肩留在壳内。', 'plunger', (7, 3, 15)),
    ('放入段落弹舌', '定位边框朝壳底，缺口对准挂耳侧定位筋；触头对准两侧凸轮。', 'click-spring', (-13, 0, 9)),
    ('放入回弹片', '缺口对准同一定位筋，加厚凸边朝壳底；自由端接触推脚，不压弹臂根部。', 'return-spring', (-13, 0, 6)),
    ('滑入底盖', '支柱朝内，从较大侧入口沿导轨滑入。卡滞时退出检查毛边、倾斜和缺口，不强推。', 'base', (15, 0, 2)),
    ('翻正并安装键帽', '扶住导向柱，将键帽压到插接肩。检查中心及四角复位；实物装拆、手感和耐久尚待验证。', 'keycap', (0, 0, 21)),
]


def xyz(v):
    x, y, z = v
    return [x / 1000, z / 1000, -y / 1000]


def write_assembly(parts, mesh_of, path):
    writer = AssemblyWriter(25, steps=[
        dict(title=title, hint=hint, targets=[part],
             transparentTargets=['shell'] if i < 4 else [],
             start=i*5, end=i*5+3, marker=xyz(marker))
        for i, (title, hint, part, marker) in enumerate(STEPS)], rotation=[1, 0, 0, 0])
    data, track = writer.data, writer.track

    offsets = {'shell': (0, 0, 0), 'plunger': (0, 0, -35),
               'click-spring': (0, 0, -55), 'return-spring': (0, 0, -75),
               'base': (55, 0, 0), 'keycap': (55, 0, 30)}
    for name, solid in parts.items():
        m = mesh_of(solid)
        vertices = np.array([xyz(v) for v in m.vertices])
        normals = np.asarray(m.vertex_normals)[:, [0, 2, 1]].copy()
        normals[:, 2] *= -1
        color = COLORS[name]
        rgba = [int(color[i:i+2], 16)/255 for i in (1, 3, 5)] + [1]
        mesh = writer.mesh(name, vertices, normals, m.faces, rgba)
        node = len(data['nodes'])
        data['nodes'].append(dict(name=name, mesh=mesh, translation=xyz(offsets[name])))
        data['nodes'][0]['children'].append(node)
        if name == 'shell':
            continue
        step = next(i for i, s in enumerate(STEPS) if s[2] == name)
        start = step * 5
        times = [0, start, start+3, 25] if start else [0, 3, 25]
        values = [xyz(offsets[name]), xyz(offsets[name]), [0, 0, 0], [0, 0, 0]] if start else [xyz(offsets[name]), [0, 0, 0], [0, 0, 0]]
        if name == 'keycap':
            times = [0, 21, 22, 23, 25]
            values = [xyz(offsets[name]), xyz(offsets[name]), xyz((0, 0, 10)), [0, 0, 0], [0, 0, 0]]
        track(node, 'translation', times, values, 'VEC3')
    track(0, 'rotation', [0, 20, 21, 25], [[1, 0, 0, 0], [1, 0, 0, 0], [0, 0, 0, 1], [0, 0, 0, 1]], 'VEC4')
    writer.write(path)


def verify_assembly(path, assembled):
    """Check exported binary geometry and animation end poses against print parts."""
    raw = path.read_bytes()
    magic, version, length = struct.unpack_from('<4sII', raw)
    assert magic == b'glTF' and version == 2 and length == len(raw)
    json_length, kind = struct.unpack_from('<II', raw, 12)
    assert kind == 0x4E4F534A
    data = json.loads(raw[20:20+json_length])
    binary = raw[28+json_length:]

    def values(index):
        row = data['accessors'][index]
        view = data['bufferViews'][row['bufferView']]
        width = {'SCALAR': 1, 'VEC3': 3, 'VEC4': 4}[row['type']]
        dtype = '<f4' if row['componentType'] == 5126 else '<u4'
        return np.frombuffer(binary, dtype=dtype, count=row['count']*width,
                             offset=view.get('byteOffset', 0)+row.get('byteOffset', 0)).reshape(-1, width)

    guide = data['scenes'][0]['extras']['assembly']
    assert guide['version'] == 1 and guide['duration'] == 25 and len(guide['steps']) == 5
    meshes = {node['name']: node for node in data['nodes'] if 'mesh' in node}
    assert set(meshes) == set(assembled)
    for i, step in enumerate(guide['steps']):
        assert step['targets'] == [STEPS[i][2]]
        assert step['transparentTargets'] == (['shell'] if i < 4 else [])
        assert 'part' not in step
    for name, node in meshes.items():
        primitive = data['meshes'][node['mesh']]['primitives'][0]
        actual = values(primitive['attributes']['POSITION'])
        expected = np.array([xyz(v) for v in assembled[name].vertices])
        # STL loading may reorder vertices; compare the unique coordinate sets.
        np.testing.assert_allclose(np.unique(actual.round(7), axis=0),
                                   np.unique(expected.round(7), axis=0), atol=1.1e-7)
    animation = data['animations'][0]
    assert len(animation['channels']) == 6
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
        if name == 'base':
            assert np.all(poses[:, 1:] == 0) and np.all(np.diff(poses[:, 0]) <= 0)
            assert poses[0, 0] > .03
    return {'parts': 6, 'steps': 5, 'duration_seconds': 25,
            'geometry_matches_print_parts': True, 'final_poses_match': True,
            'base_insertion_axis': '-X'}
