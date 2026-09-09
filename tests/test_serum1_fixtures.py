"""Fixture presets saved from Serum 1 with one change each (DebugPresets/serum1)."""

from pathlib import Path
from dataclasses import replace

import pytest

from serum2vital import serum1, mapping

FIX = Path(__file__).resolve().parent.parent / "DebugPresets" / "serum1"
pytestmark = pytest.mark.skipif(not FIX.is_dir(), reason="fixture presets not present")


def lfo1(name):
    return serum1.read(str(FIX / name)).lfo_shapes[0].settings


def test_init_is_off_mode_synced():
    s = lfo1("00 init.fxp")
    assert (s.hz_mode, s.dotted, s.triplet, s.anchor, s.mode, s.known) == (False, False, False, True, "off", True)


@pytest.mark.parametrize("name,field,value", [
    ("01 lfo1 bpm off.fxp", "hz_mode", True),
    ("02 lfo1 env.fxp", "mode", "env"),
    ("03b lfo1 trig.fxp", "mode", "trig"),
    ("04 lfo1 trip.fxp", "triplet", True),
    ("05 lfo1 dot.fxp", "dotted", True),
    ("06b lfo1 anch off.fxp", "anchor", False),
])
def test_single_flag(name, field, value):
    assert getattr(lfo1(name), field) == value


def test_rate_fixture_reads_as_sixteenth():
    p = serum1.read(str(FIX / "07 lfo1 rate 1-16.fxp"))
    from serum2vital import serum_tables as st
    from serum2vital.serum_params import NAME_TO_INDEX
    step = round(p.params[NAME_TO_INDEX["LFO1Rate"]] * 228)
    assert st.lfo_division(step) == "1/16"
    conv = mapping.convert_serum1(p)
    assert conv.settings["lfo_1_tempo"] == 10.0 and conv.settings["lfo_1_sync"] == 1.0


def test_shape_fixture_has_extra_points():
    p = serum1.read(str(FIX / "08 lfo1 shape.fxp"))
    assert p.layout == "new" and len(p.lfo_shapes[0].xs) >= 5


def test_sources_fixture_ids():
    p = serum1.read(str(FIX / "11 sources.fxp"))
    names = [s.source_name for s in p.mod_slots if s.active]
    assert names == ["velocity", "note", "poly_aftertouch", "chaos_1", "chaos_2", "note_random_1",
                     "note_random_2", "note_alt_1", "note_alt_2", "mpe_x", "mpe_y", "mpe_z",
                     "release_velocity", "fixed", "mod_wheel", "pitch_bend"]
    conv = mapping.convert_serum1(p)
    sources = [m["source"] for m in conv.modulations]
    assert "velocity" in sources and "mod_wheel" in sources and "pitch_wheel" in sources
    assert all(not s.startswith("macro_") or s.startswith("macro_control_") for s in sources)


def test_hz_mode_maps_to_seconds_sync():
    conv = mapping.convert_serum1(serum1.read(str(FIX / "01 lfo1 bpm off.fxp")))
    assert conv.settings["lfo_1_sync"] == 0.0
    # 6.2 Hz at the default knob position
    assert abs(2 ** conv.settings["lfo_1_frequency"] - 6.25) < 0.05


def test_default_rack_order_is_encoded():
    p = serum1.read(str(FIX / "00 init.fxp"))
    assert p.fx_rack[0] == "hyper" and p.fx_rack[-1] == "filter"


def test_extra_sources_and_aux():
    p = serum1.read(str(FIX / "11b sources extra.fxp"))
    assert [(s.source, s.dest, s.amount) for s in p.mod_slots if s.active] == [(15, 1, 0.5), (19, 1, 0.5)]
    p = serum1.read(str(FIX / "12 aux.fxp"))
    s = p.mod_slots[0]
    assert (s.source, s.aux_source, s.dest, s.amount) == (5, 1, 5, 0.5)


def test_reordered_reverb_rack():
    p = serum1.read(str(FIX / "13 fx order.fxp"))
    assert p.fx_rack == ["reverb", "hyper", "distortion", "flanger", "phaser", "chorus", "delay", "compressor", "eq", "filter"]


