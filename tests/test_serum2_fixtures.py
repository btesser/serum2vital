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


@pytest.mark.parametrize("name,source_ids", [
    ("12 sources.SerumPreset", [16, 17, 19, 14, 15, 21, 22, 23, 24, 34, 35, 36, 37, 38, 1, 33]),
    ("12b sources extra.SerumPreset", [18, 20, 49, 50, 51, 52, 55, 59, 58, 56, 57, 53, 54]),
])
def test_captured_source_rows(name, source_ids):
    # Main rows 4/5 use LFO 9/10: this build has no Chaos source entries.
    p = serum2.read(str(FIX / name))
    for i, source_id in enumerate(source_ids):
        slot = p.module(f"ModSlot{i}")
        assert slot["source"] == [source_id, 0]
        assert slot["destModuleTypeString"] == "Oscillator"
        assert slot["destModuleID"] == 0
        assert slot["destModuleParamName"] == "kParamVolume"
        assert slot["plainParams"]["kParamAmount"] == pytest.approx(50, abs=0.5)
    assert not p.module(f"ModSlot{len(source_ids)}").get("source")


def test_captured_sources_convert():
    conv = mapping.convert_serum2(serum2.read(str(FIX / "12 sources.SerumPreset")))
    # LFO 9/10, NoteOn Alt, MPE X and Fixed have no Vital counterpart and are dropped.
    assert [m["source"] for m in conv.modulations] == [
        "velocity", "note", "aftertouch", "random", "random", "slide", "aftertouch", "lift",
        "mod_wheel", "pitch_wheel",
    ]
    conv = mapping.convert_serum2(serum2.read(str(FIX / "12b sources extra.SerumPreset")))
    assert [m["source"] for m in conv.modulations] == ["aftertouch"]
    assert any("OSC A audio" in note for note in conv.notes)
    assert not any(note.startswith("unknown:") for note in conv.notes)


@pytest.mark.parametrize("name,rate", [
    ("13 rate 4bar.SerumPreset", 0.2108496543592536),
    ("13 rate 1bar.SerumPreset", 1.6269264358721542),
    ("13 rate 1-2.SerumPreset", 3.3735944697480575),
    ("13 rate 1-32.SerumPreset", 26.030822973954468),
])
def test_captured_synced_rates(name, rate):
    p = serum2.read(str(FIX / name))
    assert p.plain_params("LFO0")["kParamRate"] == pytest.approx(rate)
    assert lfo1(name).hz_mode is False
