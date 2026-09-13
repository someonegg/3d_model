"""Publish assembly states from the validated print build."""
from pathlib import Path
import json
import os
import shutil
import sys

HERE = Path(__file__).resolve().parents[1]
SOURCE = HERE.parent / 'volvo-xc60-2022'
sys.path.insert(0, str(HERE.parents[1] / 'tools'))
from model_library.validation import current_report


def main():
    model = json.loads((SOURCE / 'model.json').read_text(encoding='utf-8'))
    current_report(SOURCE, model)
    out = Path(os.environ.get('MODEL_OUTPUT_DIR', HERE))
    out.mkdir(parents=True, exist_ok=True)
    for name in ('assembled.glb', 'doors-open.glb', 'preview.png',
                 'doors-open.png', 'exploded.png', 'rear.png'):
        shutil.copyfile(SOURCE / name, out / name)


if __name__ == '__main__':
    main()
