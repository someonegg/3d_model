"""Small GLB writer for assembly scenes; model-specific motion stays in models."""

import json
import struct

import numpy as np


class AssemblyWriter:
    def __init__(self, duration, steps=None, rotation=None):
        root = {'name': 'assembly-root', 'children': []}
        if rotation is not None:
            root['rotation'] = rotation
        self.data = dict(
            asset={'version': '2.0', 'generator': 'model-workbench'}, scene=0,
            scenes=[{'nodes': [0], 'extras': {'assembly': {
                'version': 1, 'duration': duration, 'steps': steps if steps is not None else []}}}],
            nodes=[root], meshes=[], materials=[], accessors=[], bufferViews=[],
            animations=[{'name': 'Assembly', 'samplers': [], 'channels': []}])
        self.content = bytearray()

    def accessor(self, values, kind, component=5126):
        a = np.asarray(values, dtype='<f4' if component == 5126 else '<u4')
        self.content.extend(b'\0' * (-len(self.content) % 4))
        view = len(self.data['bufferViews'])
        self.data['bufferViews'].append(dict(
            buffer=0, byteOffset=len(self.content), byteLength=a.nbytes))
        self.content.extend(a.tobytes())
        row = dict(bufferView=view, componentType=component, count=len(a), type=kind)
        if kind == 'SCALAR':
            row.update(min=[float(a.min())], max=[float(a.max())])
        else:
            row.update(min=a.min(axis=0).tolist(), max=a.max(axis=0).tolist())
        self.data['accessors'].append(row)
        return len(self.data['accessors']) - 1

    def track(self, node, prop, times, values, kind):
        animation = self.data['animations'][0]
        sampler = len(animation['samplers'])
        animation['samplers'].append(dict(
            input=self.accessor(times, 'SCALAR'), output=self.accessor(values, kind),
            interpolation='LINEAR'))
        animation['channels'].append(dict(sampler=sampler, target=dict(node=node, path=prop)))

    def mesh(self, name, vertices, normals, faces, rgba, metallic=0):
        material = len(self.data['materials'])
        self.data['materials'].append(dict(name=name, pbrMetallicRoughness=dict(
            baseColorFactor=rgba, metallicFactor=metallic, roughnessFactor=.65)))
        index = len(self.data['meshes'])
        self.data['meshes'].append(dict(name=name, primitives=[dict(
            attributes={'POSITION': self.accessor(vertices, 'VEC3'),
                        'NORMAL': self.accessor(normals, 'VEC3')},
            indices=self.accessor(np.asarray(faces).reshape(-1), 'SCALAR', 5125),
            material=material)]))
        return index

    def write(self, path):
        self.content.extend(b'\0' * (-len(self.content) % 4))
        self.data['buffers'] = [{'byteLength': len(self.content)}]
        encoded = json.dumps(self.data, ensure_ascii=False, separators=(',', ':')).encode()
        encoded += b' ' * (-len(encoded) % 4)
        chunks = struct.pack('<II', len(encoded), 0x4E4F534A) + encoded
        chunks += struct.pack('<II', len(self.content), 0x004E4942) + self.content
        path.write_bytes(struct.pack('<4sII', b'glTF', 2, 12 + len(chunks)) + chunks)
