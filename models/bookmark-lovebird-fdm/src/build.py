"""Build a photo-inspired lovebird filament bookmark without cropping the bird."""

import json
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from scipy.ndimage import gaussian_filter, median_filter

SOURCE = Path(__file__).resolve().parents[1]
from bookmark_relief import bookmark_mesh, gray_to_layers, preview


def artwork():
    # Full-height botanical artwork; crop outer blank margins without stretching.
    image = ImageOps.fit(
        Image.open(SOURCE / "references/source.png").convert("L"),
        (301, 1001),
        method=Image.Resampling.LANCZOS,
        centering=(0.55, 0.5),
    )
    gray = gaussian_filter(median_filter(np.asarray(image, dtype=float), 3), 1.1)
    low, high = np.percentile(gray, [1, 99])
    gray = np.clip((gray - low) * 255 / (high - low), 0, 255)
    tones = json.loads((SOURCE / "parameters.json").read_text())["tone_values"]
    return gray_to_layers(gray, tones), tones


def main():
    out = Path(os.environ["MODEL_OUTPUT_DIR"])
    out.mkdir(parents=True, exist_ok=True)
    levels, tones = artwork()
    bookmark_mesh(levels).export(out / "bookmark-lovebird-fdm.stl")
    preview(out, levels, tones, "LOVEBIRD / 45 x 150 mm")


if __name__ == "__main__":
    main()
