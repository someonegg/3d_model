from pathlib import Path
import json
import os
import sys
import numpy as np
import trimesh

SOURCE = Path(__file__).resolve().parent
sys.path.insert(0, str(SOURCE.parent / 'tools'))
from bookmark_relief import BASE, LAYER, PITCH, artwork

OUT = Path(os.environ['MODEL_OUTPUT_DIR'])


def require(condition, message):
    if not condition:
        raise ValueError(message)


book = trimesh.load(OUT/'bookmark-zhuhai-fisher-girl-fdm.stl', process=False)
connected = book.copy()
connected.merge_vertices()
require(connected.body_count == 1, 'Bookmark must be one connected solid')
np.testing.assert_allclose(book.extents, [45, 150, 1.32], atol=1e-6)
require(abs(book.bounds[0, 2]) < 1e-6, 'Bookmark bottom must be flat at zero')
top = book.vertices[book.vertices[:, 2] > 0]
steps = (top[:, 2] - BASE) / LAYER
require(top[:, 2].min() >= BASE-1e-6, 'Bookmark base is too thin')
np.testing.assert_allclose(steps, np.rint(steps), atol=1e-5)
require(np.rint(steps).min() >= 0 and np.rint(steps).max() <= 10,
        'Bookmark height exceeds the 0-10 white-layer range')
require(not np.any(np.all(np.isclose(book.vertices[:, :2], [0, 0]), axis=1)),
        'Rounded corner missing')

parameters = json.loads((SOURCE/'parameters.json').read_text(encoding='utf-8'))
levels = artwork(SOURCE, parameters['tone_values'])
# Image row zero maps to the +Y edge of the delivered STL.
rows = np.rint((150-top[:, 1])/PITCH).astype(int).clip(0, levels.shape[0]-1)
cols = np.rint(top[:, 0]/PITCH).astype(int).clip(0, levels.shape[1]-1)
np.testing.assert_allclose(top[:, 2], BASE+LAYER*levels[rows, cols], atol=1e-6)

# Preserve the two narrow bright gaps separating the head from the raised arms.
for name, row, col in [('left_head_gap', .240, .395),
                       ('right_head_gap', .240, .580)]:
    r, c = round(row*1000), round(col*300)
    widths = []
    for rr in range(r-2, r+3):
        region = levels[rr] >= 8
        lo = hi = c
        if not region[c]:
            widths.append(0.)
            continue
        while lo > 0 and region[lo-1]:
            lo -= 1
        while hi < 300 and region[hi+1]:
            hi += 1
        widths.append((hi-lo+1)*PITCH)
    minimum = min(widths)
    require(minimum >= .4, f'{name}: width {minimum:.3f} mm below 0.4 mm')
