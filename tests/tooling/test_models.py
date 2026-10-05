import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import numpy as np
import trimesh
from PIL import Image

from tests.support import write_manifest
from tools.model_library.building import build
from tools.model_library.publication import catalog, publish_site, site
from tools.model_library.workspace import publish_workspace, replace_directory
from tools.model_library.resources import (
    build_order,
    builder_path,
    dependencies,
    discover,
    output_directory,
)
from tools.model_library.validation import current_report, inspect


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path(__file__).resolve().parents[2] / "tmp"
        test_root = self.temp_root / "tests"
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.library = Path(self.temp.name)
        self.root = self.library / "models" / "example"
        self.root.mkdir(parents=True)
        self.path = self.root / "mesh.stl"

    def tearDown(self):
        self.temp.cleanup()

    def check_mesh(self, mesh, purpose="print"):
        mesh.export(self.path)
        return inspect(self.path, purpose)

    def test_closed_and_open(self):
        mesh = trimesh.creation.box()
        self.assertTrue(self.check_mesh(mesh)["passed"])
        mesh.update_faces(np.arange(len(mesh.faces) - 1))
        self.assertFalse(self.check_mesh(mesh)["passed"])
        self.assertTrue(self.check_mesh(mesh, "display")["passed"])

    def test_reversed_and_multiple_components(self):
        mesh = trimesh.creation.box()
        mesh.invert()
        self.assertFalse(self.check_mesh(mesh)["passed"])
        good = trimesh.creation.box()
        other = good.copy()
        other.apply_translation([3, 0, 0])
        report = self.check_mesh(trimesh.util.concatenate([good, other]))
        self.assertTrue(report["passed"])
        self.assertEqual(report["components"], 2)
        other.invert()
        self.assertFalse(
            self.check_mesh(trimesh.util.concatenate([good, other]))["passed"]
        )

    def test_degenerate_and_corrupt(self):
        mesh = trimesh.creation.box()
        mesh.faces = np.vstack([mesh.faces, [0, 0, 1]])
        self.assertFalse(self.check_mesh(mesh)["passed"])
        self.path.write_bytes(b"broken")
        with self.assertRaises(Exception):
            inspect(self.path, "print")

    def test_workspace_location_and_cleanup(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                try:
                    with publish_workspace(self.root, ".model-build-") as work:
                        self.assertEqual(work.parent, self.temp_root)
                        self.assertTrue(work.is_dir())
                        if fail:
                            raise RuntimeError("build failed")
                except RuntimeError:
                    pass
                self.assertFalse(work.exists())

    def test_failed_rollback_keeps_recoverable_backup(self):
        target = self.library / "previous"
        target.mkdir()
        (target / "keep.txt").write_text("original")
        replace = Path.replace

        def fail_publish_and_rollback(src, dst):
            if src.name in ("staged", "backup"):
                raise OSError("filesystem unavailable")
            return replace(src, dst)

        warning = StringIO()
        with redirect_stderr(warning), self.assertRaises(OSError):
            with publish_workspace(target, ".site-build-") as work:
                staged = work / "staged"
                staged.mkdir()
                with patch.object(Path, "replace", fail_publish_and_rollback):
                    replace_directory(staged, target, work / "backup")
        self.assertIn("回滚未完成", warning.getvalue())
        self.addCleanup(shutil.rmtree, work)
        self.assertEqual(work.parent, self.temp_root)
        self.assertEqual((work / "backup/keep.txt").read_text(), "original")
        self.assertFalse(target.exists())
        (work / "backup").replace(target)
        self.assertEqual((target / "keep.txt").read_text(), "original")

    def test_specialized_verification_order_and_failure_isolation(self):
        model = write_manifest(self.root)
        model.update(
            build="build.py",
            verify="verify.py",
            inputs=["build.py", "verify.py"],
            artifacts=["details.json"],
        )
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
        (self.root / "README.md").write_text("Example")
        (self.root / "build.py").write_text(generator)
        (self.root / "verify.py").write_text(verifier)
        write_manifest(self.root, model)
        # Geometry inspection precedes verification; final reports are written afterwards.
        from tools.model_library.validation import inspect_models

        events = []
        run = subprocess.run

        def inspect_first(*args, **kwargs):
            events.append("geometry")
            self.assertFalse((args[0] / "details.json").exists())
            return inspect_models(*args, **kwargs)

        def run_script(args, **kwargs):
            events.append(Path(args[2]).name)
            return run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)

        with (
            patch(
                "tools.model_library.building.inspect_models", side_effect=inspect_first
            ),
            patch(
                "tools.model_library.building.subprocess.run", side_effect=run_script
            ),
        ):
            build(self.root, model)
        self.assertEqual(events, ["build.py", "geometry", "verify.py"])
        current_report(self.root, model)
        original = {
            name: (output_directory(self.root) / name).read_bytes()
            for name in ("mesh.stl", "preview.png", "details.json", "validation.json")
        }
        cases = [
            (
                "invalid geometry",
                generator + "(out/'mesh.stl').write_bytes(b'invalid')\n",
                verifier,
                False,
            ),
            (
                "verification failure",
                generator,
                verifier + "raise ValueError('specialized failure')\n",
                True,
            ),
            (
                "changed mesh",
                generator,
                verifier + "(out/'mesh.stl').write_bytes(b'changed')\n",
                True,
            ),
            ("missing report", generator, "pass", True),
        ]
        for name, generation, verification, should_verify in cases:
            with self.subTest(name=name):
                (self.root / "build.py").write_text(generation)
                (self.root / "verify.py").write_text(verification)
                events.clear()
                with patch(
                    "tools.model_library.building.subprocess.run",
                    side_effect=run_script,
                ):
                    with self.assertRaises(Exception):
                        build(self.root, model)
                self.assertEqual("verify.py" in events, should_verify)
                for filename, data in original.items():
                    self.assertEqual(
                        (output_directory(self.root) / filename).read_bytes(), data
                    )

    def test_verifier_manifest_contract(self):
        model = write_manifest(self.root)
        (self.root / "verify.py").write_text("pass")
        for changes in [
            dict(verify="verify.py"),
            dict(build="build.py", verify="verify.py"),
            dict(build="build.py", verify="../verify.py", inputs=["../verify.py"]),
            dict(build="build.py", verify=12, inputs=[]),
        ]:
            with self.subTest(changes=changes):
                write_manifest(self.root, model | changes)
                with self.assertRaises(ValueError):
                    discover(self.library)

    def test_builder_manifest_contract(self):
        model = write_manifest(self.root)
        (self.root / "build.py").write_text("pass")
        for changes in [
            dict(build="build.py"),
            dict(build="../build.py", inputs=["../build.py"]),
            dict(build=12, inputs=[12]),
        ]:
            with self.subTest(changes=changes):
                candidate = model | changes
                write_manifest(self.root, candidate)
                with self.assertRaisesRegex(ValueError, "build"):
                    discover(self.library)
                with self.assertRaisesRegex(ValueError, "build"):
                    builder_path(self.root, candidate)
        model.update(build="build.py", inputs=["build.py"])
        write_manifest(self.root, model)
        self.assertEqual(builder_path(self.root, model), self.root / "build.py")


