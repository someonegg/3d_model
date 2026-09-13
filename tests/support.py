"""Small manifests and report fixtures for isolated tool tests."""
import json

import trimesh
from PIL import Image
from tools.model_library.resources import input_hashes
from tools.model_library.validation import inspect_models, finish_validation


def seed_validation_report(directory, model):
    """Seed a prior report for fixtures; deliberately skip specialized acceptance.

    Exercise pipeline.validate or build when testing the validation workflow.
    """
    return finish_validation(directory, model, inspect_models(directory, model),
                             input_hashes(directory, model))


def write_manifest(directory, model=None):
    if model is None:
        model = dict(id=directory.name, name='测试模型', purpose='print', units='mm', up='Z',
                     preview='preview.png', readme='README.md',
                     variants=[dict(id='main', name='模型', file='mesh.stl')])
    (directory / 'model.json').write_text(json.dumps(model))
    return model


def write_box_model(directory, *, readme='fixture'):
    """Create a minimal model; callers explicitly seed or validate its report."""
    model = write_manifest(directory)
    trimesh.creation.box().export(directory / 'mesh.stl')
    Image.new('RGB', (2, 2)).save(directory / 'preview.png')
    (directory / 'README.md').write_text(readme)
    return model
