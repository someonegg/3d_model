"""Shared slicing helpers use fixture profiles and logs, without launching Studio."""
from pathlib import Path
import json
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.slicing import resolve_profiles, run_studio, studio_metadata


class SlicingTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2] / 'tmp/tests'
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def profiles(self, *rows):
        for row in rows:
            (self.root / f'{row["name"]}.json').write_text(json.dumps(row))
        return resolve_profiles(self.root)

    def test_inheritance_precedence_and_invalid_references(self):
        resolve = self.profiles(
            {'name': 'base', 'layer': '.2', 'walls': 2},
            {'name': 'extra', 'walls': 3},
            {'name': 'child', 'inherits': 'base', 'include': ['extra'], 'layer': '.16'},
            {'name': 'missing', 'inherits': 'unknown'},
            {'name': 'cycle-a', 'inherits': 'cycle-b'},
            {'name': 'cycle-b', 'include': ['cycle-a']},
        )
        self.assertEqual(resolve('child'), {'name': 'child', 'layer': '.16', 'walls': 3})
        self.assertEqual(resolve('base')['walls'], 2)
        with self.assertRaisesRegex(ValueError, '缺失切片配置'):
            resolve('missing')
        with self.assertRaisesRegex(ValueError, '继承循环'):
            resolve('cycle-a')

    def test_metadata_does_not_invent_historical_diagnostics(self):
        studio = self.root / 'Contents/MacOS/BambuStudio'
        studio.parent.mkdir(parents=True)
        with (studio.parent.parent / 'Info.plist').open('wb') as stream:
            plistlib.dump({'CFBundleShortVersionString': '9.8.7'}, stream)
        log = self.root / 'studio.log'
        log.write_text('Slicing complete\n')
        result = studio_metadata(studio, [log])
        self.assertEqual(result['software'], 'Bambu Studio 9.8.7')
        self.assertEqual(result['cli_diagnostics'], [])
        self.assertIn('unknown', studio_metadata(studio, [log], collect_only=True)['software'])
        log.write_text('BambuStudio version 2.3.4.5\nWarning: fixture\nWarning: fixture\n')
        result = studio_metadata(studio, [log], collect_only=True)
        self.assertEqual(result['software'], 'Bambu Studio 2.3.4.5')
        self.assertEqual(result['cli_diagnostics'], ['Warning: fixture'])

    def test_process_failure_retains_log(self):
        with patch('tools.slicing.subprocess.run', return_value=subprocess.CompletedProcess([], 7)):
            with self.assertRaisesRegex(RuntimeError, '退出码 7'):
                run_studio(['fixture-studio'], self.root)
        self.assertTrue((self.root / 'studio.log').is_file())
