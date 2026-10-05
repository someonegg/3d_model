"""Optional local Bambu Studio slicing audit. Geometry builds do not require Studio."""

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


from tools.slicing import (
    prepare_profiles, audit_files, model_directory, resolve_profiles, run_studio, save_report,
    slicing_workspace, source_hashes,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--studio", default="/Applications/BambuStudio.app/Contents/MacOS/BambuStudio"
    )
    parser.add_argument(
        "--profiles",
        default="/Applications/BambuStudio.app/Contents/Resources/profiles/BBL",
    )
    parser.add_argument("--model-dir", type=Path, default=model_directory(HERE))
    parser.add_argument(
        "--output-dir", type=Path, default=HERE.parents[1] / "tmp/xc60-slicing"
    )
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    source = args.model_dir.resolve()
    if source != model_directory(HERE):
        raise ValueError("--model-dir 必须指向当前模型的 build/models 目录")
    root = slicing_workspace(HERE, args.output_dir)
    inputs = source_hashes(source, ["assembly.json"])
    plates = json.loads((source / "assembly.json").read_text())["plates"]
    files = ["fit-coupon.stl"] + [row["file"] for row in plates]
    if args.only:
        files = [f for f in files if f in args.only]
    if not files:
        raise ValueError("没有匹配的切片文件")
    inputs.update(source_hashes(source, files))
    overrides = dict(
        layer_height="0.16",
        initial_layer_print_height="0.2",
        wall_loops="4",
        sparse_infill_density="15%",
        enable_support="1",
        support_type="tree(auto)",
        support_on_build_plate_only="0",
        support_threshold_angle="30",
        support_top_z_distance="0.2",
        support_object_xy_distance="0.35",
        brim_type="auto_brim",
        brim_width="3",
        outer_wall_speed=["50", "50", "50"],
    )
    def check(archive, config, gcode, plate, path):
        assert "256x256" in config["printable_area"], config["printable_area"]
        assert float(config["filament_density"][0]) > 1
        assert "; FEATURE: Outer wall" in gcode or ";TYPE:External perimeter" in gcode
        return {}
    prepare_profiles(root, args.profiles, "0.16mm Standard @BBL P2S", overrides, resolver=resolve_profiles)
    common = audit_files(args.studio, root, source, files, inputs, arrange=0,
                         expected={"layer_height": "0.16", "wall_loops": "4", "enable_support": "1"}, callback=check,
                         runner=run_studio)
    report = {
        "status": "complete" if len(files) == len(plates) + 1 else "partial",
        "printer": "Bambu Lab P2S",
        "nozzle_mm": 0.4,
        "layer_mm": 0.16,
        "first_layer_mm": 0.2,
        "wall_loops": 4,
        "infill_percent": 15,
        "supports": "tree(auto)",
    }
    report.update(common)
    report = save_report(root, report, source, inputs)
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