@pytest.mark.parametrize("name,expected", [
    ("14 reverb hall.fxp", {"Rev Enable": 1}),
    ("15 delay pingpong.fxp", {"Dly Enable": 1, "Dly_Mode": 0.5}),
    ("16 hyper.fxp", {"Hyp Enable": 1, "Hyp_Unison": 1, "Hyp_Retrig": 1, "HypDim_Mix": 0.5}),
    ("17 filter keytrack.fxp", {"Filter On": 1}),
    ("19 chaos sh mono.fxp", {"Chaos1 BPM": 1}),
    ("20 unison range super.fxp", {"A Uni Stack": 0.5}),
    ("21 noise.fxp", {"Osc N On": 1}),
    ("22 dist mode.fxp", {"Dist Enable": 1, "Dist_Mode": 1}),
    ("23 filter type.fxp", {"Filter On": 1, "Fil Type": 1}),
])
def test_new_fixture_parameters(name, expected):
    from serum2vital.serum_params import NAME_TO_INDEX
    p = serum1.read(str(FIX / name))
    for key, value in expected.items():
        assert p.params[NAME_TO_INDEX[key]] == pytest.approx(value)


def settings(name):
    return serum1.read(str(FIX / name)).settings


def test_init_switch_block_defaults():
    s = settings("00 init.fxp")
    assert s.known and not s.mono and not s.legato and s.polyphony == 8
    assert not s.filter_keytrack and not s.noise_one_shot and not s.noise_pitch_track
    assert s.unison_range == pytest.approx((2.0, 2.0)) and s.unison_tuning == ("Linear", "Linear")
    assert s.chaos_mono == (False, False) and s.chaos_sh == (False, False)
    assert s.reverb_hall and not s.porta_always and not s.porta_scaled


def test_filter_keytrack_switch():
    assert settings("17 filter keytrack.fxp").filter_keytrack is True
    conv = mapping.convert_serum1(serum1.read(str(FIX / "17 filter keytrack.fxp")))
    assert conv.settings["filter_1_keytrack"] == 1.0


def test_mono_legato_polyphony():
    s = settings("18 mono legato.fxp")
    assert (s.mono, s.legato, s.polyphony) == (True, True, 4)
    conv = mapping.convert_serum1(serum1.read(str(FIX / "18 mono legato.fxp")))
    assert conv.settings["polyphony"] == 1.0 and conv.settings["legato"] == 1.0


def test_chaos_mono_and_sample_hold():
    # +0x40 leaves a single voice unchanged (Mono), +0x50 steps the output (S&H):
    # established by rendering crafted single-flag variants through the plugin.
    s = settings("19 chaos sh mono.fxp")
    assert s.chaos_mono == (True, False) and s.chaos_sh == (True, False)
    conv = mapping.convert_serum1(serum1.read(str(FIX / "19 chaos sh mono.fxp")))
    assert conv.settings["random_1_style"] == 1.0 and conv.settings["random_1_sync_type"] == 1.0
    assert conv.settings["random_2_style"] == 3.0


def test_unison_range_and_tuning():
    s = settings("20 unison range super.fxp")
    assert s.unison_range == pytest.approx((12.0, 2.0)) and s.unison_tuning == ("Super", "Linear")
    conv = mapping.convert_serum1(serum1.read(str(FIX / "20 unison range super.fxp")))
    assert conv.settings["osc_1_detune_range"] == pytest.approx(12.0)
    assert conv.settings["osc_1_detune_power"] == 0.0


def test_noise_one_shot_and_pitch_track():
    # +0x24 stops the sample at its end (one-shot); +0x28 makes the Pitch knob
    # read in semitones and the spectrum follow the note (keytrack).
    s = settings("21 noise.fxp")
    assert s.noise_one_shot and s.noise_pitch_track
    conv = mapping.convert_serum1(serum1.read(str(FIX / "21 noise.fxp")))
    assert conv.settings["sample_loop"] == 0.0 and conv.settings["sample_keytrack"] == 1.0


def test_reverb_hall_byte():
    assert settings("14 reverb hall.fxp").reverb_hall is True


@pytest.mark.parametrize("name,changes", [
    ("14b reverb plate.fxp", {"reverb_hall": False}),
    ("19b chaos2 mono.fxp", {"chaos_mono": (False, True)}),
    ("19c chaos2 sh.fxp", {"chaos_sh": (False, True)}),
    ("24 porta always.fxp", {"porta_always": True}),
    ("25 porta scaled.fxp", {"porta_scaled": True}),
])
def test_isolated_gui_switch_fixtures(name, changes):
    from serum2vital.serum_params import NAME_TO_INDEX

    baseline = serum1.read(str(FIX / "00 init.fxp"))
    patch = serum1.read(str(FIX / name))
    assert patch.settings == replace(baseline.settings, **changes)
    expected_params = list(baseline.params)
    if "reverb_hall" in changes:
        expected_params[NAME_TO_INDEX["Rev Enable"]] = 1.0
    assert list(patch.params) == expected_params
    assert patch.fx_rack == baseline.fx_rack
