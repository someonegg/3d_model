"""Optional local P2S slicing audit, separate from reproducible geometry builds."""

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parents[1]


from tools.slicing import (
    prepare_profiles, audit_files, model_directory, resolve_profiles, run_studio, save_report,
    slicing_workspace, source_hashes,
)


def check_archive_geometry(archive, source):
    """Collect mode cannot attach a stale slice to a newer STL."""
    meshes = []
    for name in archive.namelist():
        if not name.endswith(".model"):
            continue
        for mesh in ET.fromstring(archive.read(name)).findall(".//{*}mesh"):
            vertices = [
                [float(v.attrib[k]) for k in ("x", "y", "z")]
                for v in mesh.findall("./{*}vertices/{*}vertex")
            ]
            faces = [
                [int(f.attrib[k]) for k in ("v1", "v2", "v3")]
                for f in mesh.findall("./{*}triangles/{*}triangle")
            ]
            meshes.append(trimesh.Trimesh(vertices, faces, process=False))
    actual = trimesh.util.concatenate(meshes)
    expected = trimesh.load(source, force="mesh")
    assert len(actual.faces) == len(expected.faces), "stale sliced mesh topology"
    for m in (actual, expected):
        m.apply_translation(-m.bounds.mean(axis=0))
    np.testing.assert_allclose(actual.extents, expected.extents, atol=2e-5)
    for a, b in ((actual, expected), (expected, actual)):
        distances, _ = cKDTree(a.triangles_center).query(b.triangles_center)
        assert max(distances) < 2e-5, "sliced geometry differs from current STL"


def extrusion_segments(gcode):
    layer = 0.0
    feature = ""
    relative = True
    position = dict(X=0.0, Y=0.0, Z=0.0, E=0.0)
    segments = []
    for line in gcode.splitlines():
        if line.startswith("; Z_HEIGHT:"):
            layer = round(float(line.split(":")[1]), 3)
        if line.startswith("; FEATURE:"):
            feature = line.split(":", 1)[1].strip()
        words = line.split(";", 1)[0].split()
        if not words:
            continue
        if words[0] in ("M82", "M83"):
            relative = words[0] == "M83"
        if words[0] == "G92":
            for word in words[1:]:
                if word[0] in position:
                    position[word[0]] = float(word[1:])
        if words[0] not in ("G0", "G1"):
            continue
        data = {word[0]: float(word[1:]) for word in words[1:] if word[0] in position}
        old = position.copy()
        e = data.get("E", 0) if relative else data.get("E", old["E"]) - old["E"]
        position.update(data)
        if e > 0 and ("X" in data or "Y" in data) and 0 < layer <= 5.4:
            segments.append(
                (
                    layer,
                    np.array([old["X"], old["Y"]]),
                    np.array([position["X"], position["Y"]]),
                    feature,
                )
            )
    return segments


def inspect_spring_paths(gcode, output, bounds):
    """Audit all compliant layers at beam-centre probes; retain toolpath overview."""
    segments = extrusion_segments(gcode)
    source = trimesh.load(model_directory(HERE) / "all-parts.stl", force="mesh")
    shift = np.array([bounds["x"], bounds["y"]]) - source.bounds[0, :2]
    checks = []
    canvas = Image.new("RGB", (1400, 1620), "#f5f2eb")
    draw = ImageDraw.Draw(canvas)
    for col, (part, center) in enumerate(
        (("return-spring", (9, 18)), ("click-spring", (49, 18)))
    ):
        center = np.array(center) + shift
        heights = (
            np.arange(0.2, 1.21, 0.2)
            if part == "return-spring"
            else np.arange(0.2, 1.61, 0.2)
        )
        for row, height in enumerate(np.round(heights, 3)):
            paths = [
                (a, b, f)
                for z, a, b, f in segments
                if z == height and np.all(np.abs((a + b) / 2 - center) < 15)
            ]
            assert paths, f"{part} missing layer {height}"
            # Continuous centreline coverage over both straight compliant arms.
            if part == "return-spring":
                probes = (
                    np.array(
                        [
                            (side * x, -side * 2.6)
                            for side in (-1, 1)
                            for x in np.linspace(-10, 7, 35)
                        ]
                    )
                    + center
                )
            else:
                # Printed upside down, so assembly Y reverses.
                probes = (
                    np.array(
                        [
                            (side * 11.2, -y)
                            for side in (-1, 1)
                            for y in np.linspace(-10, 1, 30)
                        ]
                    )
                    + center
                )
            starts = np.array([a for a, b, f in paths])
            vectors = np.array([b - a for a, b, f in paths])
            denom = np.sum(vectors * vectors, axis=1)
            for point in probes:
                t = np.clip(
                    np.sum((point - starts) * vectors, axis=1)
                    / np.maximum(denom, 1e-12),
                    0,
                    1,
                )
                distances = np.linalg.norm(
                    starts + t[:, None] * vectors - point, axis=1
                )
                assert min(distances) < 0.32, (
                    f"{part} discontinuous beam at Z={height}: {point}"
                )
            checks.append(
                dict(part=part, z_mm=height, beam_probes=len(probes), passed=True)
            )
            origin = np.array([90 + col * 700, 30 + row * 200])
            scale = 5.6
            draw.text(tuple(origin), f"{part} | Z {height:.1f} mm", fill="#253846")
            for a, b, f in paths:
                a = (a - center) * scale + origin + [240, 105]
                b = (b - center) * scale + origin + [240, 105]
                color = "#b56b2f" if "wall" in f.lower() else "#277f85"
                draw.line([tuple(a), tuple(b)], fill=color, width=2)
    canvas.save(output / "spring-toolpaths.png")
    return checks


