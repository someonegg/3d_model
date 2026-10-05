"""Catalog generation, static staging and site publication."""

import json
import shutil

from .gltf import output_model
from .resources import (
    DigestCache,
    discover,
    output_directory,
    published_assets,
    published_resource,
    resource,
    variant_config,
)
from .bundling import current_packaging
from .validation import current_report
from .workspace import publish_workspace, replace_directory


def catalog(root, strict=False):
    result = []
    hashes = DigestCache()
    for directory, model in discover(root):
        model = output_model(model)
        entry = {
            key: model[key]
            for key in (
                "id",
                "name",
                "description",
                "purpose",
                "units",
                "up",
                "variants",
                "preview",
                "readme",
            )
        }
        if "assembly" in model:
            entry["assembly"] = model["assembly"]
        entry["variants"] = [
            variant | variant_config(model, variant) for variant in model["variants"]
        ]
        entry["base"] = f"models/{model['id']}/"
        try:
            report = current_report(directory, model, hashes=hashes)
            current_packaging(directory, model, hashes=hashes)
            entry["validation"] = {
                "files": [
                    {
                        key: row[key]
                        for key in (
                            "file",
                            "dimensions",
                            "triangles",
                            "bytes",
                            "components",
                            "passed",
                        )
                    }
                    for row in report["files"]
                ]
            }
        except (ValueError, KeyError, TypeError, OSError):
            if strict:
                raise
            entry["validation"] = None
        names = published_assets(directory, model, strict=strict)
        revisions = {}
        revision_files = [v["file"] for v in model["variants"]]
        if "assembly" in model:
            revision_files.append(model["assembly"])
        for filename in revision_files:
            try:
                revisions[filename] = hashes(
                    resource(output_directory(directory), filename)
                )
            except ValueError:
                if strict:
                    raise
                revisions[filename] = "missing"
        entry["assets"] = sorted(names)
        entry["revisions"] = revisions
        result.append(entry)
    return result


def require_replaceable_site(target):
    if (
        target.exists()
        and any(target.iterdir())
        and not (target / "catalog.json").is_file()
    ):
        raise ValueError("站点输出目录非空且不是已有站点")


def site(root, target):
    root, target = root.resolve(), target.resolve()
    index = catalog(root, strict=True)
    if not index:
        raise ValueError(f"模型库为空，不能发布站点：{root / 'models'}")
    if target == root or target in root.parents:
        raise ValueError("站点输出目录不能覆盖源码目录")
    if target == root / "models" or target.is_relative_to(root / "models"):
        raise ValueError("站点输出目录不能覆盖模型目录")
    if target == root / "build" or target.is_relative_to(root / "build"):
        raise ValueError("站点输出不能覆盖模型产物")
    require_replaceable_site(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with publish_workspace(target, ".site-build-") as work:
        staged = work / "staged"
        staged.mkdir()
        for entry in index:
            directory = root / "models" / entry["id"]
            model = json.loads((directory / "model.json").read_text(encoding="utf-8"))
            for name in entry["assets"]:
                dest = staged / "models" / entry["id"] / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(published_resource(directory, model, name), dest)
        (staged / "catalog.json").write_text(
            json.dumps(index, ensure_ascii=False), encoding="utf-8"
        )
        replace_directory(staged, target, work / "backup")


def publish_site(staged, target):
    """Atomically move a complete staged site into its deployment directory."""
    staged, target = staged.resolve(), target.resolve()
    if not staged.is_dir():
        raise ValueError(f"站点暂存目录不存在：{staged}")
    if (
        staged == target
        or staged.is_relative_to(target)
        or target.is_relative_to(staged)
    ):
        raise ValueError("站点暂存目录与发布目录不能重叠")
    for name in ("catalog.json", "index.html"):
        if not (staged / name).is_file():
            raise ValueError(f"站点暂存目录缺少：{name}")
    require_replaceable_site(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with publish_workspace(target, ".site-publish-") as work:
        replace_directory(staged, target, work / "backup")
