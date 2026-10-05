"""Shared source copying and optional deterministic ZIPs with an independent cache."""
import json
import shutil
import zipfile
from pathlib import Path

from .resources import digest, DigestCache, resource, output_directory


def relative_name(name):
    if (not isinstance(name, str) or not name or '\\' in name
            or ':' in name or Path(name).is_absolute() or any(p in ('..', '.') for p in name.split('/'))
            or any(not p for p in name.split('/'))):
        raise ValueError(f'无效打包路径：{name}')
    return name


STATIC = {'.md', '.pdf', '.png', '.jpg', '.jpeg', '.webp', '.svg'}
INTERNAL = {'validation.json', 'bundle-validation.json', 'packaging-validation.json', 'model.json'}


def configuration(directory, model):
    from .gltf import output_model
    converted = output_model(model)
    geometry = {converted['preview'], *converted.get('artifacts', []), *(v['file'] for v in converted['variants'])}
    copies = [model['readme']]
    seen = set(copies)
    for item in model.get('publish', []):
        path = relative_name(item.get('path') if isinstance(item, dict) else item)
        if path in seen:
            raise ValueError('重复发布目标路径')
        seen.add(path)
        if isinstance(item, dict):
            if set(item) != {'from', 'path'} or item['from'] != 'source':
                raise ValueError('源码发布项必须声明 from: source 和 path')
            copies.append(path)
    for path in copies:
        relative_name(path)
        if path in geometry or path in INTERNAL or Path(path).suffix.lower() not in STATIC:
            raise ValueError('复制项只能是静态说明或图片，不能覆盖几何产物或内部资源')
        if any(part in {'src', 'source', 'references'} for part in Path(path).parts):
            raise ValueError('不能发布内部资源')
        resource(directory, path)
    bundle = None
    if 'bundle' in model:
        bundle = json.loads(resource(directory, relative_name(model['bundle'])).read_text(encoding='utf-8'))
        if not isinstance(bundle, dict):
            raise ValueError('打包配置必须为对象')
        filename = relative_name(bundle.get('file'))
        if not filename.endswith('.zip') or filename not in model.get('publish', []):
            raise ValueError('打包 ZIP 必须声明在 publish 中')
        if filename in geometry or filename in copies:
            raise ValueError('打包输出不能覆盖几何或复制产物')
        files = bundle.get('files')
        if not isinstance(files, list) or not files:
            raise ValueError('打包文件列表不能为空')
        seen = set()
        for row in files:
            if not isinstance(row, dict) or set(row) != {'from', 'path'} or row['from'] not in ('source', 'output'):
                raise ValueError('打包项必须仅包含 from 和 path，from 为 source 或 output')
            path = relative_name(row['path'])
            if path in seen or path == filename or path in INTERNAL:
                raise ValueError('重复归档路径或打包自身/内部报告')
            seen.add(path)
            if row['from'] == 'source':
                resource(directory, path)
    return {'copies': copies, 'bundle': bundle}


def outputs(config):
    return set(config['copies']) | ({config['bundle']['file']} if config['bundle'] else set())


def fingerprints(directory, model, output, config, *, hashes=None):
    hashes = hashes if hashes is not None else DigestCache()
    rows = [{'from': 'source', 'path': n} for n in config['copies']]
    rows += config['bundle']['files'] if config['bundle'] else []
    manifest = json.loads(resource(directory, 'model.json').read_text(encoding='utf-8'))
    return {
        'config': config,
        'manifest': {k: manifest.get(k) for k in ('readme', 'publish', 'bundle')},
        'bundle_config': hashes(resource(directory, model['bundle'])) if model.get('bundle') else None,
        'code': {p.name: hashes(p) for p in [Path(__file__), Path(__file__).with_name('resources.py')]},
        'inputs': {r['from'] + ':' + r['path']: hashes(resource(
            directory if r['from'] == 'source' or r['path'] in config['copies'] else output, r['path'])) for r in rows},
    }


def current_packaging(directory, model, *, hashes=None):
    hashes = hashes if hashes is not None else DigestCache()
    config = configuration(directory, model)
    output = output_directory(directory)
    report = json.loads(resource(output, 'packaging-validation.json').read_text(encoding='utf-8'))
    if not isinstance(report, dict):
        raise ValueError('无效公共阶段报告')
    expected = fingerprints(directory, model, output, config, hashes=hashes)
    if (report.get('version') != 1 or report.get('model') != model['id']
            or report.get('fingerprints') != expected
            or report.get('outputs') != {n: hashes(resource(output, n)) for n in sorted(outputs(config))}):
        raise ValueError('打包校验过期，请运行 build')
    return report


def package(directory, model, output):
    config = configuration(directory, model)
    geometry = json.loads(resource(output, 'validation.json').read_text(encoding='utf-8'))['outputs']
    if outputs(config) & set(geometry):
        raise ValueError('公共产物不能覆盖几何资源')
    before = fingerprints(directory, model, output, config)
    for name in config['copies']:
        dest = output / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(resource(directory, name), dest)
    bundle = config['bundle']
    if bundle:
        destination = output / bundle['file']
        destination.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for row in sorted(bundle['files'], key=lambda r: r['path']):
                entry = zipfile.ZipInfo(row['path'], date_time=(2022, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, resource(directory if row['from'] == 'source' else output,
                                                row['path']).read_bytes(), compresslevel=9)
    if before != fingerprints(directory, model, output, configuration(directory, model)):
        raise ValueError('打包期间输入已改变')
    report = {'version': 1, 'model': model['id'], 'fingerprints': before,
              'outputs': {n: digest(resource(output, n)) for n in sorted(outputs(config))}}
    (output / 'packaging-validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
