"""Measure delivered geometry and render its sampled top surface."""
from pathlib import Path
import os
import json
import numpy as np
import trimesh
from PIL import Image, ImageDraw
from build import artwork

def main():
    OUT = Path(os.environ.get('MODEL_OUTPUT_DIR', Path(__file__).resolve().parents[1]))
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

    # Eye center is locked to the new source anatomy after the full-height crop.
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

    # Two lighting directions from exported mesh height samples.
    dy, dx = np.gradient(height, .15)
    normal = np.stack([-dx, dy, np.ones_like(dx)], axis=-1)
    normal /= np.linalg.norm(normal, axis=-1)[..., None]
    canvas = Image.new('RGB', (650, 1050), '#e9e7e2')
    draw = ImageDraw.Draw(canvas)
    for index, light in enumerate(([-.6, -.7, 1], [.6, .7, 1])):
        light = np.asarray(light)/np.linalg.norm(light)
        shade = np.uint8(np.clip(.35+.65*np.sum(normal*light, axis=-1), 0, 1)*255)
        rgb = np.stack([shade, shade, shade], axis=-1)
        rgb[~valid] = [233, 231, 226]
        canvas.paste(Image.fromarray(rgb), (15+index*320, 35))
        draw.text((15+index*320, 12), f'MESH LIGHT {index+1}', fill='black')
    canvas.save(OUT / 'surface-preview.png')
    canvas = Image.new('RGB', (970, 1050), '#e9e7e2')
    draw = ImageDraw.Draw(canvas)
    for index, layer in enumerate((8, 9, 10)):
        z = .2+(layer-1)*.08
        occupied = ((height >= z-1e-6) & valid)
        pixels = np.where(occupied, 245, 35).astype('uint8')
        canvas.paste(Image.fromarray(pixels).convert('RGB'), (15+index*320, 35))
        draw.text((15+index*320, 12), f'LAYER {layer} / Z {z:.2f} mm', fill='black')
    canvas.save(OUT / 'layers-preview.png')
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
