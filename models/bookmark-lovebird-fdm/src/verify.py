"""Independently measure the delivered bookmark STL."""
from pathlib import Path
import os
import json
import numpy as np
import trimesh
from build import artwork

def main():
    OUT = Path(os.environ['MODEL_OUTPUT_DIR'])
    mesh = trimesh.load(OUT / 'bookmark-lovebird-fdm.stl', process=True)
    assert mesh.body_count == 1 and mesh.is_watertight
    np.testing.assert_allclose(mesh.extents, [45, 150, 1.32], atol=1e-6)
    assert abs(mesh.bounds[0, 2]) < 1e-6
    top = mesh.vertices[mesh.vertices[:, 2] > 0]
    steps = (top[:, 2]-.52)/.08
    np.testing.assert_allclose(steps, np.rint(steps), atol=1e-5)
    assert steps.min() >= -1e-5 and steps.max() <= 10.00001
    assert not np.any(np.all(np.isclose(mesh.vertices[:, :2], [0, 0]), axis=1))
    expected, _ = artwork()
    rows = np.rint((150-top[:, 1])/.15).astype(int).clip(0, 1000)
    cols = np.rint(top[:, 0]/.15).astype(int).clip(0, 300)
    np.testing.assert_allclose(top[:, 2], .52+.08*expected[rows, cols], atol=1e-6)
    height = np.full((1001, 301), np.nan)
    height[rows, cols] = top[:, 2]
    # Missing pixels are outside the rounded bookmark, not measured surface.
    valid = np.isfinite(height)
    height[~valid] = .52
    levels = np.rint((height-.52)/.08).astype(int)

    # Eye probe is fixed at the eye center in the cropped artwork.
    # Five adjacent X sections measure the contiguous dark eye aperture.
    eye_row, eye_col = 324, 95
    widths = []
    for row in range(eye_row-2, eye_row+3):
        dark = levels[row] <= 2
        assert dark[eye_col], 'Eye aperture lost at fixed anatomical probe'
        lo = hi = eye_col
        while lo > 0 and dark[lo-1]:
            lo -= 1
        while hi < 300 and dark[hi+1]:
            hi += 1
        widths.append((hi-lo)*.15)
    assert min(widths) >= .8, f'Eye narrower than two nozzle widths: {widths}'
    contrast = float(height[eye_row, eye_col+12]-height[eye_row, eye_col])
    assert contrast >= .24-1e-6, 'Eye/face contrast below three layers'

    (OUT / 'detail-validation.json').write_text(json.dumps({
        'dimensions_mm': mesh.extents.tolist(), 'body_count': mesh.body_count,
        'eye_probe_image_row_col': [eye_row, eye_col],
        'eye_dark_threshold_white_layers': 2,
        'eye_width_definition': 'Distance between outer sample centers of contiguous dark interval; five adjacent rows',
        'eye_widths_mm': widths, 'minimum_eye_width_mm': .8,
        'eye_face_height_difference_mm': contrast,
        'minimum_eye_face_difference_mm': .24,
        'first_layer_mm': .2, 'subsequent_layer_mm': .08,
        'total_layers': 15, 'white_start_layer': 6,
        'layer_preview': 'Vertex occupancy at layer tops, not extrusion paths or exact triangle intersections',
        'not_checked': ['full self-intersection', 'slicer extrusion paths', 'physical print', 'filament transmission calibration']
    }, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
