"""Hand-authored facial relief and noise suppression at the target diameter.

Landmarks use the reference photograph's pixel coordinates.
Heights and feature widths are in mm. This is an artistic reconstruction,
not an estimate of depth from photographic illumination.
"""
import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt, gaussian_filter, median_filter

def printable_obverse(photo_heights, diameter_mm):
    pixels_per_mm = 460 / diameter_mm
    # Remove isolated photographic grains before joining neighbouring reliefs.
    clean = gaussian_filter(median_filter(photo_heights, size=3), sigma=1.6)
    y, x = np.indices(clean.shape, dtype=float)

    def mound(cx, cy, rx, ry):
        return np.exp(-0.5 * (((x-cx)/rx)**2 + ((y-cy)/ry)**2))

    def stroke(points, width_mm):
        distance = np.full(clean.shape, np.inf)
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            dx, dy = bx-ax, by-ay
            t = np.clip(((x-ax)*dx + (y-ay)*dy)/(dx*dx+dy*dy), 0, 1)
            distance = np.minimum(distance, np.hypot(x-ax-t*dx, y-ay-t*dy))
        # Width is full width at half maximum, independent of photo brightness.
        sigma = width_mm * pixels_per_mm / 2.355
        return np.exp(-0.5*(distance/sigma)**2)

    # Continuous forehead, cheeks, muzzle and chin replace the photo texture.
    face = (0.36 + 0.27*mound(294, 161, 35, 27)
            + 0.30*mound(271, 228, 30, 32)
            + 0.22*mound(341, 222, 14, 25)
            + 0.16*mound(318, 256, 26, 17)
            + 0.25*mound(307, 281, 27, 13))

    # Recessed eye sockets, broad upper/lower lids, and simple raised eyeballs.
    # Fine pupils and skin texture are intentionally omitted at this size.
    eyelid_mask = np.zeros_like(face)
    for cx, cy, rx, ry in [(282, 191, 14, 6), (336, 182, 8, 7)]:
        face -= 0.30*mound(cx, cy, rx*1.2, ry*1.5)
        face += 0.18*mound(cx, cy, rx*0.60, ry*0.65)
        upper = [(cx-rx, cy+1), (cx-rx*.5, cy-ry*.8),
                 (cx, cy-ry), (cx+rx*.65, cy-ry*.5), (cx+rx, cy+1)]
        lower = [(cx-rx, cy+1), (cx-rx*.5, cy+ry*.55),
                 (cx+rx*.3, cy+ry*.7), (cx+rx, cy+1)]
        lids = np.maximum(stroke(upper, 0.95), stroke(lower, 0.85))
        eyelid_mask = np.maximum(eyelid_mask, lids)
        # A common crest above 0.8 mm keeps both lids on the same 0.2 mm
        # layer even where the underlying face slopes toward the far eye.
        face = face*(1-lids) + 0.88*lids
    face += 0.18*stroke([(265, 181), (274, 174), (287, 173), (297, 177)], 1.1)
    face += 0.16*stroke([(327, 169), (335, 165), (342, 169)], 0.9)

    # Nose bridge and tip project from the face; nostrils are shallow grooves.
    face += 0.35*stroke([(319, 180), (318, 194), (324, 210), (333, 221)], 1.55)
    face += 0.25*mound(333, 220, 6, 5)
    face += 0.14*mound(317, 225, 5, 4)
    face -= 0.20*stroke([(316, 229), (320, 226), (325, 228)], 0.8)
    face -= 0.18*stroke([(332, 230), (337, 227), (340, 223)], 0.8)

    # Broad lips separated by one continuous mouth line.
    upper_lip = stroke([(300, 250), (312, 245), (320, 246),
                        (328, 242), (336, 245), (347, 248)], 1.25)
    face = face*(1-upper_lip) + 0.94*upper_lip
    face += 0.21*mound(325, 259, 13, 4)
    face -= 0.28*stroke([(299, 252), (311, 252), (321, 251),
                         (330, 249), (339, 250), (347, 248)], 0.85)
    face = np.clip(face, 0, 1.1)

    # Blend inside the face boundary, preserving the hair, ear and silhouette.
    mask_image = Image.new('L', (clean.shape[1], clean.shape[0]))
    ImageDraw.Draw(mask_image).polygon([
        (237, 208), (253, 181), (275, 153), (301, 133), (319, 134),
        (335, 145), (342, 168), (344, 190), (352, 206), (354, 219),
        (349, 241), (344, 256), (339, 276), (330, 290), (312, 295),
        (287, 290), (264, 282), (245, 269), (234, 251), (228, 231),
    ], fill=255)
    alpha = np.clip(distance_transform_edt(np.asarray(mask_image)>0)/7, 0, 1)
    alpha = alpha*alpha*(3-2*alpha)
    alpha = gaussian_filter(alpha, sigma=1)
    # Preserve the far eyelid where it approaches the feathered face boundary.
    alpha = np.maximum(alpha, eyelid_mask)
    return clean*(1-alpha) + face*alpha
