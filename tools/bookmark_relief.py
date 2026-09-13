"""Shared grayscale-to-height generator for filament-painting bookmarks."""
from pathlib import Path
import json
import numpy as np
from PIL import Image, ImageOps, ImageDraw
from scipy.ndimage import gaussian_filter, median_filter, map_coordinates
import trimesh

PITCH = .15
BASE = .52
LAYER = .08
LEVELS = 10


def gray_to_layers(gray, tones):
    tones = np.asarray(tones, dtype=float)
    if (tones.shape != (LEVELS + 1,) or not np.isfinite(tones).all()
            or np.any(np.diff(tones) <= 0) or tones[0] < 0 or tones[-1] > 255):
        raise ValueError('tone_values 必须为 11 个严格递增的 0～255 灰度值')
    return np.argmin(abs(np.asarray(gray)[..., None] - tones), axis=-1)


def artwork(source, tones):
    source = Path(source)
    image = ImageOps.fit(Image.open(source / 'source.png').convert('L'),
                         (301, 1001), method=Image.Resampling.LANCZOS)
    gray = np.asarray(image, dtype=float)
    gray = median_filter(gray, size=3)
    gray = gaussian_filter(gray, sigma=.16 / PITCH)
    low, high = np.percentile(gray, [1, 99])
    gray = np.clip((gray - low) * 255 / (high - low), 0, 255)
    return gray_to_layers(gray, tones)


def bookmark_mesh(levels):
    ny, nx = levels.shape
    y = np.linspace(0, 150, ny)
    dy = np.maximum(3 - np.minimum(y, 150-y), 0)
    inset = np.where(dy > 0, 3 - np.sqrt(np.maximum(9-dy*dy, 0)), 0)
    x = inset[:, None] + np.linspace(0, 1, nx)[None, :] * (45-2*inset[:, None])
    yy = np.broadcast_to(y[:, None], x.shape)
    sampled = map_coordinates(levels.astype(float), [(150-yy)/PITCH, x/PITCH],
                              order=0, mode='nearest')
    z = BASE + LAYER * sampled
    vertices = np.column_stack((x.ravel(), yy.ravel(), z.ravel()))
    ids = np.arange(nx*ny).reshape(ny, nx)
    a, b, c, d = (value.ravel() for value in
                  (ids[:-1, :-1], ids[:-1, 1:], ids[1:, 1:], ids[1:, :-1]))
    faces = np.vstack((np.column_stack((a, b, c)), np.column_stack((a, c, d))))
    boundary = np.concatenate((ids[0, :], ids[1:, -1], ids[-1, -2::-1],
                               ids[-2:0:-1, 0]))
    bottom = np.arange(len(vertices), len(vertices)+len(boundary))
    vertices = np.vstack((vertices,
                          np.column_stack((vertices[boundary, :2], np.zeros(len(boundary)))),
                          [22.5, 75, 0]))
    following = np.roll(boundary, -1)
    next_bottom = np.roll(bottom, -1)
    faces = np.vstack((faces, np.column_stack((boundary, bottom, next_bottom)),
                       np.column_stack((boundary, next_bottom, following)),
                       np.column_stack((np.full(len(bottom), len(vertices)-1),
                                        next_bottom, bottom))))
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def preview(out, levels, tones, title):
    rgb = np.repeat(np.asarray(tones, dtype=np.uint8)[levels][..., None], 3, axis=2)
    art = Image.fromarray(rgb).resize((450, 1500), Image.Resampling.NEAREST)
    mask = Image.new('L', art.size)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 449, 1499), radius=30, fill=255)
    canvas = Image.new('RGB', (750, 1650), '#e9e7e2')
    canvas.paste(art, (150, 65), mask)
    draw = ImageDraw.Draw(canvas)
    draw.text((24, 20), title, fill='#333333')
    draw.text((24, 1590), 'UNCALIBRATED GRAYSCALE / NOT A PRINT PHOTO', fill='#333333')
    canvas.save(Path(out) / 'preview.png')


def build(source, out, title, filename):
    source, out = Path(source), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    config = json.loads((source / 'parameters.json').read_text(encoding='utf-8'))
    tones = config['tone_values']
    levels = artwork(source, tones)
    mesh = bookmark_mesh(levels)
    assert mesh.is_watertight and mesh.is_winding_consistent and mesh.volume > 0
    assert np.all(mesh.area_faces > 1e-12)
    mesh.export(out / filename)
    preview(out, levels, tones, title)
