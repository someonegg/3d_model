"""Public orchestration and script imports work outside the repository cwd."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import write_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]


class EntryPointTests(unittest.TestCase):
    def setUp(self):
        work = REPO_ROOT / "tmp/tests"
        work.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=work)
        self.addCleanup(self.temp.cleanup)
        self.library = Path(self.temp.name)

    def test_failed_model_stops_build_and_dev_before_frontend(self):
        directory = self.library / "models/example"
        directory.mkdir(parents=True)
        (directory / "README.md").write_text("Fixture")
        model = write_manifest(directory)
        model.update(build="build.py", inputs=["build.py"])
        write_manifest(directory, model)
        (directory / "build.py").write_text("raise RuntimeError('fixture failed')\n")
        catalog = REPO_ROOT / "dist/catalog.json"
        before = catalog.read_bytes() if catalog.exists() else None
        for command in ([], ["dev"]):
            result = subprocess.run(
                [
                    "node",
                    str(REPO_ROOT / "tools/build.mjs"),
                    *command,
                    "--library-root",
                    str(self.library),
                ],
                cwd=self.library,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("fixture failed", result.stderr)
            self.assertNotIn("vite", result.stdout.lower())
            self.assertEqual(catalog.read_bytes() if catalog.exists() else None, before)

    def test_watcher_error_closes_vite_and_cancels_updates(self):
        (self.library / "models").mkdir()
        script = r"""
import assert from 'node:assert/strict';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { createServer } from 'vite';
import { modelLibrary } from './tools/model-plugin.mjs';
const library = process.argv[1];
const failClose = process.argv[2] === 'true';
const server = await createServer({
  configFile: false,
  root: path.join(library, 'models'),
  plugins: [modelLibrary(library)],
  server: { host: '127.0.0.1', port: 0 },
});
await server.listen();
assert.equal(server.httpServer.listening, true);
let closes = 0;
let updates = 0;
const send = server.ws.send.bind(server.ws);
server.ws.send = (...args) => {
  if (args[0]?.event === 'models-updated') updates++;
  return send(...args);
};
const close = server.close.bind(server);
server.close = async () => {
  closes++;
  await delay(650);
  await close();
  if (failClose) throw new Error('injected close failure');
};
server.watcher.emit('all', 'add', path.join(library, 'models/example/model.json'));
server.watcher.emit('error', new Error('injected watcher failure'));
server.watcher.emit('error', new Error('second watcher failure'));
server.watcher.emit('all', 'change', path.join(library, 'models/example/model.json'));
await delay(900);
assert.equal(closes, 1);
assert.equal(updates, 0);
assert.equal(server.httpServer.listening, false);
assert.equal(server.watcher.closed, true);
assert.equal(process.exitCode, 1);
console.log('watcher shutdown verified');
"""
        for fail_close in (False, True):
            with self.subTest(fail_close=fail_close):
                result = subprocess.run(
                    [
                        "node",
                        "--input-type=module",
                        "-e",
                        script,
                        str(self.library),
                        str(fail_close).lower(),
                    ],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("watcher shutdown verified", result.stdout)
                self.assertIn("injected watcher failure", result.stderr)
                self.assertIn("second watcher failure", result.stderr)
                self.assertIn("正在关闭开发服务", result.stderr)
                if fail_close:
                    self.assertIn("开发服务关闭失败", result.stderr)
                    self.assertIn("injected close failure", result.stderr)
                self.assertNotIn("UnhandledPromiseRejection", result.stderr)

    def test_library_cli_force_and_script_source_paths(self):
        directory = self.library / "models/example"
        directory.mkdir(parents=True)
        (directory / "README.md").write_text("Fixture")
        model = write_manifest(directory)
        model.update(build="build.py", inputs=["build.py", "parameters.json"])
        write_manifest(directory, model)
        (directory / "parameters.json").write_text("[1,2,3]")
        (directory / "build.py").write_text(
            "from pathlib import Path\nimport os,json,trimesh\nfrom PIL import Image\n"
            "source=Path(__file__).resolve().parent\n"
            "out=Path(os.environ['MODEL_OUTPUT_DIR'])\nassert out.is_absolute()\n"
            "trimesh.creation.box(extents=json.loads((source/'parameters.json').read_text())).export(out/'mesh.stl')\n"
            "Image.new('RGB',(2,2)).save(out/'preview.png')\n"
        )
        args = [
            sys.executable,
            str(REPO_ROOT / "tools/models.py"),
            "build",
            "--library-root",
            str(self.library),
        ]
        for force in (False, False, True):
            result = subprocess.run(
                args + (["--force"] if force else []),
                cwd=self.library,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "完成" if force else ("跳过" if hasattr(self, "built") else "完成"),
                result.stdout,
            )
            self.built = True
        report = json.loads(
            (self.library / "build/models/example/validation.json").read_text()
        )
        self.assertEqual(report["files"][0]["dimensions"], [1, 2, 3])

    def test_slicing_help_uses_shared_import_environment(self):
        for model in ("keyboard-fidget-fdm", "volvo-xc60-2022"):
            result = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "tools/run_model.py"),
                    str(REPO_ROOT / f"models/{model}/src/slice.py"),
                    "--help",
                ],
                cwd=self.library,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--studio", result.stdout)
            self.assertIn("--profiles", result.stdout)