class BuildPipelineTests(unittest.TestCase):
    setUp = ModelTests.setUp
    tearDown = ModelTests.tearDown

    def generated(self):
        model = dict(
            id="example",
            name="Example",
            description="fixture",
            purpose="print",
            units="mm",
            up="Z",
            variants=[dict(id="main", name="Main", file="mesh.stl")],
            preview="preview.png",
            readme="README.md",
            build="build.py",
            inputs=["build.py"],
        )
        (self.root / "README.md").write_text("# Example")
        (self.root / "build.py").write_text(
            "import os,trimesh\nfrom pathlib import Path\nfrom PIL import Image\np=Path(os.environ['MODEL_OUTPUT_DIR'])\ntrimesh.creation.box().export(p/'mesh.stl')\nImage.new('RGB',(2,2)).save(p/'preview.png')\n(p/'internal.json').write_text('{}')\n"
        )
        write_manifest(self.root, model)
        return model

    def test_separated_build_and_minimal_site(self):
        model = self.generated()
        original = {p.name: p.read_bytes() for p in self.root.iterdir()}
        build(self.root, model)
        self.assertEqual(
            original, {p.name: p.read_bytes() for p in self.root.iterdir()}
        )
        current_report(self.root, model)
        target = self.library / "tmp/site"
        site(self.library, target)
        files = {
            str(p.relative_to(target / "models/example"))
            for p in (target / "models/example").rglob("*")
            if p.is_file()
        }
        self.assertEqual(files, {"mesh.stl", "preview.png", "README.md"})
        entry = json.loads((target / "catalog.json").read_text())[0]
        self.assertFalse(
            {"inputs", "build", "verify", "artifacts", "depends_on"} & entry.keys()
        )
        self.assertNotIn("resources", entry["validation"]["files"][0])

    def test_catalog_hashes_geometry_once_across_validation_bundle_and_revisions(self):
        from tools.model_library.resources import digest

        model = self.generated()
        model.update(bundle="bundle.json", publish=["download.zip"])
        (self.root / "bundle.json").write_text(json.dumps({
            "file": "download.zip",
            "files": [{"from": "output", "path": "mesh.stl"}],
        }))
        write_manifest(self.root, model)
        build(self.root, model)
        mesh = output_directory(self.root) / "mesh.stl"
        with patch("tools.model_library.resources.digest", wraps=digest) as hashed:
            entry = catalog(self.library, strict=True)[0]
        self.assertEqual(entry["revisions"]["mesh.stl"], digest(mesh))
        self.assertEqual(sum(call.args[0] == mesh for call in hashed.call_args_list), 1)
        # A new operation must detect corruption rather than reuse the previous hash.
        mesh.write_bytes(b"corrupted")
        with self.assertRaises(ValueError):
            catalog(self.library, strict=True)

    def test_hash_cache_rechecks_changed_and_replaced_files(self):
        from tools.model_library.resources import DigestCache, digest

        path = self.root / "file.bin"
        path.write_bytes(b"before")
        hashes = DigestCache()
        before = hashes(path)
        self.assertEqual(hashes(path), before)
        path.write_bytes(b"after!")
        self.assertEqual(hashes(path), digest(path))
        self.assertNotEqual(hashes(path), before)
        replacement = self.root / "replacement.bin"
        replacement.write_bytes(b"new!!!")
        replacement.replace(path)
        self.assertEqual(hashes(path), digest(path))
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            hashes(path)

    def test_modified_delivery_resources_reject_catalog_and_site(self):
        model = self.generated()
        model["publish"] = ["extra.png"]
        script = (self.root / "build.py").read_text()
        (self.root / "build.py").write_text(
            script + "Image.new('RGB',(2,2)).save(p/'extra.png')\n"
        )
        write_manifest(self.root, model)
        build(self.root, model)
        output = output_directory(self.root)
        report = current_report(self.root, model)
        self.assertEqual(
            set(report["outputs"]), {"mesh.stl", "preview.png", "extra.png"}
        )
        for name in ("preview.png", "extra.png"):
            with self.subTest(name=name):
                original = (output / name).read_bytes()
                (output / name).write_bytes(b"corrupted")
                with self.assertRaisesRegex(ValueError, "产物校验过期"):
                    current_report(self.root, model)
                self.assertIsNone(catalog(self.library)[0]["validation"])
                with self.assertRaises(ValueError):
                    site(self.library, self.library / "tmp/site")
                (output / name).write_bytes(original)
        # Adding a publish entry must also require fresh acceptance.
        Image.new("RGB", (2, 2)).save(output / "new.png")
        changed = model | {"publish": ["extra.png", "new.png"]}
        with self.assertRaisesRegex(ValueError, "产物校验过期"):
            current_report(self.root, changed)

    def mixed_model(self):
        model = self.generated()
        model["variants"].insert(
            0,
            dict(
                id="closed",
                name="Assembly",
                file="assembly.glb",
                purpose="display",
                units="m",
                up="Y",
            ),
        )
        (self.root / "parameters.json").write_text("{}")
        model["inputs"].append("parameters.json")
        script = (self.root / "build.py").read_text()
        script += "scene=trimesh.Scene(trimesh.creation.box(extents=[.1,.2,.3]))\nscene.export(p/'assembly.glb')\n"
        (self.root / "build.py").write_text(script)
        write_manifest(self.root, model)
        return model

    def test_mixed_variants_configuration_and_shared_report_expiry(self):
        model = self.mixed_model()
        self.assertEqual(discover(self.library)[0][1], model)
        build(self.root, model)
        report = current_report(self.root, model)
        assembly, printed = report["files"]
        self.assertEqual(
            (assembly["purpose"], assembly["units"], assembly["up"]),
            ("display", "m", "Y"),
        )
        self.assertEqual(
            (printed["purpose"], printed["units"], printed["up"]), ("print", "mm", "Z")
        )
        np.testing.assert_allclose(assembly["dimensions"], [0.1, 0.2, 0.3])
        entry = catalog(self.library, strict=True)[0]
        self.assertEqual(entry["variants"][1]["purpose"], "print")
        self.assertEqual(entry["variants"][0]["units"], "m")
        # Changing a variant configuration invalidates the prior acceptance.
        changed = model | {
            "variants": [
                model["variants"][0],
                model["variants"][1] | {"purpose": "display"},
            ]
        }
        with self.assertRaises(ValueError):
            current_report(self.root, changed)
        # One input invalidates the complete report for both kinds of variant.
        (self.root / "parameters.json").write_text('{"changed": true}')
        with self.assertRaises(ValueError):
            current_report(self.root, model)
        self.assertIsNone(catalog(self.library)[0]["validation"])
        with self.assertRaises(ValueError):
            site(self.library, self.library / "tmp/site")
        build(self.root, model)
        self.assertTrue(
            all(row["passed"] for row in current_report(self.root, model)["files"])
        )

    def test_mixed_display_does_not_relax_print_acceptance(self):
        model = self.mixed_model()
        build(self.root, model)
        before = (output_directory(self.root) / "mesh.stl").read_bytes()
        script = (self.root / "build.py").read_text()
        # An open GLB is valid for display; the same opening must fail printing.
        opening = "mesh=trimesh.creation.box()\nmesh.update_faces(list(range(len(mesh.faces)-1)))\n"
        (self.root / "build.py").write_text(
            script + opening + "trimesh.Scene(mesh).export(p/'assembly.glb')\n"
        )
        build(self.root, model)
        (self.root / "build.py").write_text(
            script + opening + "mesh.export(p/'mesh.stl')\n"
        )
        with self.assertRaises(ValueError):
            build(self.root, model)
        self.assertEqual(
            (output_directory(self.root) / "mesh.stl").read_bytes(), before
        )

    def test_invalid_variant_configurations(self):
        model = self.mixed_model()
        for changes in (
            {"purpose": "print"},
            {"purpose": None},
            {"units": "mm"},
            {"up": "Z"},
            {"file": "assembly.obj"},
            {"file": "../assembly.glb"},
        ):
            with self.subTest(changes=changes):
                write_manifest(
                    self.root, model | {"variants": [model["variants"][0] | changes]}
                )
                with self.assertRaises(ValueError):
                    discover(self.library)
        for changes in ({"units": "inch"}, {"up": "X"}):
            with self.subTest(changes=changes):
                write_manifest(
                    self.root, model | {"variants": [model["variants"][1] | changes]}
                )
                with self.assertRaises(ValueError):
                    discover(self.library)

    def test_site_reads_utf8_with_non_utf8_default(self):
        model = self.generated()
        model["name"] = "中文模型😀"
        (self.root / "model.json").write_text(
            json.dumps(model, ensure_ascii=False), encoding="utf-8"
        )
        build(self.root, model)
        read_text = Path.read_text

        def non_utf8_read(path, *args, **kwargs):
            kwargs.setdefault("encoding", "gbk")
            return read_text(path, *args, **kwargs)

        target = self.library / "tmp/site"
        with patch.object(Path, "read_text", non_utf8_read):
            site(self.library, target)
        entry = json.loads((target / "catalog.json").read_text(encoding="utf-8"))[0]
        self.assertEqual(entry["name"], model["name"])

    def test_imported_gltf_embeds_dependencies_and_tracks_source_changes(self):
        model = self.generated()
        source = self.root / "source"
        source.mkdir()
        for name, data in (
            trimesh.Scene(trimesh.creation.box()).export(file_type="gltf").items()
        ):
            (source / name).write_bytes(data)
        Image.new("RGB", (2, 2)).save(source / "preview.png")
        (self.root / "build.py").write_text(
            "import os,shutil\nfrom pathlib import Path\np=Path(os.environ['MODEL_OUTPUT_DIR'])\nfor f in Path('source').iterdir():\n    shutil.copy2(f,p/f.name)\n"
        )
        model.update(
            purpose="display",
            units="m",
            up="Y",
            variants=[dict(id="main", name="Main", file="model.gltf")],
        )
        model["inputs"] += [str(p.relative_to(self.root)) for p in source.iterdir()]
        write_manifest(self.root, model)
        build(self.root, model)
        entry = catalog(self.library, strict=True)[0]
        self.assertTrue(
            dependencies(output_directory(self.root), "model.glb") == {"model.glb"}
        )
        self.assertEqual(entry["variants"][0]["file"], "model.glb")
        self.assertNotIn("model.gltf", entry["assets"])
        self.assertFalse(any(name.endswith(".bin") for name in entry["assets"]))
        next(source.glob("*.bin")).write_bytes(b"changed")
        with self.assertRaises(ValueError):
            current_report(self.root, model)

    def test_imported_external_glb_publishes_only_packed_model(self):
        from tests.tooling.test_gltf import glb

        model = self.generated()
        source = self.root / "source"
        source.mkdir()
        exported = trimesh.Scene(trimesh.creation.box()).export(file_type="gltf")
        data = json.loads(exported.pop("model.gltf"))
        Image.new("RGB", (2, 2), "blue").save(source / "texture.png")
        data["images"] = [{"uri": "texture.png"}]
        (source / "model.glb").write_bytes(glb(data))
        for name, raw in exported.items():
            (source / name).write_bytes(raw)
        Image.new("RGB", (2, 2)).save(source / "preview.png")
        (self.root / "build.py").write_text(
            "import os,shutil\nshutil.copytree('source',os.environ['MODEL_OUTPUT_DIR'],dirs_exist_ok=True)\n"
        )
        model.update(
            purpose="display",
            units="m",
            up="Y",
            variants=[dict(id="main", name="Main", file="model.glb")],
        )
        model["inputs"] += [
            str(path.relative_to(self.root)) for path in source.iterdir()
        ]
        write_manifest(self.root, model)
        original = (source / "model.glb").read_bytes()
        build(self.root, model)
        current_report(self.root, model)
        self.assertEqual((source / "model.glb").read_bytes(), original)
        self.assertEqual(
            dependencies(output_directory(self.root), "model.glb"), {"model.glb"}
        )
        target = self.library / "tmp/site"
        site(self.library, target)
        entry = json.loads((target / "catalog.json").read_text())[0]
        self.assertEqual(
            set(entry["assets"]), {"model.glb", "preview.png", "README.md"}
        )
        self.assertEqual(
            (target / "models/example/model.glb").read_bytes(),
            (output_directory(self.root) / "model.glb").read_bytes(),
        )
        # A missing dependency fails without replacing the accepted output.
        before = (output_directory(self.root) / "model.glb").read_bytes()
        (source / "texture.png").unlink()
        model["inputs"].remove("source/texture.png")
        with self.assertRaises(ValueError):
            build(self.root, model)
        self.assertEqual(
            (output_directory(self.root) / "model.glb").read_bytes(), before
        )

    def test_dependency_order_and_invalid_dependency(self):
        a = (self.root, {"id": "a", "depends_on": ["z"]})
        z = (self.root.parent / "z", {"id": "z"})
        self.assertEqual(build_order([a, z]), [z, a])
        z[1]["depends_on"] = ["a"]
        with self.assertRaises(ValueError):
            build_order([a, z])
        model = self.generated()
        model["depends_on"] = ["missing"]
        write_manifest(self.root, model)
        with self.assertRaises(ValueError):
            discover(self.library)

    def test_publish_failure_preserves_output(self):
        model = self.generated()
        build(self.root, model)
        target = output_directory(self.root)
        before = (target / "mesh.stl").read_bytes()
        replace = Path.replace

        def fail(src, dst):
            if src.name == "output":
                raise OSError("failure")
            return replace(src, dst)

        with patch.object(Path, "replace", fail), self.assertRaises(OSError):
            build(self.root, model, force=True)
        self.assertEqual(before, (target / "mesh.stl").read_bytes())

    def test_manual_slicing_does_not_affect_build_validation_or_site(self):
        from tools.slicing import save_report, source_hashes

        model = self.generated()
        build(self.root, model)
        target = output_directory(self.root)
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in target.iterdir()}
        work = self.library / "tmp/slicing"
        work.mkdir(parents=True)
        report = save_report(work, {"status": "complete"}, target, source_hashes(target, ["mesh.stl"]))
        self.assertEqual(json.loads((work / "slicing-validation.json").read_text()), report)
        self.assertFalse(build(self.root, model))
        self.assertEqual(before, {
            p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in target.iterdir()
        })
        # A missing or broken manual report cannot invalidate the model or site.
        (work / "slicing-validation.json").write_text("broken")
        current_report(self.root, model)
        self.assertFalse(build(self.root, model))
        (work / "slicing-validation.json").unlink()
        site(self.library, self.library / "tmp/site")
        self.assertFalse((self.library / "tmp/site/models/example/slicing-validation.json").exists())
        (self.root / "slice.py").write_text("raise RuntimeError('manual only')\n")
        self.assertFalse(build(self.root, model))
        # Geometry rebuilds must not reset or replace independent audit results.
        (work / "slicing-validation.json").write_text(json.dumps(report))
        build(self.root, model, force=True)
        self.assertEqual(json.loads((work / "slicing-validation.json").read_text()), report)
        (self.root / "build.py").write_text(
            (self.root / "build.py").read_text()
            + "trimesh.creation.box(extents=[2,1,1]).export(p/'mesh.stl')\n"
        )
        self.assertTrue(build(self.root, model))
        self.assertEqual(current_report(self.root, model)["files"][0]["dimensions"], [2, 1, 1])
        self.assertEqual(json.loads((work / "slicing-validation.json").read_text()), report)
        self.assertNotEqual(report["source_sha256"], source_hashes(target, ["mesh.stl"]))

    def test_publish_site_moves_complete_staging_and_replaces_previous_output(self):
        staged = self.library / "tmp/site"
        staged.mkdir(parents=True)
        (staged / "catalog.json").write_text("[]")
        (staged / "index.html").write_text("new")
        (staged / "models").mkdir()
        target = self.library / "dist"
        target.mkdir()
        (target / "catalog.json").write_text("[]")
        (target / "index.html").write_text("old")
        publish_site(staged, target)
        self.assertFalse(staged.exists())
        self.assertEqual((target / "index.html").read_text(), "new")
        self.assertTrue((target / "models").is_dir())

    def test_publish_site_rejects_incomplete_or_overlapping_staging(self):
        staged = self.library / "tmp/site"
        staged.mkdir(parents=True)
        (staged / "catalog.json").write_text("[]")
        with self.assertRaisesRegex(ValueError, "index.html"):
            publish_site(staged, self.library / "dist")
        (staged / "index.html").write_text("new")
        with self.assertRaisesRegex(ValueError, "不能重叠"):
            publish_site(staged, staged / "dist")

    def test_publish_site_rejects_non_site_target(self):
        staged = self.library / "tmp/site"
        staged.mkdir(parents=True)
        (staged / "catalog.json").write_text("[]")
        (staged / "index.html").write_text("new")
        target = self.library / "notes"
        target.mkdir()
        note = target / "keep.txt"
        note.write_text("keep")
        with self.assertRaisesRegex(ValueError, "不是已有站点"):
            publish_site(staged, target)
        self.assertEqual(note.read_text(), "keep")
        self.assertTrue(staged.is_dir())

    def test_site_rejects_source_and_build_directories(self):
        model = self.generated()
        build(self.root, model)
        for target in (
            self.library,
            self.root,
            self.library / "build",
            output_directory(self.root),
        ):
            with self.subTest(target=target), self.assertRaises(ValueError):
                site(self.library, target)

    def test_publish_rejects_internal_resources(self):
        model = self.generated()
        for name in (
            "src/build.py",
            "parameters.json",
            "validation.json",
            "references/source.png",
            "../outside.png",
        ):
            write_manifest(self.root, model | {"publish": [name]})
            with self.subTest(name=name), self.assertRaises(ValueError):
                discover(self.library)

    def test_incremental_build_reuses_geometry_and_readme_updates_packaging(self):
        model = self.generated()
        self.assertTrue(build(self.root, model))
        target = output_directory(self.root)
        before = {
            p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in target.iterdir()
        }
        with patch("tools.model_library.building.subprocess.run") as run:
            self.assertFalse(build(self.root, model))
            self.assertFalse(build(self.root, model))
            run.assert_not_called()
        (self.root / "README.md").write_text("Updated documentation")
        with patch("tools.model_library.building.subprocess.run") as run:
            self.assertTrue(build(self.root, model))
            run.assert_not_called()
        for name, value in before.items():
            if name not in {"README.md", "packaging-validation.json"}:
                self.assertEqual(value, ((target / name).read_bytes(), (target / name).stat().st_mtime_ns))
        site(self.library, self.library / "tmp/site")
        self.assertEqual(
            (self.library / "tmp/site/models/example/README.md").read_text(),
            "Updated documentation",
        )
        self.assertTrue(build(self.root, model, force=True))

    def test_incremental_build_rebuilds_invalid_reports_and_outputs(self):
        model = self.generated()
        build(self.root, model)
        output = output_directory(self.root)
        for data in ("broken", "null", "{}", '{"version": 1}'):
            with self.subTest(report=data):
                (output / "validation.json").write_text(data)
                self.assertTrue(build(self.root, model))
                current_report(self.root, model)
        for name in ("mesh.stl", "preview.png", "validation.json"):
            for missing in (False, True):
                with self.subTest(file=name, missing=missing):
                    if missing:
                        (output / name).unlink()
                    else:
                        (output / name).write_text("broken")
                    self.assertTrue(build(self.root, model))
        report = json.loads((output / "validation.json").read_text())
        for files in (None, [None], []):
            (output / "validation.json").write_text(
                json.dumps(report | {"files": files})
            )
            self.assertTrue(build(self.root, model))

    def test_incremental_build_tracks_manifest_inputs_and_shared_building(self):
        model = self.generated()
        build(self.root, model)
        (self.root / "build.py").write_text(
            (self.root / "build.py").read_text() + "# input change\n"
        )
        self.assertTrue(build(self.root, model))
        model["name"] = "Changed name"
        write_manifest(self.root, model)
        self.assertTrue(build(self.root, model))
        from tools.model_library.resources import digest

        def changed_digest(path):
            return "changed" if path.name == "building.py" else digest(path)

        with patch("tools.model_library.resources.digest", side_effect=changed_digest):
            self.assertTrue(build(self.root, model))
            self.assertFalse(build(self.root, model))
        self.assertTrue(build(self.root, model))
        (self.root / "build.py").unlink()
        with self.assertRaises(ValueError):
            build(self.root, model)

    def test_incremental_dependency_propagation(self):
        from tools.model_library.building import build_library

        upstream = self.generated()
        upstream["inputs"].append("parameters.json")
        (self.root / "parameters.json").write_text("1")
        (self.root / "build.py").write_text(
            (self.root / "build.py").read_text()
            + "trimesh.creation.box(extents=[float(Path('parameters.json').read_text()),1,1]).export(p/'mesh.stl')\n"
        )
        write_manifest(self.root, upstream)
        downstream = self.library / "models/downstream"
        downstream.mkdir()
        model = upstream | {
            "id": "downstream",
            "depends_on": ["example"],
            "inputs": ["build.py", "../../build/models/example/mesh.stl"],
        }
        (downstream / "README.md").write_text("Downstream")
        (downstream / "build.py").write_text(
            "import os, shutil\nfrom pathlib import Path\np=Path(os.environ['MODEL_OUTPUT_DIR'])\nfor name in ['mesh.stl','preview.png']:\n    shutil.copy2(Path('../../build/models/example')/name,p/name)\n"
        )
        write_manifest(downstream, model)
        build_library(self.library)
        self.assertFalse(build(downstream, model))
        (self.root / "parameters.json").write_text("2")
        build_library(self.library)
        self.assertEqual(
            current_report(downstream, model)["files"][0]["dimensions"], [2, 1, 1]
        )
        self.assertFalse(build(downstream, model))

    def test_incremental_cache_tracks_requirements_and_runtime_versions(self):
        from tools.model_library.resources import digest, input_hashes
        from importlib.metadata import version

        model = self.generated()
        build(self.root, model)
        before = input_hashes(self.root, model)
        changes = [
            patch(
                "tools.model_library.resources.digest",
                side_effect=lambda p: "changed" if p.name == "requirements.txt" else digest(p),
            ),
            patch("tools.model_library.resources.sys.version", "changed Python"),
            patch(
                "tools.model_library.resources.metadata.version",
                side_effect=lambda name: "changed" if name == "trimesh" else version(name),
            ),
        ]
        for change in changes:
            with change:
                self.assertNotEqual(before, input_hashes(self.root, model))
                with self.assertRaisesRegex(ValueError, "构建输入已改变"):
                    current_report(self.root, model)
        # One representative environment change exercises the actual rebuild.
        with changes[0]:
            self.assertTrue(build(self.root, model))
            self.assertFalse(build(self.root, model))

    def test_incremental_cache_ignores_site_tools_and_unconsumed_helpers(self):
        from tools.model_library.resources import digest

        model = self.generated()
        build(self.root, model)
        target = output_directory(self.root)
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in target.iterdir()}
        for filename in (
            "build.mjs", "model-plugin.mjs", "python.mjs", "runtime.mjs",
            "models.py", "bookmark_relief.py", "assembly_gltf.py", "slicing.py", "publication.py",
        ):
            with self.subTest(file=filename), patch(
                "tools.model_library.resources.digest",
                side_effect=lambda p: "changed" if p.name == filename else digest(p),
            ), patch("tools.model_library.building.subprocess.run") as run:
                self.assertFalse(build(self.root, model))
                run.assert_not_called()
                current_report(self.root, model)
        self.assertEqual(
            before,
            {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in target.iterdir()},
        )
        helper = self.library / "tools/bookmark_relief.py"
        helper.parent.mkdir()
        helper.write_text("# shared algorithm\n")
        model["inputs"].append("../../tools/bookmark_relief.py")
        write_manifest(self.root, model)
        build(self.root, model)
        helper.write_text("# changed algorithm\n")
        self.assertTrue(build(self.root, model))
        self.assertFalse(build(self.root, model))

    def test_incremental_cache_tracks_assembly_writer(self):
        model = self.generated()
        helper = self.library / "tools/assembly_gltf.py"
        helper.parent.mkdir(exist_ok=True)
        helper.write_text("# assembly writer\n")
        model["inputs"].append("../../tools/assembly_gltf.py")
        write_manifest(self.root, model)
        self.assertTrue(build(self.root, model))
        self.assertFalse(build(self.root, model))
        helper.write_text("# changed assembly writer\n")
        self.assertTrue(build(self.root, model))
        self.assertFalse(build(self.root, model))

    def test_discovery_rejects_missing_sources_and_site_rejects_empty_library(self):
        from tools.model_library.building import build_library

        model = self.generated()
        build(self.root, model)
        target = self.library / "tmp/site"
        site(self.library, target)
        before = (target / "catalog.json").read_bytes()
        (self.root / "model.json").unlink()
        for operation in (
            lambda: build_library(self.library),
            lambda: catalog(self.library, strict=True),
            lambda: site(self.library, target),
        ):
            with self.assertRaisesRegex(ValueError, "缺少 model.json"):
                operation()
        self.assertEqual(before, (target / "catalog.json").read_bytes())
        with self.assertRaisesRegex(ValueError, "模型库目录不存在"):
            discover(self.library / "absent")
        empty = self.library / "empty"
        (empty / "models/.hidden").mkdir(parents=True)
        (empty / "models/README.md").write_text("ignored")
        self.assertEqual(discover(empty), [])
        self.assertEqual(catalog(empty), [])
        with self.assertRaisesRegex(ValueError, "模型库为空"):
            site(empty, target)
        self.assertEqual(before, (target / "catalog.json").read_bytes())

    def test_real_models_ignore_manual_slice_code_changes(self):
        from tools.model_library.resources import digest, input_hashes

        repo = Path(__file__).resolve().parents[2]
        for directory, model in discover(repo):
            before = input_hashes(directory, model)
            with self.subTest(model=model["id"]), patch(
                "tools.model_library.resources.digest",
                side_effect=lambda p: "changed" if p.name in {"slice.py", "slicing.py"} else digest(p),
            ):
                self.assertEqual(before, input_hashes(directory, model))
