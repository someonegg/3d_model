"""Render public previews from the delivered STL."""
import numpy as np
import trimesh
from PIL import Image, ImageDraw

def mesh_previews(OUT):
    mesh = trimesh.load(OUT / "bookmark-lovebird-fdm.stl", process=True)
    top = mesh.vertices[mesh.vertices[:, 2] > 0]
    steps = (top[:, 2]-.52)/.08
    np.testing.assert_allclose(steps, np.rint(steps), atol=1e-5)
    assert steps.min() >= -1e-5 and steps.max() <= 10.00001
    assert not np.any(np.all(np.isclose(mesh.vertices[:, :2], [0, 0]), axis=1))
    rows = np.rint((150-top[:, 1])/.15).astype(int).clip(0, 1000)
    cols = np.rint(top[:, 0]/.15).astype(int).clip(0, 300)
    height = np.full((1001, 301), np.nan)
    height[rows, cols] = top[:, 2]
    # Missing pixels are outside the rounded bookmark, not measured surface.
    valid = np.isfinite(height)
    height[~valid] = .52
    levels = np.rint((height-.52)/.08).astype(int)

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
