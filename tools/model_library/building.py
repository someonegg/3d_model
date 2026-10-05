import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .gltf import normalize
from .resources import (
    build_order,
    builder_path,
    discover,
    generated_assets,
    input_hashes,
    output_directory,
    published_assets,
    resource,
)
from .bundling import configuration, outputs, current_packaging, package
from .validation import current_report, finish_validation, inspect_models
from .workspace import publish_workspace, replace_directory


def verifier_path(directory, model):
    if not model.get("verify"):
        return None
    if not model.get("build") or model["verify"] not in model.get("inputs", []):
        raise ValueError("verify 需要 build 且必须声明为 inputs")
    return resource(directory, model["verify"])


def run_model(script, directory, output):
    runner = Path(__file__).resolve().parents[1] / "run_model.py"
    subprocess.run(
        [sys.executable, str(runner), str(script)],
        cwd=directory,
        env=dict(
            os.environ,
            MODEL_OUTPUT_DIR=str(output.resolve()),
            PYTHONDONTWRITEBYTECODE="1",
        ),
        check=True,
    )


def accept(output, directory, model, initial_inputs):
    """Shared acceptance for generated files and copies of existing files."""
    verifier = verifier_path(directory, model)
    reports = inspect_models(output, model)
    if verifier:
        run_model(verifier, directory, output)
    return finish_validation(output, model, reports, initial_inputs)


def build(directory, model, force=False):
    directory = directory.resolve()
    builder = builder_path(directory, model)
    for dependency in model.get("depends_on", []):
        source = directory.parent / dependency
        current_report(
            source, json.loads((source / "model.json").read_text(encoding="utf-8"))
        )
    config = configuration(directory, model)
    model = model | {"bundle_outputs": sorted(outputs(config))}
    initial_inputs = input_hashes(directory, model)
    geometry_current = False
    if not force:
        try:
            current_report(directory, model, inputs=initial_inputs)
            geometry_current = True
        except (ValueError, KeyError, TypeError, OSError):
            pass
    if geometry_current:
        try:
            current_packaging(directory, model)
        except (ValueError, KeyError, TypeError, OSError):
            target = output_directory(directory)
            with publish_workspace(target, ".model-bundle-") as work:
                staged = work / "output"
                shutil.copytree(target, staged)
                try:
                    previous = json.loads((staged / 'packaging-validation.json').read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    previous = {}
                if not isinstance(previous, dict) or not isinstance(previous.get("outputs", {}), dict):
                    previous = {}
                protected = generated_assets(staged, model) | published_assets(directory, model, strict=False)
                for name in previous.get('outputs', {}):
                    if name not in outputs(config) and name not in protected:
                        candidate = (staged / name).resolve()
                        if candidate.is_relative_to(staged.resolve()) and candidate.is_file():
                            candidate.unlink()
                package(directory, model, staged)
                current_report(directory, model, inputs=initial_inputs)
                if input_hashes(directory, model) != initial_inputs:
                    raise ValueError("打包期间构建输入已改变")
                replace_directory(staged, target, work / "backup")
            return True
        return False
    target = output_directory(directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    with publish_workspace(target, ".model-build-") as work:
        output = work / "output"
        output.mkdir()
        run_model(builder, directory, output)
        model = normalize(output, model)
        accept(output, directory, model, initial_inputs)
        for name in generated_assets(output, model):
            resource(output, name)
        package(directory, model, output)
        if input_hashes(directory, model) != initial_inputs:
            raise ValueError("构建期间输入已改变")
        replace_directory(output, target, work / "backup")
    return True


def build_library(root, force=False):
    for directory, model in build_order(discover(root)):
        changed = build(directory, model, force=force)
        print(f"build: {model['id']} {'完成' if changed else '跳过'}", flush=True)
