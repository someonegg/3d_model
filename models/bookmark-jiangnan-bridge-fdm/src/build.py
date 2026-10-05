"""Build the Jiangnan filament-painting bookmark with shared geometry."""

import os
from pathlib import Path

from bookmark_relief import build as _build

SOURCE = Path(__file__).resolve().parents[1]


def build(out):
    _build(SOURCE, out, "JIANGNAN / 45 x 150 mm", "bookmark-jiangnan-bridge-fdm.stl")


def main():
    build(os.environ["MODEL_OUTPUT_DIR"])


if __name__ == "__main__":
    main()
