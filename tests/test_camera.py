"""The Blender camera that reproduces a view from the 3D preview (no Blender needed)."""

import math

import pytest

from app.blender_render import WORLD_SCALE, camera_matrix

VIEW = {"position": [149.63, 50.82, 142.57], "target": [105.44, -18.82, 186.16], "up": [0.6422, 0.0703, 0.7633]}


def column(matrix, i):
    return [matrix[r][i] for r in range(3)]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def test_camera_sits_at_the_scaled_position_and_looks_at_the_target():
    m = camera_matrix(VIEW)
    assert column(m, 3) == pytest.approx([x * WORLD_SCALE for x in VIEW["position"]])
    assert m[3] == [0.0, 0.0, 0.0, 1.0]
    forward = [t - p for t, p in zip(VIEW["target"], VIEW["position"])]
    length = math.hypot(*forward)
    # A Blender camera looks down its local -Z axis.
    assert [-x for x in column(m, 2)] == pytest.approx([x / length for x in forward])


def test_camera_axes_are_orthonormal_and_keep_the_up_direction():
    m = camera_matrix(VIEW)
    right, up, back = column(m, 0), column(m, 1), column(m, 2)
    for axis in (right, up, back):
        assert math.hypot(*axis) == pytest.approx(1)
    for a, b in ((right, up), (up, back), (right, back)):
        assert dot(a, b) == pytest.approx(0, abs=1e-9)
    assert dot(up, VIEW["up"]) > 0.99  # Mol*'s up is already close to perpendicular
    # Right-handed, as Blender's object axes are.
    cross = [right[1] * up[2] - right[2] * up[1], right[2] * up[0] - right[0] * up[2], right[0] * up[1] - right[1] * up[0]]
    assert cross == pytest.approx(back)


def test_a_slanted_up_direction_is_straightened():
    view = {"position": [0, 0, 50], "target": [0, 0, 0], "up": [0, 1, 1]}  # not perpendicular to the view
    m = camera_matrix(view)
    assert column(m, 1) == pytest.approx([0, 1, 0])
    assert column(m, 0) == pytest.approx([1, 0, 0])
