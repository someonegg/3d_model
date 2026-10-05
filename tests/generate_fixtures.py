"""Create tiny textured glTF/GLB assets for browser acceptance tests."""
import argparse
import json
import shutil
import sys
import struct
from pathlib import Path

import numpy as np
from PIL import Image
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.model_library.gltf import pack

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / 'tmp/fixtures'


def generate(fixture_root):
    fixture_root = Path(fixture_root)
    if fixture_root.exists():
        shutil.rmtree(fixture_root)
    output = fixture_root / 'assets'
    output.mkdir(parents=True, exist_ok=True)
    (fixture_root / 'models').mkdir()
    mesh = trimesh.creation.box(extents=[1, 2, 3])
    texture = Image.new('RGB', (2, 2), '#286ecb')
    texture.putpixel((0, 0), (240, 160, 40))
    mesh.visual = trimesh.visual.texture.TextureVisuals(
        uv=np.zeros((len(mesh.vertices), 2)), image=texture)
    scene = trimesh.Scene(mesh)
    for name, data in scene.export(file_type='gltf').items():
        (output / name).write_bytes(data)
    scene.export(output / 'model.glb')

    texture.save(output / 'texture.png')
    gltf = json.loads((output / 'model.gltf').read_text())
    gltf['images'] = [{'uri': 'texture.png'}]
    (output / 'model.gltf').write_text(json.dumps(gltf))
    (output / 'packed.glb').write_bytes(pack(output, 'model.gltf'))
    encoded = json.dumps(gltf).encode()
    encoded += b' ' * (-len(encoded) % 4)
    (output / 'external.glb').write_bytes(struct.pack('<4sIIII', b'glTF', 2, 20 + len(encoded), len(encoded), 0x4e4f534a) + encoded)
    (output / 'external-packed.glb').write_bytes(pack(output, 'external.glb'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_ROOT)
    generate(parser.parse_args().output)
