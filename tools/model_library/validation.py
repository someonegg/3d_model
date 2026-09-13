import json
import numpy as np
import trimesh
from .resources import dependencies, digest, resource, input_hashes


def inspect(path, purpose):
    scene = trimesh.load(path, force='scene', process=False)
    meshes = scene.dump()
    if not len(meshes):
        raise ValueError('模型为空')
    mesh = trimesh.util.concatenate(meshes)
    if not len(mesh.faces) or not np.isfinite(mesh.vertices).all():
        raise ValueError('模型为空或包含无效坐标')
    # STL duplicates vertices by design. Merge exact coordinates only; do not repair faces.
    vertices, inverse = np.unique(mesh.vertices, axis=0, return_inverse=True)
    mesh = trimesh.Trimesh(vertices=vertices, faces=inverse[mesh.faces], process=False)
    degenerate = int(np.count_nonzero(mesh.area_faces <= 1e-12))
    edges = mesh.edges_sorted
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    closed = bool(np.all(counts == 2))
    parts = mesh.split(only_watertight=False, repair=False)
    volumes = [float(part.volume) for part in parts]
    result = {'sha256': digest(path), 'dimensions': mesh.extents.tolist(), 'triangles': len(mesh.faces),
              'bytes': path.stat().st_size, 'degenerate_faces': degenerate, 'closed_manifold_edges': closed,
              'consistent_winding': bool(mesh.is_winding_consistent), 'components': len(parts),
              'signed_volume': float(mesh.volume), 'component_volumes': volumes}
    result['passed'] = purpose == 'display' or (closed and result['consistent_winding'] and degenerate == 0 and bool(volumes) and all(v > 0 for v in volumes))
    return result


def validation_config(model):
    return {key: model[key] for key in ('purpose', 'units', 'up')} | {
        'files': sorted({v['file'] for v in model['variants']})}


def inspect_models(directory, model):
    reports = []
    for variant in model['variants']:
        deps = dependencies(directory, variant['file'])
        result = inspect(resource(directory, variant['file']), model['purpose'])
        result.update(file=variant['file'], resources={name: digest(resource(directory, name)) for name in sorted(deps)})
        reports.append(result)
    if not all(r['passed'] for r in reports):
        raise ValueError(f"{model['id']} 校验失败")
    return reports


def finish_validation(directory, model, reports, inputs, write=True):
    # Reuse geometry measurements only while the exact files and dependencies remain unchanged.
    for row in reports:
        hashes = {name: digest(resource(directory, name)) for name in dependencies(directory, row['file'])}
        if hashes != row['resources']:
            raise ValueError('专项验收修改了已校验模型或其依赖')
    report = {'version': 1, 'model': model['id'], 'units': model['units'], 'files': reports,
              'config': validation_config(model), 'inputs': inputs}
    if model.get('artifacts'):
        report['artifacts'] = {name: digest(resource(directory, name)) for name in model['artifacts']}
    if write:
        (directory / 'validation.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if not all(r['passed'] for r in reports):
        raise ValueError(f"{model['id']} 校验失败")
    return report


def current_report(directory, model):
    report = json.loads(resource(directory, 'validation.json').read_text(encoding='utf-8'))
    if not isinstance(report, dict):
        raise ValueError('请重新校验模型')
    if report.get('version') != 1 or report.get('model') != model['id'] or report.get('config') != validation_config(model):
        raise ValueError('请重新校验模型')
    if report.get('inputs', {}) != input_hashes(directory, model):
        raise ValueError('构建输入已改变，请运行 models:build')
    rows = {r['file']: r for r in report['files']}
    for variant in model['variants']:
        row = rows.get(variant['file'], {})
        hashes = {name: digest(resource(directory, name)) for name in dependencies(directory, variant['file'])}
        if not row.get('passed') or row.get('resources') != hashes:
            raise ValueError(f"{model['id']} 校验过期或未通过")
    artifacts = {name: digest(resource(directory, name)) for name in model.get('artifacts', [])}
    if report.get('artifacts', {}) != artifacts:
        raise ValueError(f"{model['id']} 附加产物校验过期")
    return report
