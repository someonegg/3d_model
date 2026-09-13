from pathlib import Path
import hashlib
import json
import struct


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resource(directory, name):
    path = (directory / name).resolve()
    if not path.is_relative_to(directory.resolve()) or not path.is_file():
        raise ValueError(f'缺失或越界资源：{name}')
    return path


EXCLUDED_DIRECTORIES = set(json.loads((Path(__file__).resolve().parents[1] / "model-discovery.json").read_text(encoding='utf-8'))["excluded_directories"])


def input_hashes(directory, model):
    root = directory.resolve().parent
    result = {}
    names = model.get("inputs", [])
    if not isinstance(names, list) or any(not isinstance(name, str) or not name or Path(name).is_absolute() for name in names):
        raise ValueError('无效构建输入列表')
    for name in names:
        path = (directory / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"缺失或越界构建输入：{name}")
        result[name] = digest(path)
    return result


def builder_path(directory, model):
    if 'build' not in model:
        return None
    name = model['build']
    inputs = model.get('inputs', [])
    if (not isinstance(name, str) or not name or Path(name).is_absolute()
            or '..' in Path(name).parts or not isinstance(inputs, list)
            or name not in inputs):
        raise ValueError('build 必须是模型目录内的脚本，且声明在 inputs 中')
    return resource(directory, name)


def discover(root):
    models = []
    for path in sorted(root.glob('*/model.json')):
        if path.parent.name.startswith('.') or path.parent.name in EXCLUDED_DIRECTORIES:
            continue
        model = json.loads(path.read_text(encoding='utf-8'))
        if model.get('id') != path.parent.name or model.get('purpose') not in ('print', 'display'):
            raise ValueError(f'无效模型 ID 或用途：{path}')
        if not model.get('variants') or len({v['id'] for v in model['variants']}) != len(model['variants']):
            raise ValueError(f'无效变体：{path}')
        for key in ('preview', 'readme'):
            name = model.get(key)
            if not isinstance(name, str) or not name or Path(name).is_absolute() or '..' in Path(name).parts:
                raise ValueError(f'无效资源路径：{key}')
        builder_path(path.parent, model)
        if 'verify' in model:
            name = model['verify']
            if (not isinstance(name, str) or not name or Path(name).is_absolute()
                    or '..' in Path(name).parts or not model.get('build')
                    or name not in model.get('inputs', [])):
                raise ValueError('verify 必须是模型目录内的脚本，且声明 build 和对应 inputs')
            resource(path.parent, name)
        artifacts = model.get('artifacts', [])
        if not isinstance(artifacts, list) or any(
            not isinstance(name, str) or not name or Path(name).is_absolute()
            or '..' in Path(name).parts for name in artifacts
        ):
            raise ValueError('无效附加产物路径')
        for variant in model['variants']:
            suffix = Path(variant['file']).suffix.lower()
            if suffix not in ('.stl', '.glb', '.gltf'):
                raise ValueError('仅支持 STL、GLB 和 glTF')
            if suffix == '.stl' and (model.get('units') not in ('mm', 'cm', 'm') or model.get('up') not in ('Y', 'Z')):
                raise ValueError('STL 必须声明 units 和 up')
            if suffix in ('.glb', '.gltf') and (model.get('units') != 'm' or model.get('up') != 'Y'):
                raise ValueError('GLB/glTF 必须使用 m 单位、Y 向上')
            if model['purpose'] == 'print' and suffix != '.stl':
                raise ValueError('打印校验仅支持 STL；请将 GLB/glTF 登记为展示模型')
        models.append((path.parent, model))
    return models


def dependencies(directory, filename):
    path = resource(directory, filename)
    result = {filename}
    if path.suffix.lower() in ('.gltf', '.glb'):
        if path.suffix.lower() == '.gltf':
            data = json.loads(path.read_text(encoding='utf-8'))
        else:
            raw = path.read_bytes()
            if len(raw) < 20 or raw[:4] != b'glTF' or raw[16:20] != b'JSON':
                raise ValueError('无效 GLB 文件')
            length = struct.unpack('<I', raw[12:16])[0]
            data = json.loads(raw[20:20 + length])
        for item in data.get('buffers', []) + data.get('images', []):
            uri = item.get('uri', '')
            if uri and not uri.startswith('data:'):
                from urllib.parse import unquote
                if ':' in uri or uri.startswith('/'):
                    raise ValueError('glTF 仅支持本地依赖')
                dep = resource(directory, str(Path(filename).parent / unquote(uri)))
                result.add(str(dep.relative_to(directory.resolve())))
        unsupported = set(data.get('extensionsRequired', [])) & {'KHR_draco_mesh_compression', 'EXT_meshopt_compression', 'KHR_texture_basisu'}
        if unsupported:
            raise ValueError(f'不支持的压缩扩展：{unsupported}')
    return result


def assets(directory, model, *, generated=False, strict=True):
    """Resources shared by build, catalog and publishing."""
    names = {'validation.json', model['preview'], *model.get('artifacts', [])}
    if not generated:
        names.add(model['readme'])
    for variant in model['variants']:
        names.add(variant['file'])
        try:
            names.update(dependencies(directory, variant['file']))
        except ValueError:
            if strict:
                raise
    return names
