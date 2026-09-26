"""Check delivered parts and the intended clearances of the assembled button."""
from pathlib import Path
import os
import numpy as np
import trimesh

def main():
    out = Path(os.environ.get('MODEL_OUTPUT_DIR', Path(__file__).resolve().parents[1]))
    mesh = trimesh.load(out / 'fidget-button-fdm.stl', process=True)
    replacement = trimesh.load(out / 'fidget-button-fdm-spring.stl', process=True)
    parts = mesh.split(only_watertight=True)
    assert len(parts) == 4, f'expected four separate printable parts, got {len(parts)}'
    assert all(part.is_watertight and part.is_winding_consistent and part.volume > 0 for part in parts)
    by_height = {round(float(part.extents[2]), 2): part for part in parts}
    assert set(by_height) == {17.0, 11.04, 8.7, 1.16}, by_height.keys()
    shell, plug, cap, flexure = (by_height[h] for h in (17.0, 11.04, 8.7, 1.16))
    assert replacement.is_watertight and replacement.is_winding_consistent
    assert len(replacement.split(only_watertight=True)) == 1
    np.testing.assert_allclose(replacement.extents, flexure.extents, atol=1e-5)
    np.testing.assert_allclose(replacement.volume, flexure.volume, atol=1e-3)
    for part in parts:
        assert abs(part.bounds[0, 2]) < 1e-6, 'each part must sit flat on the build plate'
    for index, first in enumerate(parts):
        for second in parts[index + 1:]:
            overlap = np.minimum(first.bounds[1, :2], second.bounds[1, :2]) - np.maximum(first.bounds[0, :2], second.bounds[0, :2])
            assert np.any(overlap < -4.0), 'print plate parts need at least 4 mm separation'
    np.testing.assert_allclose(shell.extents[:2], [42, 42], atol=1e-5)
    np.testing.assert_allclose(plug.extents[:2], [42, 42], atol=1e-5)
    np.testing.assert_allclose(cap.extents[:2], [27.6, 27.6], atol=1e-5)
    np.testing.assert_allclose(flexure.extents[:2], [34, 34], atol=0.21)

    def radii_at(part, height):
        points = part.vertices[np.isclose(part.vertices[:, 2], height, atol=1e-5)]
        center = (part.bounds[0, :2] + part.bounds[1, :2]) / 2
        return np.hypot(*(points[:, :2] - center).T)


    def has_radius(part, height, radius):
        assert np.any(np.isclose(radii_at(part, height), radius, atol=0.021)), (height, radius)


    # Measure exported cross sections, not just source constants.
    for part, height, radius in ((shell, 0, 13.0), (shell, 2.5, 17.5),
                                 (cap, 0, 12.6), (cap, 4.0, 13.8),
                                 (cap, 8.7, 6.0), (cap, 8.7, 2.6),
                                 (plug, 3.0, 17.25), (plug, 3.0, 17.55),
                                 (plug, 11.04, 14.0), (plug, 10.7, 3.0)):
        has_radius(part, height, radius)
    # The long upper wall must clear the bore; only 1.2 mm of ribs retain it.
    for height in (4.8, 10.24):
        np.testing.assert_allclose(radii_at(plug, height), 17.25, atol=1e-5)
    for height in (3.0, 4.2):
        radii = radii_at(plug, height)
        assert np.count_nonzero(radii > 17.5) == 6
        np.testing.assert_allclose(radii.max(), 17.55, atol=1e-5)
    # Recess lips leave a 1.2 mm floor and 2 mm tool access at both X ends.
    center = (plug.bounds[0, :2] + plug.bounds[1, :2]) / 2
    seam = plug.vertices[np.isclose(plug.vertices[:, 2], 2.4), :2] - center
    for sign in (-1, 1):
        assert np.any(np.linalg.norm(seam - [sign * 19.0, 0], axis=1) < 1e-5)
    has_radius(plug, 1.2, 21.0)
    assert 13.0 - 12.6 >= 0.35  # radial clearance around the cap face
    assert 17.5 - 17.25 >= 0.20  # main plug body clearance
    assert 0.04 < 17.55 - 17.5 < 0.06  # retaining ribs; physical fit still needs a test print
    assert 14.0 < 14.25 < 17.1 < 17.5  # spring frame supported inside the shell

    # Assembled Z: shell top 17, cap face 18.5, cap pusher lower face 9.8.
    spring_top_z = -2.4 + float(plug.bounds[1, 2]) + float(flexure.extents[2])
    cap_pusher_z = 18.5 - 8.7
    stop_z = -2.4 + 10.7
    assert abs(spring_top_z - cap_pusher_z) < 1e-5
    assert abs(cap_pusher_z - stop_z - 1.5) < 1e-6
    # The spring tips straddle the stop and meet the annular pusher.
    xy = flexure.vertices[:, :2] - (flexure.bounds[0, :2] + flexure.bounds[1, :2]) / 2
    near_center = xy[np.abs(xy[:, 0]) < 0.11]
    assert np.min(np.abs(near_center[:, 1])) >= 3.19
    assert np.any((near_center[:, 1] >= 3.2) & (near_center[:, 1] <= 5.4))
    assert np.any((near_center[:, 1] <= -3.2) & (near_center[:, 1] >= -5.4))
    print('4 closed parts; 42 mm diameter; 0.4 mm cap clearance; 1.5 mm mechanical travel; 1.16 mm flexure; short ribs and two pry recesses')


if __name__ == '__main__':
    main()
