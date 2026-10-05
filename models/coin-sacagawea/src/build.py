"""Export printable coin variants and their preview."""
from pathlib import Path
import os
import numpy as np
from PIL import Image, ImageFilter
from portrait import printable_obverse
from reverse import printable_reverse
from geometry import SOURCE, RELIEF, DIAMETER, topology, save_mesh
from preview import preview

def main():
    out = Path(os.environ['MODEL_OUTPUT_DIR'])
    out.mkdir(parents=True, exist_ok=True)
    PHOTO = Image.open(SOURCE / 'references/reference.jpg').convert('L').filter(ImageFilter.GaussianBlur(0.65))
    DATA = np.asarray(PHOTO, dtype=float) / 255
    OBVERSE_HEIGHTS = printable_obverse(RELIEF * np.clip((DATA - 0.12) / 0.76, 0, 1) ** 0.75, DIAMETER)
    REVERSE_HEIGHTS = printable_reverse(RELIEF * np.clip((DATA - 0.12) / 0.76, 0, 1) ** 0.75, DIAMETER)
    fields = {'obverse': OBVERSE_HEIGHTS, 'reverse': REVERSE_HEIGHTS}
    topology_data = topology()
    save_mesh(out, fields, topology_data, 'coin-sacagawea-obverse.stl','obverse')
    save_mesh(out, fields, topology_data, 'coin-sacagawea-reverse.stl','reverse')
    save_mesh(out, fields, topology_data, 'coin-sacagawea-double-sided.stl','obverse','reverse')
    preview(out, fields)


if __name__ == '__main__':
    main()
