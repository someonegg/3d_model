import json

import numpy as np
import trimesh

from .resources import (
    dependencies,
    DigestCache,
    generated_assets,
    input_hashes,
    output_directory,
    resource,
    variant_config,
)


def inspect(path, purpose, *, hashes=None):
    hashes = hashes if hashes is not None else DigestCache()
    scene = trimesh.load(path, force="scene", process=False)
    meshes = scene.dump()
    if not len(meshes):
        raise ValueError("模型为空")
    mesh = trimesh.util.concatenate(meshes)
    if not len(mesh.faces) or not np.isfinite(mesh.vertices).all():
        raise ValueError("模型为空或包含无效坐标")
    # STL duplicates vertices by design. Merge exact coordinates only; do not repair faces.
    vertices, inverse = np.unique(mesh.vertices, axis=0, return_inverse=True)
    mesh = trimesh.Trimesh(vertices=vertices, faces=inverse[mesh.faces], process=False)
    degenerate = int(np.count_nonzero(mesh.area_faces <= 1e-12))
    edges = mesh.edges_sorted
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    closed = bool(np.all(counts == 2))
    parts = mesh.split(only_watertight=False, repair=False)
    volumes = [float(part.volume) for part in parts]
    result = {
        "sha256": hashes(path),
        "dimensions": mesh.extents.tolist(),
        "triangles": len(mesh.faces),
        "bytes": path.stat().st_size,
        "degenerate_faces": degenerate,
        "closed_manifold_edges": closed,
        "consistent_winding": bool(mesh.is_winding_consistent),
        "components": len(parts),
        "signed_volume": float(mesh.volume),
        "component_volumes": volumes,
    }
    result["passed"] = purpose == "display" or (
        closed
        and result["consistent_winding"]
        and degenerate == 0
        and bool(volumes)
        and all(v > 0 for v in volumes)
    )
    return result


def validation_config(model):
    return {key: model[key] for key in ("purpose", "units", "up")} | {
        "files": sorted({v["file"] for v in model["variants"]}),
        "variants": sorted(
            [
                {"file": variant["file"], **variant_config(model, variant)}
                for variant in model["variants"]
            ],
            key=lambda row: row["file"],
        ),
    }


def inspect_models(directory, model):
    hashes = DigestCache()
    reports = []
    for variant in model["variants"]:
        deps = dependencies(directory, variant["file"])
        config = variant_config(model, variant)
        result = inspect(resource(directory, variant["file"]), config["purpose"], hashes=hashes)
        result.update(config)
        result.update(
            file=variant["file"],
            resources={
                name: hashes(resource(directory, name)) for name in sorted(deps)
            },
        )
        reports.append(result)
    if not all(r["passed"] for r in reports):
        raise ValueError(f"{model['id']} 校验失败")
    return reports


def finish_validation(directory, model, reports, inputs):
    file_hashes = DigestCache()
    # Reuse geometry measurements only while the exact files and dependencies remain unchanged.
    for row in reports:
        hashes = {
            name: file_hashes(resource(directory, name))
            for name in dependencies(directory, row["file"])
        }
        if hashes != row["resources"]:
            raise ValueError("专项验收修改了已校验模型或其依赖")
    report = {
        "version": 2,
        "model": model["id"],
        "units": model["units"],
        "files": reports,
        "config": validation_config(model),
        "inputs": inputs,
    }
    report["outputs"] = {
        name: file_hashes(resource(directory, name))
        for name in sorted(generated_assets(directory, model) - {"validation.json"})
    }
    (directory / "validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not all(r["passed"] for r in reports):
        raise ValueError(f"{model['id']} 校验失败")
    return report


def current_report(directory, model, inputs=None, *, hashes=None):
    file_hashes = hashes if hashes is not None else DigestCache()
    from .gltf import output_model

    model = output_model(model)
    from .bundling import configuration, outputs
    model = model | {"bundle_outputs": sorted(outputs(configuration(directory, model)))}
    source = directory
    directory = output_directory(source)
    report = json.loads(
        resource(directory, "validation.json").read_text(encoding="utf-8")
    )
    if not isinstance(report, dict):
        raise ValueError("请运行 build")
    if (
        report.get("version") != 2
        or report.get("model") != model["id"]
        or report.get("config") != validation_config(model)
    ):
        raise ValueError("请运行 build")
    if report.get("inputs", {}) != (
        inputs if inputs is not None else input_hashes(source, model)
    ):
        raise ValueError("构建输入已改变，请运行 build")
    files = report.get("files")
    if not isinstance(files, list) or any(not isinstance(row, dict) for row in files):
        raise ValueError("无效验收报告")
    rows = {row["file"]: row for row in files}
    if len(rows) != len(files) or set(rows) != {v["file"] for v in model["variants"]}:
        raise ValueError("无效验收报告")
    for row in files:
        for key in ("dimensions", "triangles", "bytes", "components"):
            if key not in row:
                raise ValueError("无效验收报告")
    for variant in model["variants"]:
        row = rows.get(variant["file"], {})
        hashes = {
            name: file_hashes(resource(directory, name))
            for name in dependencies(directory, variant["file"])
        }
        if not row.get("passed") or row.get("resources") != hashes:
            raise ValueError(f"{model['id']} 校验过期或未通过")
    outputs = {
        name: file_hashes(resource(directory, name))
        for name in sorted(generated_assets(directory, model) - {"validation.json"})
    }
    if report.get("outputs") != outputs:
        raise ValueError(f"{model['id']} 产物校验过期")
    return report
