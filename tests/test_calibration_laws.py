"""Mapping laws settled by rendering both plugins (see docs/FINDINGS_AND_PLAN.md §11)."""

import math

import pytest

from serum2vital import mapping, serum1
from serum2vital.wavetables import lfo_to_vital


def _shape(xs, ys, curves=None):
    return serum1.LfoShape(xs=list(xs), ys=list(ys), curves=list(curves or [0.5] * (len(xs) - 1)))


def test_serum1_lfo_default_shape_is_a_triangle():
    # Stored (0,0)-(0.5,1)-(1,1): y is the LFO value as is and the loop closes.
    lfo = lfo_to_vital(_shape([0.0, 0.5, 1.0], [0.0, 1.0, 1.0]), invert_y=False, close_loop=True)
    assert lfo["points"] == [0.0, 0.0, 0.5, 1.0, 1.0, 0.0]


def test_lfo_close_loop_never_flattens_the_curve():
    lfo = lfo_to_vital(_shape([0.0, 0.5, 1.0], [1.0, 1.0, 0.0]), invert_y=False, close_loop=True)
    assert lfo["points"][1::2] == [1.0, 1.0, 0.0]          # left as drawn rather than flat
    lfo = lfo_to_vital(_shape([0.0, 1.0], [1.0, 0.0]), invert_y=False, close_loop=True)
    assert lfo["points"][1::2] == [1.0, 0.0]               # two-point ramps are not closed


def test_lfo_invert_still_available_for_other_formats():
    lfo = lfo_to_vital(_shape([0.0, 1.0], [0.0, 1.0]), invert_y=True)
    assert lfo["points"][1::2] == [1.0, 0.0]


def test_noise_pitch_law():
    def semis(pitch):
        return (pitch - 0.5) * 96.0 if pitch >= 0.5 else max(-48.0, 100.0 * math.log2(max(2.0 * pitch, 1e-3)))
    assert semis(0.75) == pytest.approx(24.0) and semis(1.0) == pytest.approx(48.0)
    assert semis(0.4) == pytest.approx(-32.19, abs=0.1)
    assert semis(0.25) == -48.0


def test_fm_sub_and_interp_helpers():
    assert mapping.warp_amount("fm_sub", 0.4) == pytest.approx(0.6)
    assert mapping.warp_amount("fm_sub", 0.9) == 1.0
    assert mapping._interp(-18.1, [(-36.2, 0.2), (-18.1, 1.5), (-7.5, 7.3)]) == pytest.approx(1.5)
    assert mapping._interp(-50.0, [(-36.2, 0.2), (-18.1, 1.5), (-7.5, 7.3)]) == pytest.approx(0.2)
    assert mapping._interp(-12.8, [(-36.2, 0.2), (-18.1, 1.5), (-7.5, 7.3)]) == pytest.approx(4.4, abs=0.01)