def inspect_support_paths(gcode, output, bounds):
    """Check all four ramps narrow upward and retain an extruded seating pad."""
    segments = extrusion_segments(gcode)
    source = trimesh.load(model_directory(HERE) / "all-parts.stl", force="mesh")
    shift = np.array([bounds["x"], bounds["y"]]) - source.bounds[0, :2] + [-32, 18]
    canvas = Image.new("RGB", (1200, 1200), "#f5f2eb")
    draw = ImageDraw.Draw(canvas)
    checks = []
    for col, (x, y) in enumerate(((-12.8, 0), (12.8, 0), (0, -12.8), (0, 12.8))):
        center = shift + [x, y]
        edges = []
        for row, height in enumerate((4.6, 4.8, 5.0, 5.2)):
            paths = [
                (a - center, b - center)
                for z, a, b, f in segments
                if z == height and np.all(np.abs((a + b) / 2 - center) < 1.05)
            ]
            assert paths, f"support {col} missing layer {height}"
            starts = np.array([a for a, b in paths])
            vectors = np.array([b - a for a, b in paths])
            point = np.array([0.6, 0])
            t = np.clip(
                np.sum((point - starts) * vectors, axis=1)
                / np.maximum(np.sum(vectors * vectors, axis=1), 1e-12),
                0,
                1,
            )
            assert (
                min(np.linalg.norm(starts + t[:, None] * vectors - point, axis=1))
                < 0.32
            ), "missing support pad extrusion"
            edge = float(np.vstack(paths)[:, 0].min())
            edges.append(edge)
            checks.append(
                dict(
                    support_xy_mm=[x, y],
                    z_mm=height,
                    leading_path_x_mm=round(edge, 4),
                    passed=True,
                )
            )
            origin = np.array([150 + col * 300, 150 + row * 300])
            draw.text(
                tuple(origin + [-135, -135]), f"({x}, {y}) | Z {height}", fill="#253846"
            )
            # Nominal section at the middle of the printed 0.2 mm layer.
            left = -1 + max(0.0, height - 0.1 - 4.5) * 1.2 / 0.8
            draw.rectangle(
                [tuple(origin + [left * 90, -90]), tuple(origin + [90, 90])],
                outline="#b9b3a8",
                width=2,
            )
            for a, b in paths:
                draw.line(
                    [tuple(origin + a * 90), tuple(origin + b * 90)],
                    fill="#277f85",
                    width=3,
                )
        assert all(b >= a - 0.02 for a, b in zip(edges, edges[1:])), (
            "ramp reverses in sliced layers"
        )
        assert edges[-1] - edges[0] > 0.5, "ramp absent from sliced layers"
    canvas.save(output / "support-toolpaths.png")
    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--studio", default="/Applications/BambuStudio.app/Contents/MacOS/BambuStudio"
    )
    parser.add_argument(
        "--profiles",
        type=Path,
        default=Path("/Applications/BambuStudio.app/Contents/Resources/profiles/BBL"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=HERE.parents[1] / "tmp/keyboard-fidget-slicing",
    )
    parser.add_argument(
        "--collect-only",
        action="store_true",
        help="Verify and collect existing externally sliced 3MF outputs",
    )
    args = parser.parse_args()
    root = slicing_workspace(HERE, args.output_dir)
    source = model_directory(HERE)
    files = ("all-parts.stl",)
    inputs = source_hashes(source, files)
    overrides = dict(
        layer_height="0.2",
        initial_layer_print_height="0.2",
        wall_loops="3",
        sparse_infill_density="15%",
        enable_support="0",
        brim_type="no_brim",
        outer_wall_speed=["45", "45", "45"],
        inner_wall_speed=["80", "80", "80"],
        wall_generator="arachne",
        detect_thin_wall="0",
    )
    def check(archive, config, gcode, plate, path):
        check_archive_geometry(archive, path)
        bounds = plate["objects"][0]["bbox"] if path.name == "all-parts.stl" else None
        return dict(path_checks=inspect_spring_paths(gcode, root, bounds) if bounds else [],
                    support_path_checks=inspect_support_paths(gcode, root, bounds) if bounds else [])
    prepare_profiles(root, args.profiles, "0.20mm Standard @BBL P2S", overrides, resolver=resolve_profiles)
    common = audit_files(args.studio, root, source, files, inputs, arrange=1,
                         expected={"layer_height": "0.2", "enable_support": "0"}, callback=check,
                         runner=run_studio, collect_only=args.collect_only)
    report = dict(
        status="complete",
        printer="Bambu Lab P2S",
        nozzle_mm=0.4,
        layer_mm=0.2,
        first_layer_mm=0.2,
        wall_loops=3,
        infill_percent=15,
        supports=False,
    )
    report.update(common)
    report = save_report(root, report, source, inputs)
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
