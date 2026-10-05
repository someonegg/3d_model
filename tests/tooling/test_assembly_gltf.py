import json
import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tools.assembly_gltf import AssemblyWriter


class AssemblyWriterTests(unittest.TestCase):
    def test_exported_geometry_tracks_and_metadata(self):
        steps = [dict(title='安装', hint='对齐', start=0, end=1, marker=[0, 0, 0],
                      targets=['part'], transparentTargets=[])]
        writer = AssemblyWriter(2, steps, rotation=[0, 0, 0, 1])
        vertices = [[0, 0, 0], [.001, 0, 0], [0, .002, 0]]
        mesh = writer.mesh('part', vertices, [[0, 0, 1]] * 3, [[0, 1, 2]], [1, .5, 0, 1])
        writer.data['nodes'].append(dict(name='part', mesh=mesh))
        writer.data['nodes'][0]['children'].append(1)
        writer.track(1, 'translation', [0, 2], [[.1, 0, 0], [0, 0, 0]], 'VEC3')
        writer.track(0, 'rotation', [0, 2], [[0, 0, 0, 1]] * 2, 'VEC4')
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'assembly.glb'
            writer.write(path)
            raw = path.read_bytes()
        self.assertEqual(struct.unpack_from('<4sII', raw), (b'glTF', 2, len(raw)))
        length, kind = struct.unpack_from('<II', raw, 12)
        self.assertEqual(kind, 0x4E4F534A)
        self.assertEqual(length % 4, 0)
        data = json.loads(raw[20:20 + length])
        size, kind = struct.unpack_from('<II', raw, 20 + length)
        self.assertEqual(kind, 0x004E4942)
        binary = raw[28 + length:]
        self.assertEqual(size, len(binary))
        self.assertEqual(data['buffers'][0]['byteLength'], size)
        self.assertEqual(data['scenes'][0]['extras']['assembly']['steps'], steps)
        self.assertEqual(data['nodes'][0]['children'], [1])
        self.assertEqual(len(data['animations'][0]['channels']), 2)
        for view in data['bufferViews']:
            self.assertEqual(view['byteOffset'] % 4, 0)
            self.assertLessEqual(view['byteOffset'] + view['byteLength'], len(binary))

        def values(index):
            accessor = data['accessors'][index]
            view = data['bufferViews'][accessor['bufferView']]
            dtype = '<f4' if accessor['componentType'] == 5126 else '<u4'
            return np.frombuffer(binary, dtype=dtype, offset=view['byteOffset'],
                                 count=view['byteLength'] // 4)

        primitive = data['meshes'][0]['primitives'][0]
        np.testing.assert_allclose(values(primitive['attributes']['POSITION']).reshape(-1, 3), vertices)
        np.testing.assert_array_equal(values(primitive['indices']), [0, 1, 2])
        animation = data['animations'][0]
        sampler = animation['samplers'][animation['channels'][0]['sampler']]
        np.testing.assert_array_equal(values(sampler['input']), [0, 2])
        np.testing.assert_allclose(values(sampler['output']).reshape(-1, 3), [[.1, 0, 0], [0, 0, 0]])
        self.assertEqual(data['materials'][0]['pbrMetallicRoughness']['baseColorFactor'], [1, .5, 0, 1])

    def test_models_declare_writer_as_incremental_input(self):
        repo = Path(__file__).resolve().parents[2]
        for model_id in ['keyboard-fidget-fdm', 'volvo-xc60-2022']:
            with self.subTest(model=model_id):
                directory = repo / 'models' / model_id
                model = json.loads((directory / 'model.json').read_text())
                self.assertIn('../../tools/assembly_gltf.py', model['inputs'])
