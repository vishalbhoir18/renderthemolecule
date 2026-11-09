"""Chain colours: Blender gets the shared palette in linear light (no Blender needed)."""

import pytest

np = pytest.importorskip("numpy")

from app.blender_render import chain_colors, srgb_to_linear  # noqa: E402
from app.options import CHAIN_COLORS  # noqa: E402


def test_srgb_to_linear():
    assert srgb_to_linear("#FFFFFF") == pytest.approx((1, 1, 1))
    assert srgb_to_linear("#000000") == (0, 0, 0)
    # Mid grey in sRGB is about 21 % light: Blender would show "#808080" as given.
    assert srgb_to_linear("#808080") == pytest.approx((0.2158605,) * 3)


def test_chains_take_the_palette_in_order_of_their_ids():
    colors = chain_colors(["B", "A", "B", "C", "A"])
    first, second, third = (srgb_to_linear(c) + (1.0,) for c in CHAIN_COLORS[:3])
    assert colors.shape == (5, 4)
    assert colors[1] == pytest.approx(first) and colors[4] == pytest.approx(first)  # chain A
    assert colors[0] == pytest.approx(second) and colors[2] == pytest.approx(second)  # chain B
    assert colors[3] == pytest.approx(third)  # chain C


def test_the_palette_repeats_after_its_last_colour():
    ids = [f"{chr(65 + i)}" for i in range(len(CHAIN_COLORS) + 1)]
    colors = chain_colors(ids)
    assert colors[-1] == pytest.approx(colors[0])
    assert len({tuple(c) for c in colors[:-1]}) == len(CHAIN_COLORS)


def test_rainbow_runs_along_each_chain_and_greys_other_atoms():
    from app.blender_render import rainbow_colors
    from app.options import NON_POLYMER_RAINBOW_COLOR, RAINBOW_COLORS

    chains = ["A", "A", "A", "B", "B", "A"]
    residues = [10, 15, 20, 1, 3, 301]
    polymer = [True, True, True, True, True, False]  # the last atom is a water
    colors = rainbow_colors(chains, residues, polymer)
    first, last = (srgb_to_linear(c) + (1.0,) for c in (RAINBOW_COLORS[0], RAINBOW_COLORS[-1]))
    assert colors[0] == pytest.approx(first) and colors[2] == pytest.approx(last)  # chain A: 10 -> 20
    assert colors[3] == pytest.approx(first) and colors[4] == pytest.approx(last)  # chain B on its own
    assert colors[5] == pytest.approx(srgb_to_linear(NON_POLYMER_RAINBOW_COLOR) + (1.0,))
    # Halfway along chain A: the middle colour, blended in sRGB as the preview does.
    middle = RAINBOW_COLORS[len(RAINBOW_COLORS) // 2]
    assert colors[1] == pytest.approx(srgb_to_linear(middle) + (1.0,))


def test_a_one_residue_chain_takes_the_first_colour():
    from app.blender_render import rainbow_colors
    from app.options import RAINBOW_COLORS

    colors = rainbow_colors(["A", "A"], [5, 5], [True, True])
    assert colors[0] == pytest.approx(srgb_to_linear(RAINBOW_COLORS[0]) + (1.0,))
