"""Manifest-driven model build, validation and static staging."""

import argparse
import json
import sys
from pathlib import Path

from model_library.building import build, build_library
from model_library.publication import catalog, publish_site, site
from model_library.resources import build_order, discover

REPO_ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("command", choices=["build", "site", "publish", "catalog"])
    parser.add_argument("id", nargs="?")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--library-root",
        type=Path,
        default=REPO_ROOT,
        help="model library directory (default: source repository)",
    )
    parser.add_argument("--output", type=Path, help="site or publish output directory")
    parser.add_argument(
        "--staging",
        type=Path,
        help="publish staging directory (default: <repository>/tmp/site)",
    )
    args = parser.parse_args()
    library_root = args.library_root.resolve()
    if args.output and args.command not in ("site", "publish"):
        parser.error("--output 仅适用于 site 或 publish")
    if args.staging and args.command != "publish":
        parser.error("--staging 仅适用于 publish")
    if args.force and args.command != "build":
        parser.error("--force 仅适用于 build")
    if args.id and args.command != "build":
        parser.error("模型 ID 仅适用于 build")
    try:
        if args.command == "site":
            site(library_root, (args.output or REPO_ROOT / "tmp/site").resolve())
        elif args.command == "publish":
            publish_site(
                (args.staging or REPO_ROOT / "tmp/site").resolve(),
                (args.output or REPO_ROOT / "dist").resolve(),
            )
        elif args.command == "catalog":
            print(json.dumps(catalog(library_root), ensure_ascii=False))
        else:
            if args.id:
                models = build_order(discover(library_root))
                required = {args.id}
                for _, model in reversed(models):
                    if model["id"] in required:
                        required.update(model.get("depends_on", []))
                if args.id not in {m["id"] for _, m in models}:
                    raise ValueError("无效模型 ID")
                for directory, model in models:
                    if model["id"] in required:
                        build(directory, model, force=args.force)
            else:
                build_library(library_root, force=args.force)
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
