"""Manifest-driven model build, validation and static staging."""
from pathlib import Path
import argparse
import json
import sys
from model_library.pipeline import build, catalog, publish_site, site, validate
from model_library.resources import discover

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['build', 'validate', 'site', 'publish', 'catalog'])
    parser.add_argument('id', nargs='?')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, help='site or publish output directory')
    parser.add_argument('--staging', type=Path, help='publish staging directory (default: <root>/tmp/site)')
    args = parser.parse_args()
    root = args.root.resolve()
    if args.output and args.command not in ('site', 'publish'):
        parser.error('--output 仅适用于 site 或 publish')
    if args.staging and args.command != 'publish':
        parser.error('--staging 仅适用于 publish')
    try:
        if args.command == 'site':
            site(root, (args.output or root / 'tmp/site').resolve())
        elif args.command == 'publish':
            publish_site((args.staging or root / 'tmp/site').resolve(),
                         (args.output or root / 'dist').resolve())
        elif args.command == 'catalog':
            print(json.dumps(catalog(root), ensure_ascii=False))
        else:
            selected = [(d, m) for d, m in discover(root) if args.all or m['id'] == args.id]
            if not selected:
                raise ValueError('请指定有效模型 ID 或 --all')
            action = {'build': build, 'validate': validate}[args.command]
            for directory, model in selected:
                action(directory, model)
                print(f"{args.command}: {model['id']} 完成")
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
