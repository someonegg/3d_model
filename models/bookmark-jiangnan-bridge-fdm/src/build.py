"""Build the Jiangnan filament-painting bookmark with shared geometry."""
from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tools'))
from bookmark_relief import build as _build

SOURCE = Path(__file__).resolve().parents[1]


def build(out):
    _build(SOURCE, out, 'JIANGNAN / 45 x 150 mm',
           'bookmark-jiangnan-bridge-fdm.stl')


def main():
    build(os.environ.get('MODEL_OUTPUT_DIR', SOURCE))


if __name__ == '__main__':
    main()
