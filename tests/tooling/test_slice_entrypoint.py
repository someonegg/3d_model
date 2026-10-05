"""Exercise the shell dispatcher with a fake interpreter, never BambuStudio."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class SliceEntryPointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'tools').mkdir()
        self.script = self.root / 'tools/slice-model.sh'
        shutil.copyfile(ROOT / 'tools/slice-model.sh', self.script)
        python = self.root / '.venv/bin/python'
        python.parent.mkdir(parents=True)
        python.write_text(
            '#!/bin/bash\n'
            'printf "started\\n" > started\n'
            'printf "stdout\\n"\n'
            'printf "stderr\\n" >&2\n'
            'printf "%s\\n" "$@"\n'
            'exit 17\n'
        )
        python.chmod(0o755)

    def run_slice(self, *args):
        return subprocess.run(
            ['bash', str(self.script), *args], cwd='/',
            capture_output=True, text=True, timeout=10,
        )

    def test_terminal_and_argument_forwarding(self):
        result = self.run_slice('keyboard-fidget-fdm', '--only', 'a b')
        self.assertEqual(result.returncode, 17)
        self.assertEqual(result.stderr, 'stderr\n')
        self.assertEqual(result.stdout.splitlines(), [
            'stdout', str(self.root / 'tools/run_model.py'),
            str(self.root / 'models/keyboard-fidget-fdm/src/slice.py'),
            '--only', 'a b',
        ])
        self.assertEqual(self.run_slice('fidget-button-fdm').returncode, 17)

    def test_log_merges_streams_overwrites_and_creates_directories(self):
        log = self.root / 'logs with spaces/nested/run.log'
        for path in ('logs with spaces/nested/run.log', str(log)):
            with self.subTest(path=path):
                result = self.run_slice('star-chain-fdm', '--only', 'a b', '--log-file', path)
                self.assertEqual(result.returncode, 17, result.stderr)
                self.assertEqual(result.stdout + result.stderr, '')
                content = log.read_text()
                self.assertTrue(content.startswith('stdout\nstderr\n'))
                self.assertTrue(content.endswith('--only\na b\n'))
                self.assertNotIn('--log-file', content)
                log.write_text('old content')

    def test_invalid_logs_do_not_start_model_or_truncate(self):
        log = self.root / 'existing.log'
        log.write_text('keep')
        cases = [
            ('--log-file',), ('--log-file', ''),
            ('--log-file', '--only'),
            ('--log-file', str(log), '--log-file', 'other'),
            ('--log-file', str(self.root)),
            ('--log-file', str(log / 'child/run.log')),
        ]
        for args in cases:
            with self.subTest(args=args):
                result = self.run_slice('star-chain-fdm', *args)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stderr)
                self.assertFalse((self.root / 'started').exists())
                self.assertEqual(log.read_text(), 'keep')

    def test_help_list_and_unknown_model(self):
        self.assertIn('--log-file', self.run_slice('--help').stdout)
        self.assertIn('star-chain-fdm', self.run_slice('--list').stdout)
        self.assertEqual(self.run_slice('unknown').returncode, 2)
        self.assertFalse((self.root / 'started').exists())
