"""Unit curves and menu tables measured from the Serum plugin (serum_tables)."""

import math

from serum2vital import mapping, serum_tables as st, serum1


def test_envelope_curve_is_quintic():
    # Serum shows 1.00 s at the half-way knob and 7.59 s at three quarters.
    assert abs(st.env_seconds(0.5) - 1.0) < 1e-6
    assert abs(st.env_seconds(0.75) - 7.59) < 0.01
    assert abs(mapping.env_time(0.5) ** 4 - 1.0) < 1e-3
    assert abs(mapping.env_time(1.0) ** 4 - 32.0) < 1e-2


def test_lfo_rate_tables():
    assert st.lfo_division(114) == "1/4"           # Serum's default knob position
    assert st.lfo_division(0) == "32 bar" and st.lfo_division(160) == "1/16"
    assert abs(st.lfo_hz(0.5) - 6.25) < 1e-6 and abs(st.lfo_hz(1.0) - 100.0) < 1e-6
    assert mapping.VITAL_TEMPO["1/4"] == 8 and mapping.VITAL_TEMPO["bar"] == 6


def test_cutoff_curve_matches_readout():
    # Serum read-outs: 8 Hz, 425 Hz, 22050 Hz at knob 0, 0.5, 1.
    assert abs(st.cutoff_hz(0.0) - 8.0) < 1e-6
    assert abs(st.cutoff_hz(0.5) - 420.0) < 6.0
    assert abs(st.cutoff_hz(1.0) - 22050.0) < 1e-3
    # 8 Hz is MIDI note -0.4; Vital clamps its cutoff at note 8 when the value is set.
    assert -1 < mapping.serum_cutoff_to_note(0.0) < 0 and 136 < mapping.serum_cutoff_to_note(1.0) < 137


def test_menu_tables():
    assert st.FILTER_NAMES[0] == "MG Low 6" and st.FILTER_NAMES[1] == "MG Low 12" and len(st.FILTER_NAMES) == 96
    assert st.WARP_NAMES[18] == "FM (from B)" and len(st.WARP_NAMES) == 24
    assert st.DIST_MODE_NAMES[15] == "Tape Sat." and st.UNISON_STACK_NAMES[7] == "Center-12"
    assert st.indexed(1 / 95, (95, 89, 88)) == 1 and st.indexed(28 / 89, (95, 89, 88)) == 28
    assert st.indexed(18 / 23, (23,)) == 18


def test_master_volume_curve():
    assert abs(st.master_db(1.0)) < 1e-9
    assert abs(st.master_db(0.7) + 9.29) < 0.05
    assert abs(st.master_db(0.5) + 18.06) < 0.05


def test_vital_source_names():
    assert mapping.SOURCE_TO_VITAL["macro_1"] == "macro_control_1"
    assert mapping.SOURCE_TO_VITAL["chaos_1"] == "random_1"
    assert mapping.SOURCE_TO_VITAL["pitch_bend"] == "pitch_wheel"
    assert serum1.MOD_SOURCES[13] == "velocity" and serum1.MOD_SOURCES[1] == "mod_wheel"


def test_lfo_settings_flags_decode():
    assert serum1.LfoSettings.from_flags([1, 0, 0, 0, 0, 0]).mode == "off"
    assert serum1.LfoSettings.from_flags([1, 0, 0, 0, 1, 0]).mode == "trig"
    assert serum1.LfoSettings.from_flags([1, 1, 1, 0, 1, 1]) == serum1.LfoSettings(
        hz_mode=True, dotted=True, triplet=False, anchor=True, mode="env")


def test_aux_routing_uses_amount_modulation():
    conv = mapping.Conversion(name="t")
    mapping.route(conv, "lfo_1", "osc_1_tune", 0.4, aux="mod_wheel")
    assert conv.modulations == [
        {"source": "lfo_1", "destination": "osc_1_tune"},
        {"source": "mod_wheel", "destination": "modulation_1_amount"},
    ]
    # The aux link carries half the amount: Vital's amount parameter spans -1..1.
    assert conv.settings["modulation_1_amount"] == 0.0 and abs(conv.settings["modulation_2_amount"] - 0.2) < 1e-9
