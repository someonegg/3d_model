"""Build a photo-inspired lovebird filament bookmark without cropping the bird."""

import json
import os
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1]
from bookmark_relief import build as build_bookmark, artwork as _artwork
from preview import mesh_previews


def artwork():
    config = json.loads((SOURCE / 'parameters.json').read_text())
    tones = config['tone_values']
    return _artwork(SOURCE, tones, **config['image_processing']), tones


def main():
    out = Path(os.environ["MODEL_OUTPUT_DIR"])
    out.mkdir(parents=True, exist_ok=True)
    build_bookmark(SOURCE, out, "LOVEBIRD / 45 x 150 mm", "bookmark-lovebird-fdm.stl")
    mesh_previews(out)



if __name__ == "__main__":
    main()
