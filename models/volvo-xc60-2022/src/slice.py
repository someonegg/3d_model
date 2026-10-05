"""Optional local Bambu Studio slicing audit. Geometry builds do not require Studio."""
from tools.slicing import slicing_parser, configure_slicing
from tools.slicing_geometry import check_archive_geometry


import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


from tools.slicing import audit_files, model_directory, resolve_profiles, run_studio, save_report, slicing_workspace, source_hashes


SLICING = json.loads((Path(__file__).resolve().parents[1] / 'slicing.json').read_text())


def main():
    parser = slicing_parser(HERE, 'xc60-slicing')
    parser.add_argument('--only', nargs='+')
    args = parser.parse_args()
    source = model_directory(HERE)
    root = slicing_workspace(HERE, args.output_dir)
    inputs = source_hashes(source, ["assembly.json"])
    plates = json.loads((source / "assembly.json").read_text())["plates"]
    files = ["fit-coupon.stl"] + [row["file"] for row in plates]
    if args.only:
        unknown = set(args.only) - set(files)
        if unknown:
            parser.error('未知切片文件：' + ', '.join(sorted(unknown)))
        files = [f for f in files if f in args.only]
    if not files:
        raise ValueError("没有匹配的切片文件")
    inputs.update(source_hashes(source, files))
    def check(archive, config, gcode, plate, path):
        check_archive_geometry(archive, path)
        assert "256x256" in config["printable_area"], config["printable_area"]
        assert float(config["filament_density"][0]) > 1
        assert "; FEATURE: Outer wall" in gcode or ";TYPE:External perimeter" in gcode
        return {}
    if configure_slicing(args, root, source, files, inputs, SLICING, resolver=resolve_profiles):
        return

    common = audit_files(args.studio, root, source, files, inputs, arrange=SLICING['arrange'],
                         expected=SLICING['expected'], callback=check,
                         runner=run_studio, collect_only=args.collect_only)
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
