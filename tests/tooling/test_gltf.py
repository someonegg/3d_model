import base64
import io
import json
import struct
import tempfile
from pathlib import Path
import unittest

from PIL import Image

from tools.model_library.gltf import normalize, pack
from tools.model_library.resources import dependencies


def glb(data, binary=None):
    encoded = json.dumps(data).encode()
    encoded += b' ' * (-len(encoded) % 4)
    chunks = struct.pack('<II', len(encoded), 0x4e4f534a) + encoded
    if binary is not None:
        binary += b'\0' * (-len(binary) % 4)
        chunks += struct.pack('<II', len(binary), 0x004e4942) + binary
    return struct.pack('<4sII', b'glTF', 2, 12 + len(chunks)) + chunks


class PackingTests(unittest.TestCase):
    def test_external_and_embedded_buffers_images_and_scene_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'nested').mkdir()
            texture = io.BytesIO()
            Image.new('RGB', (2, 2), 'red').save(texture, format='PNG')
            png = texture.getvalue()
            (root / 'nested/texture name.png').write_bytes(png)
            (root / 'nested/data.bin').write_bytes(b'abcdef')
            for kind in ('gltf', 'external-glb', 'mixed-glb'):
                with self.subTest(kind=kind):
                    data = {'asset': {'version': '2.0'},
                            'buffers': [{'byteLength': 6, 'uri': 'data.bin'},
                                        {'byteLength': 3, 'uri': 'data:application/octet-stream;base64,' + base64.b64encode(b'xyz').decode()}],
                            'bufferViews': [{'buffer': 0, 'byteOffset': 1, 'byteLength': 4},
                                            {'buffer': 1, 'byteLength': 3}],
                            'images': [{'uri': 'texture%20name.png'},
                                       {'uri': 'data:image/png;base64,' + base64.b64encode(png).decode()}],
                            'nodes': [{'name': 'preserved', 'extras': {'custom': 1}}],
                            'animations': [{'name': 'retained'}],
                            'materials': [{'extensions': {'KHR_materials_unlit': {}}}],
                            'extensionsUsed': ['KHR_materials_unlit'], 'extras': {'source': kind}}
                    if kind == 'mixed-glb':
                        del data['buffers'][0]['uri']
                    name = 'nested/model.' + ('gltf' if kind == 'gltf' else 'glb')
                    (root / name).write_bytes(json.dumps(data).encode() if kind == 'gltf' else glb(data, b'abcdef' if kind == 'mixed-glb' else None))
                    result = pack(root, name)
                    self.assertEqual(struct.unpack_from('<I', result, 8)[0], len(result))
                    length = struct.unpack_from('<I', result, 12)[0]
                    packed = json.loads(result[20:20 + length])
                    binary = result[28 + length:]
                    for key in ('nodes', 'animations', 'materials', 'extensionsUsed', 'extras'):
                        self.assertEqual(packed[key], data[key])
                    for view, expected in zip(packed['bufferViews'], (b'bcde', b'xyz', png, png)):
                        self.assertEqual(view['buffer'], 0)
                        offset = view['byteOffset']
                        self.assertEqual(binary[offset:offset + view['byteLength']], expected)
                    self.assertNotIn('uri', packed['buffers'][0])
                    self.assertTrue(all('uri' not in image for image in packed['images']))
                    (root / 'packed.glb').write_bytes(result)
                    self.assertEqual(dependencies(root, 'packed.glb'), {'packed.glb'})

    def test_rejects_missing_truncated_remote_and_escaping_resources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'model'
            root.mkdir()
            # The escaping resource exists and is valid, so rejection must
            # enforce the boundary rather than merely notice a missing file.
            (Path(temp) / 'outside.bin').write_bytes(b'abcd')
            (root / 'short.bin').write_bytes(b'a')
            for uri in ('missing.bin', 'short.bin', '../outside.bin', 'https://example.com/data.bin'):
                with self.subTest(uri=uri):
                    (root / 'model.gltf').write_text(json.dumps({'buffers': [{'uri': uri, 'byteLength': 4}]}))
                    with self.assertRaises(ValueError):
                        pack(root, 'model.gltf')

    def test_output_collision_keeps_inputs_intact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'model.gltf').write_text('{}')
            (root / 'model.glb').write_bytes(b'keep')
            with self.assertRaisesRegex(ValueError, '冲突'):
                normalize(root, {'variants': [{'file': 'model.gltf'}]})
            self.assertEqual((root / 'model.glb').read_bytes(), b'keep')
