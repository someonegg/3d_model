"""Exercise the display publisher against a tiny independent print library."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from PIL import Image
import trimesh

from tools.model_library.pipeline import validate


class DisplayBuildTests(unittest.TestCase):
    def test_import_is_passive_and_stale_upstream_is_rejected(self):
        repo = Path(__file__).resolve().parents[2]
        root = repo / 'tmp/tests'
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as temporary:
            library = Path(temporary)
            source = library / 'models/volvo-xc60-2022'
            source.mkdir(parents=True)
            script = library / 'models/display/src/build.py'
            script.parent.mkdir(parents=True)
            shutil.copyfile(repo / 'models/volvo-xc60-2022-display/src/build.py', script)
            scene = trimesh.Scene(trimesh.creation.box())
            for name in ('assembled.glb', 'doors-open.glb'):
                scene.export(source / name)
            for name in ('preview.png', 'doors-open.png', 'exploded.png', 'rear.png'):
                Image.new('RGB', (2, 2)).save(source / name)
            (source / 'README.md').write_text('Fixture')
            model = dict(id=source.name, purpose='display', units='m', up='Y',
                         variants=[dict(id='closed', file='assembled.glb'),
                                   dict(id='open', file='doors-open.glb')],
                         readme='README.md', preview='preview.png')
            (source / 'model.json').write_text(json.dumps(model))
            validate(source, model)
            output = library / 'output'
            env = dict(os.environ, PYTHONPATH=str(repo / 'tools'),
                       MODEL_OUTPUT_DIR=str(output), PYTHONDONTWRITEBYTECODE='1')
            imported = subprocess.run([sys.executable, '-c',
                                       'import runpy,sys; runpy.run_path(sys.argv[1])', str(script)],
                                      env=env, capture_output=True)
            self.assertEqual(imported.returncode, 0, imported.stderr)
            self.assertFalse(output.exists())
            result = subprocess.run([sys.executable, str(script)], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(list(output.iterdir())), 6)
            before = (output / 'assembled.glb').read_bytes()
            trimesh.Scene(trimesh.creation.box(extents=[2, 2, 2])).export(source / 'assembled.glb')
            result = subprocess.run([sys.executable, str(script)], env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('校验过期', result.stderr.decode())
            self.assertEqual((output / 'assembled.glb').read_bytes(), before)
