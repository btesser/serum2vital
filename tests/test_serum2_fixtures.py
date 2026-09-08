"""Serum 2 fixture presets (DebugPresets/*.SerumPreset), one change each from Init."""

from pathlib import Path

import pytest

from serum2vital import serum2, mapping

FIX = Path(__file__).resolve().parent.parent / "DebugPresets"
pytestmark = pytest.mark.skipif(not (FIX / "1.SerumPreset").is_file(), reason="fixture presets not present")


def lfo1(name):
    p = serum2.read(str(FIX / name))
    return mapping.s2_lfo_settings(p.plain_params("LFO0"))


def test_init_is_trigger_synced():
    s = lfo1("1.SerumPreset")
    assert (s.hz_mode, s.dotted, s.triplet, s.anchor, s.mode) == (False, False, False, True, "trig")


@pytest.mark.parametrize("name,field,value", [
    ("2.SerumPreset", "hz_mode", True),
    ("3.SerumPreset", "mode", "env"),
    ("4 - lfo1 free.SerumPreset", "mode", "off"),
    ("5.SerumPreset", "triplet", True),
    ("6.SerumPreset", "dotted", True),
    ("7 - anchor off.SerumPreset", "anchor", False),
])
def test_single_flag(name, field, value):
    assert getattr(lfo1(name), field) == value


def test_synced_rate_one_sixteenth():
    conv = mapping.convert_serum2(serum2.read(str(FIX / "8.SerumPreset")))
    assert conv.settings["lfo_1_sync"] == 1.0 and conv.settings["lfo_1_tempo"] == 10.0


def test_custom_shape_is_flipped_to_vital_axis():
    conv = mapping.convert_serum2(serum2.read(str(FIX / "9.SerumPreset")))
    lfo = conv.lfos[0]
    assert lfo["num_points"] == 5
    ys = lfo["points"][1::2]
    assert ys[0] == 0.0 and abs(ys[1] - (1 - 0.0294)) < 1e-3   # Serum y 1.0 (bottom) -> Vital 0


def test_lfo5_fixtures():
    p = serum2.read(str(FIX / "10.SerumPreset"))
    assert mapping.s2_lfo_settings(p.plain_params("LFO4")).hz_mode is True
    p = serum2.read(str(FIX / "11.SerumPreset"))
    assert mapping.s2_lfo_settings(p.plain_params("LFO4")).mode == "env"
