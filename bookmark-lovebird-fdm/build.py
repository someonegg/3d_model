"""Build a photo-inspired lovebird filament bookmark without cropping the bird."""
from pathlib import Path
import os
import sys
import json
import numpy as np
from PIL import Image, ImageOps
from scipy.ndimage import gaussian_filter, median_filter

SOURCE = Path(__file__).resolve().parent
sys.path.insert(0, str(SOURCE.parent / 'tools'))
from bookmark_relief import gray_to_layers, bookmark_mesh, preview


def artwork():
    # Full-height botanical artwork; crop outer blank margins without stretching.
    image = ImageOps.fit(Image.open(SOURCE / 'source.png').convert('L'),
                         (301, 1001), method=Image.Resampling.LANCZOS,
                         centering=(.55, .5))
    gray = gaussian_filter(median_filter(np.asarray(image, dtype=float), 3), 1.1)
    low, high = np.percentile(gray, [1, 99])
    gray = np.clip((gray-low)*255/(high-low), 0, 255)
    tones = json.loads((SOURCE / 'parameters.json').read_text())['tone_values']
    return gray_to_layers(gray, tones), tones


if __name__ == '__main__':
    out = Path(os.environ.get('MODEL_OUTPUT_DIR', SOURCE))
    out.mkdir(parents=True, exist_ok=True)
    levels, tones = artwork()
    bookmark_mesh(levels).export(out / 'bookmark-lovebird-fdm.stl')
    preview(out, levels, tones, 'LOVEBIRD / 45 x 150 mm')
