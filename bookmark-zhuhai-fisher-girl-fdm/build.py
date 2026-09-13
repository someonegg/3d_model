"""Build the Zhuhai filament-painting bookmark with shared geometry."""
from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from bookmark_relief import build as _build

SOURCE = Path(__file__).resolve().parent


def build(out):
    _build(SOURCE, out, 'ZHUHAI / 45 x 150 mm',
           'bookmark-zhuhai-fisher-girl-fdm.stl')


if __name__ == '__main__':
    build(os.environ.get('MODEL_OUTPUT_DIR', SOURCE))
