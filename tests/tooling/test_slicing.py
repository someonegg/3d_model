"""Shared slicing helpers use fixture profiles and logs, without launching Studio."""
from pathlib import Path
import json
import plistlib
import subprocess
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from tools.slicing import (
    model_directory, resolve_profiles, run_studio, save_report, sha,
    slicing_workspace, source_hashes, studio_metadata,
)


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

    def test_report_failure_preserves_previous_result_and_changed_sources_are_rejected(self):
        source = self.root / 'source'
        source.mkdir()
        mesh = source / 'mesh.stl'
        mesh.write_bytes(b'original geometry')
        inputs = source_hashes(source, ['mesh.stl'])
        report = save_report(self.root, {'status': 'complete'}, source, inputs)
        target = self.root / 'slicing-validation.json'
        before = target.read_bytes()
        self.assertEqual(report['source_sha256']['mesh.stl'], sha(mesh))
        with patch.object(Path, 'replace', side_effect=OSError('fixture failure')):
            with self.assertRaisesRegex(OSError, 'fixture failure'):
                save_report(self.root, {'status': 'partial'}, source, inputs)
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(list(self.root.glob('.slicing-report-*')), [])
        with self.assertRaises(TypeError):
            save_report(self.root, {'status': object()}, source, inputs)
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(list(self.root.glob('.slicing-report-*')), [])
        mesh.write_bytes(b'changed geometry')
        with self.assertRaisesRegex(ValueError, '输入已改变'):
            save_report(self.root, {'status': 'complete'}, source, inputs)
        self.assertEqual(target.read_bytes(), before)

    def test_workspace_cannot_write_to_sources_or_build_outputs(self):
        directory = self.root / 'models/example'
        directory.mkdir(parents=True)
        for output in (self.root, directory, directory / 'src',
                       self.root / 'build/models/example', self.root / 'dist',
                       self.root / 'tmp/site'):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, '不能覆盖'):
                slicing_workspace(directory, output)
        output = self.root / 'tmp/slicing'
        self.assertEqual(slicing_workspace(directory, output), output)
        with self.assertRaisesRegex(ValueError, '越界切片输入'):
            source_hashes(directory, ['../../outside.stl'])

    def test_volvo_manual_audit_needs_no_manifest_or_build_validation(self):
        import importlib.util
        import sys

        script = Path(__file__).resolve().parents[2] / 'models/volvo-xc60-2022/src/slice.py'
        spec = importlib.util.spec_from_file_location('volvo_slice', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.HERE = self.root / 'models/car'
        module.HERE.mkdir(parents=True)
        source = model_directory(module.HERE)
        source.mkdir(parents=True)
        (source / 'assembly.json').write_text(json.dumps({'plates': [{'file': 'plate.stl'}]}))
        for name in ('fit-coupon.stl', 'plate.stl'):
            (source / name).write_bytes(b'fixture geometry')
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in source.iterdir()}
        output = self.root / 'tmp/slicing'

        def studio(command, out):
            (out / 'result.json').write_text(json.dumps({
                'return_code': 0,
                'sliced_plates': [{'total_predication': 1, 'filaments': [], 'feature_type_times': {}}],
            }))
            config = {
                'printer_model': 'Bambu Lab P2S', 'nozzle_diameter': ['0.4'],
                'layer_height': '0.16', 'wall_loops': '4', 'enable_support': '1', 'printable_area': '256x256',
                'filament_density': ['1.2'],
            }
            with zipfile.ZipFile(out / 'sliced.3mf', 'w') as archive:
                archive.writestr('Metadata/project_settings.config', json.dumps(config))
                archive.writestr('Metadata/plate_1.png', b'fixture preview')
                archive.writestr('Metadata/top_1.png', b'fixture preview')
                archive.writestr('Metadata/plate_1.gcode', '; FEATURE: Outer wall\n')

        argv = ['slice.py', '--output-dir', str(output), '--profiles', str(self.root / 'profiles')]
        with patch.object(sys, 'argv', argv), patch.object(
            module, 'resolve_profiles', return_value=lambda name: {}
        ), patch.object(module, 'run_studio', side_effect=studio):
            module.main()
        report = output / 'slicing-validation.json'
        accepted = report.read_bytes()
        self.assertEqual(json.loads(accepted)['status'], 'complete')
        with patch.object(sys, 'argv', argv + ['--only', 'fit-coupon.stl']), patch.object(
            module, 'resolve_profiles', return_value=lambda name: {}
        ), patch.object(module, 'run_studio', side_effect=studio):
            module.main()
        accepted = report.read_bytes()
        self.assertEqual(json.loads(accepted)['status'], 'partial')
        self.assertEqual([row['file'] for row in json.loads(accepted)['plates']], ['fit-coupon.stl'])
        with patch.object(sys, 'argv', argv), patch.object(
            module, 'resolve_profiles', return_value=lambda name: {}
        ), patch.object(module, 'run_studio', side_effect=RuntimeError('slice failed')):
            with self.assertRaisesRegex(RuntimeError, 'slice failed'):
                module.main()
        self.assertEqual(report.read_bytes(), accepted)
        self.assertEqual(before, {
            p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in source.iterdir()
        })
        self.assertFalse((module.HERE / 'model.json').exists())
        self.assertFalse((source / 'validation.json').exists())

    def test_shared_audit_collect_partial_configuration_failure_and_changed_input(self):
        from tools.slicing import audit_files, prepare_profiles
        source = self.root / 'source'
        source.mkdir()
        (source / 'one.stl').write_bytes(b'mesh one')
        (source / 'two.stl').write_bytes(b'mesh two')
        inputs = source_hashes(source, ['one.stl'])
        prepare_profiles(self.root, self.root, 'fixture', {'layer_height': '0.2'},
                         resolver=lambda _: lambda name: {})
        expected = {'layer_height': '0.2', 'enable_support': '0'}

        def studio(command, output):
            self.assertEqual(command[command.index('--arrange') + 1], '1')
            self.assertEqual(Path(command[-1]).name, 'one.stl')
            (output / 'result.json').write_text(json.dumps({'return_code': 0, 'sliced_plates': [
                {'total_predication': 2, 'filaments': [], 'feature_type_times': {}}]}))
            with zipfile.ZipFile(output / 'sliced.3mf', 'w') as archive:
                archive.writestr('Metadata/project_settings.config', json.dumps({
                    'printer_model': 'Bambu Lab P2S', 'nozzle_diameter': ['0.4'], **expected}))
                for name in ('plate_1.png', 'top_1.png'):
                    archive.writestr('Metadata/' + name, b'preview')
                archive.writestr('Metadata/plate_1.gcode', 'G1 X1 E1\n')

        with patch('tools.slicing.run_studio', side_effect=studio) as runner:
            report = audit_files('fixture', self.root, source, ['one.stl'], inputs,
                                 arrange=1, expected=expected)
            self.assertEqual(runner.call_count, 1)
        self.assertEqual([p['file'] for p in report['plates']], ['one.stl'])
        save_report(self.root, report, source, inputs)
        accepted = (self.root / 'slicing-validation.json').read_bytes()
        with patch('tools.slicing.run_studio', side_effect=AssertionError('must not run')):
            collected = audit_files('fixture', self.root, source, ['one.stl'], inputs,
                                   arrange=1, expected=expected, collect_only=True)
        self.assertEqual(collected['plates'], report['plates'])
        with self.assertRaisesRegex(ValueError, '配置不符'):
            audit_files('fixture', self.root, source, ['one.stl'], inputs,
                        arrange=1, expected={'layer_height': '0.16'}, collect_only=True)
        with patch('tools.slicing.run_studio', side_effect=RuntimeError('failed')):
            with self.assertRaisesRegex(RuntimeError, 'failed'):
                audit_files('fixture', self.root, source, ['one.stl'], inputs,
                            arrange=1, expected=expected)
        (source / 'one.stl').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, '输入已改变'):
            save_report(self.root, collected, source, inputs)
        self.assertEqual((self.root / 'slicing-validation.json').read_bytes(), accepted)

    def test_keyboard_special_checks_reject_stale_geometry_and_missing_paths(self):
        import importlib.util
        import xml.etree.ElementTree as ET
        import trimesh
        script = Path(__file__).resolve().parents[2] / 'models/keyboard-fidget-fdm/src/slice.py'
        spec = importlib.util.spec_from_file_location('keyboard_slice', script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source = self.root / 'all-parts.stl'
        mesh = trimesh.creation.box()
        mesh.export(source)
        model = ET.Element('model')
        node = ET.SubElement(model, 'mesh')
        vertices = ET.SubElement(node, 'vertices')
        triangles = ET.SubElement(node, 'triangles')
        for vertex in mesh.vertices:
            ET.SubElement(vertices, 'vertex', dict(zip(('x', 'y', 'z'), map(str, vertex))))
        for face in mesh.faces:
            ET.SubElement(triangles, 'triangle', dict(zip(('v1', 'v2', 'v3'), map(str, face))))
        with zipfile.ZipFile(self.root / 'mesh.3mf', 'w') as archive:
            archive.writestr('3D/3dmodel.model', ET.tostring(model))
        with zipfile.ZipFile(self.root / 'mesh.3mf') as archive:
            module.check_archive_geometry(archive, source)
            mesh.apply_scale(2)
            mesh.export(source)
            with self.assertRaises(AssertionError):
                module.check_archive_geometry(archive, source)
        with patch.object(module, 'model_directory', return_value=self.root):
            for check in (module.inspect_spring_paths, module.inspect_support_paths):
                with self.assertRaisesRegex(AssertionError, 'missing layer'):
                    check('', self.root, {'x': 0, 'y': 0})
