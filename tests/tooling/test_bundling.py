import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import trimesh
from tools.model_library.bundling import configuration, current_packaging
from tools.model_library.building import build
from tools.model_library.publication import catalog
from tools.model_library.resources import output_directory, input_hashes


class BundleTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2] / 'tmp/tests'
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.library = Path(self.temp.name)
        self.directory = self.library / 'models/example'
        self.directory.mkdir(parents=True)
        self.model = dict(id='example', name='test', description='test', purpose='print', units='mm', up='Z',
                          variants=[dict(id='main', name='main', file='mesh.stl')],
                          preview='preview.png', readme='README.md', build='build.py',
                          inputs=['build.py'], bundle='bundle.json', publish=['print-files.zip', {'from':'source', 'path':'notes.md'}])
        (self.directory / 'model.json').write_text(json.dumps(self.model))
        (self.directory / 'build.py').write_text('# fixture')
        (self.directory / 'README.md').write_text('readme')
        (self.directory / 'notes.md').write_text('notes')
        self.config = dict(file='print-files.zip', files=[dict(path='mesh.stl', **{'from': 'output'}),
            dict(path='README.md', **{'from': 'source'}),
            dict(path='notes.md', **{'from': 'source'})])
        self.write_config()
        self.calls = 0

    def write_config(self):
        (self.directory / 'bundle.json').write_text(json.dumps(self.config))

    def generate(self, script, directory, output):
        self.calls += 1
        trimesh.creation.box().export(output / 'mesh.stl')
        (output / 'preview.png').write_bytes(b'preview')

    def run_build(self, **kwargs):
        with patch('tools.model_library.building.run_model', side_effect=self.generate):
            return build(self.directory, self.model, **kwargs)

    def test_cache_determinism_and_independent_recovery(self):
        self.assertTrue(self.run_build())
        self.assertNotIn('@tools/model_library/bundling.py', input_hashes(self.directory, self.model))
        target = output_directory(self.directory)
        geometry = (target / 'validation.json').read_bytes()
        original = (target / 'print-files.zip').read_bytes()
        with zipfile.ZipFile(target / 'print-files.zip') as archive:
            self.assertEqual(archive.namelist(), ['README.md', 'mesh.stl', 'notes.md'])
            self.assertEqual(archive.read('README.md'), b'readme')
        self.assertFalse(self.run_build())
        (target / 'print-files.zip').write_bytes(b'broken')
        with self.assertRaises(ValueError):
            catalog(self.library, strict=True)
        self.assertTrue(self.run_build())
        self.assertEqual((target / 'print-files.zip').read_bytes(), original)
        for filename in ('README.md', 'notes.md'):
            (self.directory / filename).write_text('updated')
            self.assertTrue(self.run_build())
            self.assertEqual((target / 'validation.json').read_bytes(), geometry)
        self.config['files'].reverse()
        self.write_config()
        previous = (target / 'print-files.zip').read_bytes()
        self.assertTrue(self.run_build())
        self.assertEqual((target / 'print-files.zip').read_bytes(), previous)
        self.assertEqual(self.calls, 1)
        (self.directory / 'build.py').write_text('# changed')
        self.assertTrue(self.run_build())
        self.assertEqual(self.calls, 2)
        current_packaging(self.directory, self.model)
        self.assertTrue(self.run_build(force=True))
        self.assertEqual(self.calls, 3)

    def test_illegal_and_missing_inputs(self):
        for row in (dict(path='../escape', **{'from':'source'}),
                    dict(path='/absolute', **{'from':'source'}),
                    dict(path='print-files.zip', **{'from':'output'}),
                    dict(path='README.md', **{'from':'unknown'}),
                    dict(path='README.md', **{'from':'source'}),
                    dict(path='missing.md', **{'from':'source'})):
            with self.subTest(row=row):
                original = list(self.config['files'])
                self.config['files'].append(row)
                self.write_config()
                with self.assertRaises(ValueError):
                    configuration(self.directory, self.model)
                self.config['files'] = original
        self.config['files'].append(dict(path='missing.stl', **{'from':'output'}))
        self.write_config()
        with self.assertRaises(ValueError):
            self.run_build()
        self.assertFalse(output_directory(self.directory).exists())

    def test_failed_repack_preserves_every_previous_output(self):
        self.run_build()
        output = output_directory(self.directory)
        before = {p.name:p.read_bytes() for p in output.iterdir()}
        (self.directory / 'notes.md').write_text('changed')
        with patch('tools.model_library.bundling.zipfile.ZipFile.writestr', side_effect=OSError('failed')):
            with self.assertRaisesRegex(OSError, 'failed'):
                self.run_build()
        self.assertEqual({p.name:p.read_bytes() for p in output.iterdir()}, before)
        self.assertEqual(self.calls, 1)

    def save_model(self):
        (self.directory / 'model.json').write_text(json.dumps(self.model))

    def test_copy_without_zip_and_recover_corruption(self):
        self.model.pop('bundle')
        self.model['publish'] = [{'from': 'source', 'path': 'notes.md'}]
        self.save_model()
        self.run_build()
        output = output_directory(self.directory)
        geometry = (output / 'validation.json').read_bytes()
        self.assertEqual((output / 'README.md').read_text(), 'readme')
        self.assertEqual((output / 'notes.md').read_text(), 'notes')
        self.assertFalse((output / 'print-files.zip').exists())
        for name in ('notes.md', 'README.md'):
            (output / name).write_text('broken')
            with self.assertRaises(ValueError):
                catalog(self.library, strict=True)
            self.assertTrue(self.run_build())
            self.assertEqual((output / 'validation.json').read_bytes(), geometry)
        self.assertEqual(self.calls, 1)
        current_packaging(self.directory, self.model)

    def test_configuration_changes_remove_only_recorded_products(self):
        self.run_build()
        output = output_directory(self.directory)
        (output / 'unrelated.txt').write_text('retain')
        self.model.pop('bundle')
        self.model['publish'] = []
        self.save_model()
        self.assertTrue(self.run_build())
        self.assertFalse((output / 'notes.md').exists())
        self.assertFalse((output / 'print-files.zip').exists())
        self.assertEqual((output / 'unrelated.txt').read_text(), 'retain')
        self.assertEqual(self.calls, 1)
        self.model['publish'] = [{'from': 'source', 'path': 'notes.md'}]
        self.save_model()
        self.assertTrue(self.run_build())
        self.assertEqual(self.calls, 1)

    def test_copy_failure_and_changing_inputs_preserve_previous_output(self):
        self.run_build()
        output = output_directory(self.directory)
        before = {p.name: p.read_bytes() for p in output.iterdir()}
        (self.directory / 'notes.md').write_text('changed')
        import shutil
        original = shutil.copy2
        def changing_copy(src, dst, *args, **kwargs):
            result = original(src, dst, *args, **kwargs)
            if Path(src) == self.directory / 'notes.md':
                Path(src).write_text('changed again')
            return result
        with patch('tools.model_library.bundling.shutil.copy2', side_effect=changing_copy):
            with self.assertRaisesRegex(ValueError, '输入已改变'):
                self.run_build()
        self.assertEqual({p.name: p.read_bytes() for p in output.iterdir()}, before)
        with patch('tools.model_library.bundling.shutil.copy2', side_effect=OSError('copy failed')):
            with self.assertRaises(OSError):
                self.run_build()
        self.assertEqual({p.name: p.read_bytes() for p in output.iterdir()}, before)

    def test_bundle_file_requires_exact_fields_and_valid_source(self):
        for item in (None, 'mesh.stl', {},
                     {'from': 'output'},
                     {'path': 'mesh.stl'},
                     {'from': 'output', 'path': 'mesh.stl', 'extra': True},
                     {'from': 'unknown', 'path': 'mesh.stl'}):
            with self.subTest(item=item):
                self.config['files'][0] = item
                self.write_config()
                with self.assertRaisesRegex(ValueError, '打包项必须仅包含 from 和 path'):
                    configuration(self.directory, self.model)

    def test_reject_invalid_copies(self):
        for item in ({'from': 'source', 'path': '../notes.md'},
                     {'from': 'source', 'path': 'mesh.stl'},
                     {'from': 'source', 'path': 'preview.png'},
                     {'from': 'source', 'path': 'README.md'},
                     {'from': 'output', 'path': 'notes.md'},
                     {'from': 'source', 'path': 'src/private.md'}):
            with self.subTest(item=item):
                self.model['publish'] = ['print-files.zip', item]
                with self.assertRaises(ValueError):
                    configuration(self.directory, self.model)

    def test_zip_can_use_copied_output_and_declared_source_geometry_input(self):
        self.config['files'][-1]['from'] = 'output'
        self.write_config()
        self.run_build()
        (self.directory / 'notes.md').write_text('new notes')
        self.assertTrue(self.run_build())
        self.assertEqual(self.calls, 1)
        with zipfile.ZipFile(output_directory(self.directory) / 'print-files.zip') as archive:
            self.assertEqual(archive.read('notes.md'), b'new notes')
        self.model['inputs'].append('notes.md')
        self.save_model()
        self.assertTrue(self.run_build())
        (self.directory / 'notes.md').write_text('geometry input changed')
        self.assertTrue(self.run_build())
        self.assertEqual(self.calls, 3)

    def test_nested_image_copy_and_readme_path_change_without_zip(self):
        self.model.pop('bundle')
        self.model['publish'] = [{'from': 'source', 'path': 'docs/image.png'}]
        (self.directory / 'docs').mkdir()
        (self.directory / 'docs/image.png').write_bytes(b'image')
        self.save_model()
        self.run_build()
        output = output_directory(self.directory)
        self.assertEqual((output / 'docs/image.png').read_bytes(), b'image')
        (self.directory / 'docs/guide.md').write_text('new readme')
        self.model['readme'] = 'docs/guide.md'
        self.save_model()
        self.assertTrue(self.run_build())
        self.assertEqual((output / 'docs/guide.md').read_text(), 'new readme')
        self.assertFalse((output / 'README.md').exists())
        self.assertEqual(self.calls, 1)
