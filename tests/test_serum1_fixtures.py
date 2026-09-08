"""Fixture presets saved from Serum 1 with one change each (DebugPresets/serum1)."""

from pathlib import Path

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
