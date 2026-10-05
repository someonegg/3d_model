"""Small manifests and report fixtures for isolated tool tests."""
import json

def write_manifest(directory, model=None):
    if model is None:
        model = dict(id=directory.name, name='测试模型', purpose='print', units='mm', up='Z',
                     preview='preview.png', readme='README.md',
                     variants=[dict(id='main', name='模型', file='mesh.stl')])
    (directory / 'model.json').write_text(json.dumps(model))
    return model
