"""Simplify the eagle relief at the target coin diameter.

Photo landmarks are in pixels; relief heights and groove widths are in mm.
Long flight feathers retain their photographic outlines. Small covert-feather
texture is replaced with broader, continuous grooves, not scan-derived depth.
"""
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt, gaussian_filter, median_filter

def printable_reverse(photo_heights, diameter_mm):
    pixels_per_mm = 460 / diameter_mm
    clean = gaussian_filter(median_filter(photo_heights, size=3), sigma=1.6)
    y, x = np.indices(clean.shape, dtype=float)

    # The dense small feathers at the wing root and chest otherwise produce
    # many isolated islands on 0.2 mm layers. Keep the flight feathers outside.
    mask_image = Image.new('L', (clean.shape[1], clean.shape[0]))
    ImageDraw.Draw(mask_image).polygon([
        (766, 175), (781, 179), (795, 205), (802, 240), (807, 278),
        (817, 297), (832, 310), (826, 331), (803, 345), (779, 339),
        (760, 325), (749, 307), (758, 287), (763, 255),
    ], fill=255)
    alpha = np.clip(distance_transform_edt(np.asarray(mask_image)>0)/6, 0, 1)
    alpha = gaussian_filter(alpha*alpha*(3-2*alpha), sigma=1)
    body = gaussian_filter(clean, sigma=3.2)

    grooves = np.zeros_like(clean)
    paths = [
        [(770, 201), (778, 209), (790, 212)],
        [(770, 222), (781, 231), (797, 234)],
        [(770, 244), (783, 252), (801, 255)],
        [(769, 266), (783, 274), (804, 277)],
        [(763, 287), (777, 296), (791, 299), (809, 297)],
        [(759, 304), (772, 315), (790, 320), (817, 314)],
        [(771, 324), (786, 333), (803, 334), (818, 327)],
    ]
    # 0.85 mm full width at half maximum; 0.30 mm maximum groove depth.
    sigma = 0.85 * pixels_per_mm / 2.355
    for points in paths:
        distance = np.full(clean.shape, np.inf)
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            dx, dy = bx-ax, by-ay
            t = np.clip(((x-ax)*dx + (y-ay)*dy)/(dx*dx+dy*dy), 0, 1)
            distance = np.minimum(distance, np.hypot(x-ax-t*dx, y-ay-t*dy))
        grooves = np.maximum(grooves, np.exp(-0.5*(distance/sigma)**2))
    body = np.clip(body-0.30*grooves, 0, 1.1)
    return clean*(1-alpha) + body*alpha
