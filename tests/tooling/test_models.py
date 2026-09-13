import json
import errno
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
import shutil
from types import SimpleNamespace
import numpy as np
import trimesh
from PIL import Image

from tools.model_library.pipeline import build, catalog, publish_site, site, publish_workspace, replace_directory, validate
from tools.model_library.resources import builder_path, dependencies, discover, resource
from tools.model_library.validation import current_report, inspect
from tests.support import write_manifest, seed_validation_report


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path(__file__).resolve().parents[2] / 'tmp'
        test_root = self.temp_root / 'tests'
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.library = Path(self.temp.name)
        self.root = self.library / 'example'
        self.root.mkdir()
        self.path = self.root / 'mesh.stl'

    def tearDown(self):
        self.temp.cleanup()

    def check_mesh(self, mesh, purpose='print'):
        mesh.export(self.path)
        return inspect(self.path, purpose)

    def test_closed_and_open(self):
        mesh = trimesh.creation.box()
        self.assertTrue(self.check_mesh(mesh)['passed'])
        mesh.update_faces(np.arange(len(mesh.faces) - 1))
        self.assertFalse(self.check_mesh(mesh)['passed'])
        self.assertTrue(self.check_mesh(mesh, 'display')['passed'])

    def test_reversed_and_multiple_components(self):
        mesh = trimesh.creation.box()
        mesh.invert()
        self.assertFalse(self.check_mesh(mesh)['passed'])
        good = trimesh.creation.box()
        other = good.copy()
        other.apply_translation([3, 0, 0])
        report = self.check_mesh(trimesh.util.concatenate([good, other]))
        self.assertTrue(report['passed'])
        self.assertEqual(report['components'], 2)
        other.invert()
        self.assertFalse(self.check_mesh(trimesh.util.concatenate([good, other]))['passed'])

    def test_degenerate_and_corrupt(self):
        mesh = trimesh.creation.box()
        mesh.faces = np.vstack([mesh.faces, [0, 0, 1]])
        self.assertFalse(self.check_mesh(mesh)['passed'])
        self.path.write_bytes(b'broken')
        with self.assertRaises(Exception):
            inspect(self.path, 'print')

    def test_stale_report(self):
        self.check_mesh(trimesh.creation.box())
        model = dict(id='example', units='mm', up='Z', purpose='print', variants=[dict(id='main', file='mesh.stl')], preview='preview.png', readme='README.md')
        for name in ['preview.png', 'README.md']:
            (self.root / name).write_text('fixture')
        write_manifest(self.root, model)
        validate(self.root, model)
        current_report(self.root, model)
        self.check_mesh(trimesh.creation.box(extents=[2, 2, 2]))
        with self.assertRaises(ValueError):
            current_report(self.root, model)

    def test_paths_and_missing_dependencies(self):
        with self.assertRaises(ValueError):
            resource(self.root, '../outside')
        (self.root / 'mesh.gltf').write_text(json.dumps({'buffers': [{'uri': 'missing.bin'}]}))
        with self.assertRaises(ValueError):
            dependencies(self.root, 'mesh.gltf')

    def test_build_commits_external_gltf_resources(self):
        model = dict(id='example', units='m', up='Y', purpose='display',
                     variants=[dict(id='main', file='meshes/model.gltf')],
                     build='build.py', preview='preview.png',
                     readme='README.md', inputs=['build.py'])
        write_manifest(self.root, model)
        (self.root / 'README.md').write_text('fixture')
        Image.new('RGB', (2, 2), '#286ecb').save(self.root / 'reference.png')
        (self.root / 'build.py').write_text('''from pathlib import Path
import json
import os
from PIL import Image
import trimesh

output = Path(os.environ['MODEL_OUTPUT_DIR'])
meshes = output / 'meshes'
meshes.mkdir()
scene = trimesh.Scene(trimesh.creation.box())
for name, data in scene.export(file_type='gltf').items():
    (meshes / name).write_bytes(data)
image = Image.open(Path(__file__).resolve().parent / 'reference.png')
(output / 'textures').mkdir()
image.save(output / 'textures/color.png')
image.save(output / 'preview.png')
gltf = json.loads((meshes / 'model.gltf').read_text())
gltf['images'] = [{'uri': '../textures/color.png'}]
(meshes / 'model.gltf').write_text(json.dumps(gltf))
''')
        # An existing stale buffer must be replaced, not reused after validation.
        (self.root / 'meshes').mkdir()
        stale_buffer = self.root / 'meshes/gltf_buffer_0.bin'
        stale_buffer.write_bytes(b'old buffer')
        build(self.root, model)
        resources = dependencies(self.root, 'meshes/model.gltf')
        self.assertIn('textures/color.png', resources)
        self.assertIn('meshes/gltf_buffer_0.bin', resources)
        self.assertNotEqual(stale_buffer.read_bytes(), b'old buffer')
        report = current_report(self.root, model)
        self.assertEqual(set(report['files'][0]['resources']), resources)
        self.assertTrue(inspect(self.root / 'meshes/model.gltf', 'display')['passed'])
        staging = self.library / 'tmp/site'
        site(self.library, staging)
        published = staging / 'models' / model['id']
        files = {str(path.relative_to(published)) for path in published.rglob('*') if path.is_file()}
        self.assertEqual(files, resources | {'preview.png', 'README.md', 'validation.json'})
        for name in resources:
            self.assertEqual((published / name).read_bytes(), (self.root / name).read_bytes())

    def test_failed_build_preserves_output(self):
        self.path.write_bytes(b'previous output')
        (self.root / 'build.py').write_text('raise RuntimeError("expected failure")')
        model = dict(id='example', build='build.py', inputs=['build.py'],
                     variants=[dict(file='mesh.stl')])
        run = subprocess.run
        def quiet_run(args, **kwargs):
            return run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        with patch('tools.model_library.pipeline.subprocess.run', side_effect=quiet_run):
            with self.assertRaises(Exception):
                build(self.root, model)
        self.assertEqual(self.path.read_bytes(), b'previous output')

    def test_build_artifacts_are_staged_and_checked_for_freshness(self):
        model = dict(id='example', purpose='print', units='mm', up='Z',
                     build='build.py', preview='preview.png', readme='README.md',
                     variants=[dict(id='main', file='mesh.stl')],
                     inputs=['build.py'], artifacts=['details.json'])
        (self.root / 'README.md').write_text('Example')
        (self.root / 'build.py').write_text('''
import os
from pathlib import Path
import trimesh
from PIL import Image
out = Path(os.environ['MODEL_OUTPUT_DIR'])
trimesh.creation.box().export(out / 'mesh.stl')
Image.new('RGB', (4, 4)).save(out / 'preview.png')
(out / 'details.json').write_text('{"passed":true}')
''')
        build(self.root, model)
        current_report(self.root, model)
        write_manifest(self.root, model)
        staging = self.library / 'tmp/site'
        site(self.library, staging)
        entry = catalog(self.library, strict=True)[0]
        self.assertIn('details.json', entry['assets'])
        published = staging / 'models/example'
        self.assertEqual(set(entry['assets']), {str(p.relative_to(published)) for p in published.rglob('*') if p.is_file()})
        self.assertEqual((published / 'details.json').read_bytes(),
                         (self.root / 'details.json').read_bytes())
        (self.root / 'details.json').write_text('changed')
        with self.assertRaisesRegex(ValueError, '附加产物校验过期'):
            current_report(self.root, model)
        before = self.path.read_bytes()
        model['artifacts'].append('missing.json')
        with self.assertRaisesRegex(ValueError, '缺失或越界资源'):
            build(self.root, model)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual((self.root / 'details.json').read_text(), 'changed')

    def test_reject_invalid_artifact_paths(self):
        directory = self.root
        model = dict(id='example', purpose='print', units='mm', up='Z',
                     preview='preview.png', readme='README.md',
                     variants=[dict(id='main', file='mesh.stl')])
        for value in ('details.json', [None], [''], ['../escape'], ['/tmp/escape']):
            with self.subTest(artifacts=value):
                model['artifacts'] = value
                write_manifest(directory, model)
                with self.assertRaisesRegex(ValueError, '无效附加产物路径'):
                    discover(self.library)

    def test_legacy_reports_leave_catalog_available(self):
        self.check_mesh(trimesh.creation.box())
        for name in ('preview.png', 'README.md'):
            (self.root / name).write_text('fixture')
        model = dict(id='example', units='mm', up='Z', purpose='print',
                     variants=[dict(id='main', file='mesh.stl')],
                     preview='preview.png', readme='README.md')
        for legacy in ([], [{'file': 'mesh.stl'}], {'triangles': 12}, None):
            with self.subTest(report=legacy):
                (self.root / 'validation.json').write_text(json.dumps(legacy))
                write_manifest(self.root, model)
                self.assertIsNone(catalog(self.library)[0]['validation'])
                with self.assertRaises(ValueError):
                    catalog(self.library, strict=True)
        validate(self.root, model)
        self.assertTrue(current_report(self.root, model)['files'][0]['passed'])

    def test_mixed_case_formats_and_dependencies(self):
        directory = self.root
        for name in ('preview.png', 'README.md'):
            (directory / name).write_text('fixture')
        scene = trimesh.Scene(trimesh.creation.box())
        for name, data in scene.export(file_type='gltf').items():
            (directory / ('mesh.GlTf' if name == 'model.gltf' else name)).write_bytes(data)
        (directory / 'mesh.GLB').write_bytes(scene.export(file_type='glb'))
        (directory / 'mesh.STL').write_bytes(trimesh.creation.box().export(file_type='stl'))
        for filename in ('mesh.STL', 'mesh.GlTf', 'mesh.GLB'):
            with self.subTest(filename=filename):
                model = dict(id='example', units='mm' if filename.endswith('STL') else 'm',
                             up='Z' if filename.endswith('STL') else 'Y',
                             purpose='print' if filename.endswith('STL') else 'display',
                             variants=[dict(id='main', file=filename)],
                             preview='preview.png', readme='README.md')
                write_manifest(directory, model)
                self.assertEqual(len(discover(self.library)), 1)
                self.assertTrue(validate(directory, model)['files'][0]['passed'])
                if filename.endswith('GlTf'):
                    self.assertGreater(len(dependencies(directory, filename)), 1)
                model['units'] = 'invalid'
                write_manifest(directory, model)
                with self.assertRaises(ValueError):
                    discover(self.library)

    def test_site_replaces_stale_assets_and_preserves_output_on_missing_resource(self):
        model = write_manifest(self.root)
        self.check_mesh(trimesh.creation.box())
        Image.new('RGB', (2, 2)).save(self.root / 'preview.png')
        (self.root / 'README.md').write_text('fixture')
        validate(self.root, model)
        target = self.library / 'output'
        site(self.library, target)
        (target / 'obsolete.stl').write_bytes(b'obsolete')
        site(self.library, target)
        self.assertFalse((target / 'obsolete.stl').exists())
        before = (target / 'catalog.json').read_bytes()
        (self.root / 'preview.png').unlink()
        with self.assertRaises(ValueError):
            site(self.library, target)
        self.assertEqual((target / 'catalog.json').read_bytes(), before)

    def test_discovery_ignores_test_and_hidden_directories(self):
        write_manifest(self.root)
        for name in ('.hidden', 'tests', 'tmp'):
            directory = self.library / name
            directory.mkdir()
            (directory / 'model.json').write_text('{}')
        self.assertEqual([model['id'] for _, model in discover(self.library)], ['example'])

    def test_fixture_generation_removes_stale_models(self):
        repo = Path(__file__).resolve().parents[2]
        fixture_root = self.library / 'fixtures'
        stale = fixture_root / 'models/stale/model.json'
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text('{}')
        subprocess.run([sys.executable, str(repo / 'tests/generate_fixtures.py'),
                        '--output', str(fixture_root)], cwd=repo, check=True)
        self.assertFalse(stale.exists())
        self.assertTrue((fixture_root / 'assets/model.glb').is_file())

    def test_cli_uses_explicit_root_and_output(self):
        model = write_manifest(self.root)
        self.check_mesh(trimesh.creation.box())
        Image.new('RGB', (2, 2)).save(self.root / 'preview.png')
        (self.root / 'README.md').write_text('fixture')
        cli = Path(__file__).resolve().parents[2] / 'tools/models.py'
        def run(*args):
            return subprocess.run([sys.executable, str(cli), *args, '--root', str(self.library)],
                                  cwd=self.library, capture_output=True, text=True, check=True)
        run('validate', model['id'])
        index = json.loads(run('catalog').stdout)
        self.assertEqual([entry['id'] for entry in index], ['example'])
        run('site')
        default = self.library / 'tmp/site'
        self.assertEqual(json.loads((default / 'catalog.json').read_text()), index)
        (default / 'index.html').write_text('fixture')
        run('publish')
        self.assertFalse(default.exists())
        self.assertEqual(json.loads((self.library / 'dist/catalog.json').read_text()), index)
        target = self.library / 'custom-site'
        run('site', '--output', str(target))
        self.assertEqual(json.loads((target / 'catalog.json').read_text()), index)
        self.assertFalse((self.library / '.site').exists())

    def test_publish_site_moves_complete_staging_and_replaces_previous_output(self):
        staged = self.library / 'tmp/site'
        staged.mkdir(parents=True)
        (staged / 'catalog.json').write_text('[]')
        (staged / 'index.html').write_text('new')
        (staged / 'models').mkdir()
        target = self.library / 'dist'
        target.mkdir()
        (target / 'catalog.json').write_text('[]')
        (target / 'index.html').write_text('old')
        publish_site(staged, target)
        self.assertFalse(staged.exists())
        self.assertEqual((target / 'index.html').read_text(), 'new')
        self.assertTrue((target / 'models').is_dir())

    def test_publish_site_rejects_incomplete_or_overlapping_staging(self):
        staged = self.library / 'tmp/site'
        staged.mkdir(parents=True)
        (staged / 'catalog.json').write_text('[]')
        with self.assertRaisesRegex(ValueError, 'index.html'):
            publish_site(staged, self.library / 'dist')
        (staged / 'index.html').write_text('new')
        with self.assertRaisesRegex(ValueError, '不能重叠'):
            publish_site(staged, staged / 'dist')

    def test_publish_site_rejects_non_site_target(self):
        staged = self.library / 'tmp/site'
        staged.mkdir(parents=True)
        (staged / 'catalog.json').write_text('[]')
        (staged / 'index.html').write_text('new')
        target = self.library / 'notes'
        target.mkdir()
        note = target / 'keep.txt'
        note.write_text('keep')
        with self.assertRaisesRegex(ValueError, '不是已有站点'):
            publish_site(staged, target)
        self.assertEqual(note.read_text(), 'keep')
        self.assertTrue(staged.is_dir())

    def test_site_rejects_source_and_non_site_output_directories(self):
        model = write_manifest(self.root)
        self.check_mesh(trimesh.creation.box())
        Image.new('RGB', (2, 2)).save(self.root / 'preview.png')
        (self.root / 'README.md').write_text('fixture')
        validate(self.root, model)
        unrelated = self.library / 'notes'
        unrelated.mkdir()
        (unrelated / 'keep.txt').write_text('keep')
        for target in (self.library, self.root, unrelated):
            with self.subTest(target=target), self.assertRaises(ValueError):
                site(self.library, target)
        self.assertEqual((unrelated / 'keep.txt').read_text(), 'keep')
        self.assertTrue((self.root / 'mesh.stl').is_file())

    def test_copy_and_publish_failures_preserve_model_and_site(self):
        model = write_manifest(self.root)
        self.check_mesh(trimesh.creation.box())
        Image.new('RGB', (2, 2)).save(self.root / 'preview.png')
        (self.root / 'README.md').write_text('original')
        (self.root / 'build.py').write_text("from pathlib import Path\nimport os,trimesh\nfrom PIL import Image\np=Path(os.environ['MODEL_OUTPUT_DIR'])\ntrimesh.creation.box(extents=[2,2,2]).export(p/'mesh.stl')\nImage.new('RGB',(2,2),'red').save(p/'preview.png')\n")
        model.update(build='build.py', inputs=['build.py'])
        write_manifest(self.root, model)
        seed_validation_report(self.root, model)
        target = self.library / 'tmp/site'
        site(self.library, target)
        def snapshot(folder):
            return {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob('*') if p.is_file()}
        before_model, before_site = snapshot(self.root), snapshot(target)
        copy = shutil.copy2
        def fail_copy(src, dst, *args, **kwargs):
            if Path(src).name == 'preview.png':
                raise OSError('copy failure')
            return copy(src, dst, *args, **kwargs)
        replace = Path.replace
        def fail_publish(src, dst):
            if src.name == 'staged':
                raise OSError('publish failure')
            return replace(src, dst)
        for action in (lambda: build(self.root, model), lambda: site(self.library, target)):
            for context in (patch('tools.model_library.pipeline.shutil.copy2', side_effect=fail_copy),
                            patch.object(Path, 'replace', fail_publish)):
                with context, self.assertRaises(OSError):
                    action()
                self.assertEqual(snapshot(self.root), before_model)
                self.assertEqual(snapshot(target), before_site)
                current_report(self.root, model)

    def test_labels_do_not_invalidate_geometry_but_inputs_do(self):
        model = write_manifest(self.root)
        self.check_mesh(trimesh.creation.box())
        (self.root / 'source.txt').write_text('initial source')
        model['inputs'] = ['source.txt']
        seed_validation_report(self.root, model)
        model['variants'][0]['name'] = 'new label'
        model['variants'][0]['id'] = 'new-id'
        current_report(self.root, model)
        (self.root / 'source.txt').write_text('changed source')
        with self.assertRaisesRegex(ValueError, '构建输入'):
            current_report(self.root, model)
        with self.assertRaisesRegex(ValueError, '构建输入'):
            validate(self.root, model)
        model['inputs'] = ['../../outside']
        with self.assertRaisesRegex(ValueError, '构建输入'):
            validate(self.root, model)

    def test_workspace_location_and_cleanup(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                try:
                    with publish_workspace(self.root, '.model-build-') as work:
                        self.assertEqual(work.parent, self.temp_root)
                        self.assertTrue(work.is_dir())
                        if fail:
                            raise RuntimeError('build failed')
                except RuntimeError:
                    pass
                self.assertFalse(work.exists())

    def test_cross_device_publish_preserves_original(self):
        (self.root / 'keep.txt').write_text('original')
        with publish_workspace(self.root, '.site-build-') as work:
            staged = work / 'staged'
            staged.mkdir()
            stat = Path.stat
            def different_device(path, *args, **kwargs):
                if path == staged:
                    return SimpleNamespace(st_dev=stat(path).st_dev + 1)
                return stat(path, *args, **kwargs)
            with patch.object(Path, 'stat', different_device), patch.object(Path, 'replace') as replace:
                with self.assertRaises(OSError) as error:
                    replace_directory(staged, self.root, work / 'backup')
                self.assertEqual(error.exception.errno, errno.EXDEV)
                replace.assert_not_called()
            self.assertEqual((self.root / 'keep.txt').read_text(), 'original')
        self.assertFalse(work.exists())

    def test_failed_rollback_keeps_recoverable_backup(self):
        target = self.library / 'previous'
        target.mkdir()
        (target / 'keep.txt').write_text('original')
        replace = Path.replace
        def fail_publish_and_rollback(src, dst):
            if src.name in ('staged', 'backup'):
                raise OSError('filesystem unavailable')
            return replace(src, dst)
        warning = StringIO()
        with redirect_stderr(warning), self.assertRaises(OSError):
            with publish_workspace(target, '.site-build-') as work:
                staged = work / 'staged'
                staged.mkdir()
                with patch.object(Path, 'replace', fail_publish_and_rollback):
                    replace_directory(staged, target, work / 'backup')
        self.assertIn('回滚未完成', warning.getvalue())
        self.addCleanup(shutil.rmtree, work)
        self.assertEqual(work.parent, self.temp_root)
        self.assertEqual((work / 'backup/keep.txt').read_text(), 'original')
        self.assertFalse(target.exists())
        (work / 'backup').replace(target)
        self.assertEqual((target / 'keep.txt').read_text(), 'original')

    def test_specialized_verification_order_and_failure_isolation(self):
        model = write_manifest(self.root)
        model.update(build='build.py', verify='verify.py',
                     inputs=['build.py', 'verify.py'], artifacts=['details.json'])
        generator = """from pathlib import Path
import os, trimesh
from PIL import Image
out = Path(os.environ['MODEL_OUTPUT_DIR'])
trimesh.creation.box().export(out/'mesh.stl')
Image.new('RGB', (2,2)).save(out/'preview.png')
"""
        verifier = """from pathlib import Path
import os
out = Path(os.environ['MODEL_OUTPUT_DIR'])
(out/'details.json').write_text('{"passed": true}')
"""
        (self.root/'README.md').write_text('Example')
        (self.root/'build.py').write_text(generator)
        (self.root/'verify.py').write_text(verifier)
        write_manifest(self.root, model)
        # Geometry inspection precedes verification; final reports are written afterwards.
        from tools.model_library.validation import inspect_models
        events = []
        run = subprocess.run
        def inspect_first(*args, **kwargs):
            events.append('geometry')
            self.assertFalse((args[0]/'details.json').exists())
            return inspect_models(*args, **kwargs)
        def run_script(args, **kwargs):
            events.append(Path(args[1]).name)
            return run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        with patch('tools.model_library.pipeline.inspect_models', side_effect=inspect_first), patch('tools.model_library.pipeline.subprocess.run', side_effect=run_script):
            build(self.root, model)
        self.assertEqual(events, ['build.py', 'geometry', 'verify.py'])
        current_report(self.root, model)
        original = {name: (self.root/name).read_bytes() for name in ('mesh.stl','preview.png','details.json','validation.json')}
        cases = [
            ('invalid geometry', generator + "(out/'mesh.stl').write_bytes(b'invalid')\n", verifier, False),
            ('verification failure', generator, verifier + "raise ValueError('specialized failure')\n", True),
            ('changed mesh', generator, verifier + "(out/'mesh.stl').write_bytes(b'changed')\n", True),
            ('missing report', generator, 'pass', True),
            ('changed input', generator, verifier + "Path('build.py').write_text('changed')\n", True),
        ]
        for name, generation, verification, should_verify in cases:
            with self.subTest(name=name):
                (self.root/'build.py').write_text(generation)
                (self.root/'verify.py').write_text(verification)
                events.clear()
                with patch('tools.model_library.pipeline.subprocess.run', side_effect=run_script):
                    with self.assertRaises(Exception):
                        build(self.root, model)
                self.assertEqual('verify.py' in events, should_verify)
                for filename, data in original.items():
                    self.assertEqual((self.root/filename).read_bytes(), data)

    def test_verifier_manifest_contract(self):
        model = write_manifest(self.root)
        (self.root/'verify.py').write_text('pass')
        for changes in [dict(verify='verify.py'),
                        dict(build='build.py', verify='verify.py'),
                        dict(build='build.py', verify='../verify.py', inputs=['../verify.py']),
                        dict(build='build.py', verify=12, inputs=[])]:
            with self.subTest(changes=changes):
                write_manifest(self.root, model | changes)
                with self.assertRaises(ValueError):
                    discover(self.library)

    def test_builder_manifest_contract(self):
        model = write_manifest(self.root)
        (self.root / 'build.py').write_text('pass')
        for changes in [dict(build='build.py'),
                        dict(build='../build.py', inputs=['../build.py']),
                        dict(build=12, inputs=[12])]:
            with self.subTest(changes=changes):
                candidate = model | changes
                write_manifest(self.root, candidate)
                with self.assertRaisesRegex(ValueError, 'build'):
                    discover(self.library)
                with self.assertRaisesRegex(ValueError, 'build'):
                    builder_path(self.root, candidate)
        model.update(build='build.py', inputs=['build.py'])
        write_manifest(self.root, model)
        self.assertEqual(builder_path(self.root, model), self.root / 'build.py')


class ExistingValidationTests(unittest.TestCase):
    setUp = ModelTests.setUp
    tearDown = ModelTests.tearDown
    check_mesh = ModelTests.check_mesh
    def prepare(self):
        model = write_manifest(self.root)
        model.update(build='build.py', verify='verify.py', inputs=['build.py', 'verify.py'],
                     artifacts=['details.json'])
        self.check_mesh(trimesh.creation.box())
        for name in ('preview.png', 'README.md', 'details.json'):
            (self.root/name).write_text('original')
        (self.root/'build.py').write_text('raise RuntimeError("must not build")')
        (self.root/'verify.py').write_text('pass')
        seed_validation_report(self.root, model)
        return model

    def test_existing_validation_order_and_report_publication(self):
        from tools.model_library import pipeline
        model = self.prepare()
        before = self.path.read_bytes()
        events = []
        inspect_models_real = pipeline.inspect_models
        finish_real = pipeline.finish_validation
        def geometry(*args):
            events.append('geometry')
            return inspect_models_real(*args)
        def verify(args, **kwargs):
            events.append(Path(args[1]).name)
            self.assertEqual(kwargs['cwd'], self.root.resolve())
            output = Path(kwargs['env']['MODEL_OUTPUT_DIR'])
            self.assertNotEqual(output, self.root)
            (output/'details.json').write_text('updated')
        def finish(*args):
            events.append('finish')
            return finish_real(*args)
        with patch.object(pipeline, 'inspect_models', side_effect=geometry), patch.object(pipeline.subprocess, 'run', side_effect=verify), patch.object(pipeline, 'finish_validation', side_effect=finish):
            pipeline.validate(self.root, model)
        self.assertEqual(events, ['geometry', 'verify.py', 'finish'])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual((self.root/'details.json').read_text(), 'updated')
        current_report(self.root, model)

    def test_existing_validation_failures_preserve_reports(self):
        from tools.model_library import pipeline
        for failure in ('specialized', 'mesh', 'input', 'original', 'publish'):
            with self.subTest(failure=failure):
                model = self.prepare()
                before = {name: (self.root/name).read_bytes() for name in ('mesh.stl', 'details.json', 'validation.json')}
                def verify(*args, **kwargs):
                    output = Path(kwargs['env']['MODEL_OUTPUT_DIR'])
                    (output/'details.json').write_text('updated')
                    if failure == 'specialized':
                        raise subprocess.CalledProcessError(1, args[0])
                    if failure == 'mesh':
                        (output/'mesh.stl').write_bytes(b'changed')
                    if failure == 'input':
                        (self.root/'build.py').write_text('changed input')
                    if failure == 'original':
                        (self.root/'README.md').write_text('concurrent edit')
                replace = Path.replace
                def publish(src, dst):
                    if failure == 'publish' and src.name == 'staged':
                        raise OSError('publish failure')
                    return replace(src, dst)
                with patch.object(pipeline.subprocess, 'run', side_effect=verify), patch.object(Path, 'replace', publish):
                    with self.assertRaises(Exception):
                        pipeline.validate(self.root, model)
                for name, data in before.items():
                    self.assertEqual((self.root/name).read_bytes(), data)
                if failure == 'original':
                    self.assertEqual((self.root/'README.md').read_text(), 'concurrent edit')

    def test_existing_validation_without_verifier_and_stale_inputs(self):
        from tools.model_library import pipeline
        model = self.prepare()
        del model['verify']
        with patch.object(pipeline.subprocess, 'run') as run:
            pipeline.validate(self.root, model)
            run.assert_not_called()
        (self.root/'build.py').write_text('changed')
        with patch.object(pipeline, 'inspect_models') as inspect_geometry:
            with self.assertRaisesRegex(ValueError, '构建输入'):
                pipeline.validate(self.root, model)
            inspect_geometry.assert_not_called()

    def test_existing_validation_rejects_changed_gltf_dependency(self):
        from tools.model_library import pipeline
        model = self.prepare()
        model.update(purpose='display', units='m', up='Y',
                     variants=[dict(id='main', file='model.gltf')])
        for name, data in trimesh.Scene(trimesh.creation.box()).export(file_type='gltf').items():
            (self.root/name).write_bytes(data)
        seed_validation_report(self.root, model)
        before = (self.root/'validation.json').read_bytes()
        dependency = next(name for name in dependencies(self.root, 'model.gltf') if name.endswith('.bin'))
        original = (self.root/dependency).read_bytes()
        def verify(*args, **kwargs):
            (Path(kwargs['env']['MODEL_OUTPUT_DIR'])/dependency).write_bytes(b'changed')
        with patch.object(pipeline.subprocess, 'run', side_effect=verify):
            with self.assertRaisesRegex(ValueError, '依赖'):
                pipeline.validate(self.root, model)
        self.assertEqual((self.root/dependency).read_bytes(), original)
        self.assertEqual((self.root/'validation.json').read_bytes(), before)
