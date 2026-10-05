"""Exercise every model's CLI orchestration without launching BambuStudio."""
import contextlib
import io
import json
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.slicing import configure_slicing, slicing_parser, source_hashes

REPO = Path(__file__).resolve().parents[2]
MODELS = ('fidget-button-fdm', 'keyboard-fidget-fdm', 'retractable-shuriken-fdm',
          'star-chain-fdm', 'volvo-xc60-2022')


class SlicingInterfaceTests(unittest.TestCase):
    def test_all_modes_and_failures(self):
        for model in MODELS:
            with self.subTest(model=model), tempfile.TemporaryDirectory(dir=REPO / 'tmp') as tmp:
                root = Path(tmp)
                source = root / 'source'
                source.mkdir()
                for name in ('all-parts.stl', 'fidget-button-fdm.stl', 'fit-coupon.stl', 'plate.stl'):
                    (source / name).write_bytes(b'fixture geometry')
                (source / 'assembly.json').write_text(json.dumps({'plates': [{'file': 'plate.stl'}]}))
                (source / 'geometry.json').write_text('{}')
                profiles = root / 'profiles'
                profiles.mkdir()
                config = json.loads((REPO / 'models' / model / 'slicing.json').read_text())
                for i, name in enumerate(('Bambu Lab P2S 0.4 nozzle', config['process'], config['filament'])):
                    (profiles / f'{i}.json').write_text(json.dumps({'name': name}))
                script = REPO / 'models' / model / 'src/slice.py'
                with patch.object(sys, 'path', [str(script.parent), str(REPO / 'tools'), *sys.path]), patch.dict(sys.modules):
                    for name in ('build', 'geometry', 'preview', 'assembly'):
                        sys.modules.pop(name, None)
                    namespace = runpy.run_path(str(script))
                    main = namespace['main']
                    argv = [str(script), '--studio', 'fixture-studio', '--profiles', str(profiles),
                            '--output-dir', str(root / 'audit')]
                    def audit(*args, **kwargs):
                        self.assertEqual(args[0], 'fixture-studio')
                        return {'cli_diagnostics': [], 'plates': [], 'software': 'fixture', 'physical_print_test': False}
                    with patch.dict(main.__globals__, {'model_directory': lambda _: source}), patch.object(
                        sys, 'argv', argv + ['--prepare-only']
                    ), patch.dict(main.__globals__, {'audit_files': lambda *a, **k: self.fail('prepare sliced')}), contextlib.redirect_stdout(io.StringIO()) as stream:
                        main()
                    commands = json.loads(stream.getvalue())['commands']
                    self.assertTrue(commands)
                    self.assertTrue(all(command[0] == 'fixture-studio' for command in commands))
                    configs = [root / 'audit' / f'{n}.json' for n in ('machine', 'process', 'filament')]
                    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in configs]
                    for mode in ([], ['--collect-only']):
                        with patch.dict(main.__globals__, {'model_directory': lambda _: source}), patch.object(
                            sys, 'argv', argv + mode
                        ), patch.dict(main.__globals__, {'audit_files': audit}), contextlib.redirect_stdout(io.StringIO()):
                            main()
                        if mode:
                            self.assertEqual(before, [(p.read_bytes(), p.stat().st_mtime_ns) for p in configs])
                        else:
                            before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in configs]
                    for mode in (['--prepare-only', '--collect-only'], ['--unknown']):
                        with patch.object(sys, 'argv', argv + mode), contextlib.redirect_stderr(io.StringIO()):
                            with self.assertRaises(SystemExit):
                                main()
                    if model == 'volvo-xc60-2022':
                        with patch.dict(main.__globals__, {'model_directory': lambda _: source}), patch.object(
                            sys, 'argv', argv + ['--only', 'missing.stl']
                        ), contextlib.redirect_stderr(io.StringIO()):
                            with self.assertRaises(SystemExit):
                                main()
                    with patch.dict(main.__globals__, {'model_directory': lambda _: source}), patch.object(
                        sys, 'argv', argv
                    ), patch.dict(main.__globals__, {'audit_files': unittest.mock.Mock(side_effect=RuntimeError('fixture failure'))}):
                        with self.assertRaisesRegex(RuntimeError, 'fixture failure'):
                            main()
                    process = root / 'audit/process.json'
                    original = process.read_bytes()
                    process.write_text('{}')
                    with patch.dict(main.__globals__, {'model_directory': lambda _: source}), patch.object(
                        sys, 'argv', argv + ['--collect-only']
                    ):
                        with self.assertRaisesRegex(ValueError, '指纹'):
                            main()
                    process.write_bytes(original)
                    (source / 'all-parts.stl').write_bytes(b'changed')
                    (source / 'fidget-button-fdm.stl').write_bytes(b'changed')
                    (source / 'fit-coupon.stl').write_bytes(b'changed')
                    with patch.dict(main.__globals__, {'model_directory': lambda _: source}), patch.object(
                        sys, 'argv', argv + ['--collect-only']
                    ):
                        with self.assertRaisesRegex(ValueError, '指纹'):
                            main()
