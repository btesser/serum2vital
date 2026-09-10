"""Effect laws measured with tools/fx_fixtures.py (see docs/FINDINGS_AND_PLAN.md, third pass)."""

import math

import pytest

from serum2vital import fx_common as fx
from serum2vital import serum_tables as st


def test_delay_time_and_offset_laws():
    # plugin read-out: 1.00 ms at 0, 32.25 at 0.5, 159.20 at 0.75, 501 at 1
    assert st.delay_seconds(0.0) == pytest.approx(0.001)
    assert st.delay_seconds(0.5) == pytest.approx(0.03225, abs=1e-5)
    assert st.delay_seconds(0.75) == pytest.approx(0.1592, abs=1e-5)
    assert st.delay_seconds(1.0) == pytest.approx(0.501)
    assert st.delay_offset(0.0) == 0.5 and st.delay_offset(1.0) == 1.5   # "Dot"


def test_synced_delay_offsets_pick_dotted_and_triplet():
    quarter = fx.VITAL_TEMPO_INDEX["1/4"]
    assert fx.synced_delay(quarter, 1.0) == (fx.SYNC_TEMPO, quarter)
    assert fx.synced_delay(quarter, 1.5) == (fx.SYNC_DOTTED, quarter)
    # Serum 2 stores 4/3 for "triplet": the triplet of the next longer division
    assert fx.synced_delay(quarter, 4.0 / 3.0) == (fx.SYNC_TRIPLET, quarter - 1)
    # Serum 1's "Dot 1/2" (0.75x) is the dotted next shorter division
    assert fx.synced_delay(quarter, 0.75) == (fx.SYNC_DOTTED, quarter + 1)


def test_serum2_delay_ladder_anchors():
    assert fx.delay_seconds_to_tempo_index(0.0387) == fx.VITAL_TEMPO_INDEX["1/8"]
    assert fx.delay_seconds_to_tempo_index(0.0832) == fx.VITAL_TEMPO_INDEX["1/4"]
    assert fx.delay_seconds_to_tempo_index(0.1787) == fx.VITAL_TEMPO_INDEX["1/2"]
    assert fx.delay_seconds_to_tempo_index(0.18) == fx.VITAL_TEMPO_INDEX["1/1"]
    assert fx.delay_seconds_to_tempo_index(0.826) == fx.VITAL_TEMPO_INDEX["4/1"]


def test_fx_rate_ladder():
    assert fx.fx_rate_sync(0) == (fx.SYNC_TEMPO, 0)                                   # Off -> Freeze
    assert fx.fx_rate_sync(142) == (fx.SYNC_DOTTED, fx.VITAL_TEMPO_INDEX["1/4"])       # "1/4."
    assert fx.fx_rate_sync(171) == (fx.SYNC_TRIPLET, fx.VITAL_TEMPO_INDEX["1/4"])      # "1/4 t"
    assert fx.fx_rate_sync(228) == (fx.SYNC_TEMPO, fx.VITAL_TEMPO_INDEX["1/32"])
    # Serum 2: 1.333 Hz stored at knob 5/8 rendered as a dotted quarter at 120 BPM
    assert fx.fx_rate_sync(fx.fx_rate_step_from_hz(20.0 * (5 / 8) ** 4)) == (fx.SYNC_DOTTED, fx.VITAL_TEMPO_INDEX["1/4"])


def test_wet_mix_law():
    assert fx.serum_wet_gain(0.5) == pytest.approx(0.5)
    assert fx.serum_wet_to_vital(1.0) == pytest.approx(1.0)
    assert fx.serum_wet_to_vital(0.5) == pytest.approx(1.0 / 3.0)
    assert fx.serum_wet_to_vital(0.0) == 0.0


def test_compressor_laws():
    # Vital's follower time is base_ms * exp(8x - 4): 28 ms release base
    assert fx.comp_time_to_vital(28.0, "release") == pytest.approx(0.5)
    assert fx.comp_time_to_vital(90.0, "release") == pytest.approx((math.log(90 / 28) + 4) / 8)
    assert fx.comp_time_to_vital(1000.0, "attack") == 1.0
    assert fx.comp_makeup_db(0.5) == pytest.approx(18.8, abs=0.1)
    assert fx.comp_makeup_db(0.0) == 0.0
    assert fx.mb_threshold_gain_db(-17.6) == 0.0
    assert fx.mb_threshold_gain_db(-7.5) == 0.0
    assert fx.mb_threshold_gain_db(-25.8) == pytest.approx(-0.85 * 8.2)


def test_distortion_tables():
    for mode in ("Tube", "HardClip", "Diode 1", "Stomp Box", "kTube", "kDiode2"):
        vital_type, drive, _ = fx.dist_settings(mode, 0.0)
        assert -30.0 <= drive <= 30.0
    assert fx.dist_settings("Tube", 0.0)[1] == pytest.approx(-6.0, abs=0.6)      # -6 dB pad, clean
    assert fx.dist_settings("HardClip", 0.0) == (fx.DIST_HARD_CLIP, -6.0, True)
    assert fx.dist_settings("Tube", 1.0)[1] > 10.0
    assert fx.dist_settings("Lin.Fold", 0.5) == (fx.DIST_LINEAR_FOLD, 27.0, True)
    assert fx.dist_settings("X-Shaper", 0.0)[1] == pytest.approx(-6.0, abs=0.6)
    assert fx.mb_threshold_gain_db(-25.8, 0.0) == 0.0


def test_reverb_laws():
    assert fx.serum1_reverb_rt60(0.35, 0.8) == pytest.approx(2000.0 / 11.7 ** 3)   # just above the 1.14 s size floor
    assert fx.serum1_reverb_rt60(0.65, 0.8) == pytest.approx(3.2)                  # size floor
    assert fx.serum1_reverb_rt60(0.35, 6.4) == pytest.approx(8.8, abs=0.5)
    assert fx.serum1_reverb_rt60(0.35, 12.0) == fx.REVERB_MAX_RT60
    # Vital's RT60 = 1.45 * decay_time * f(size): 2 s at size 0.35 -> log2(2/1.45)
    assert fx.vital_decay_for_rt60(2.0, 0.35) == pytest.approx(math.log2(2.0 / 1.45))
    assert fx.serum2_reverb_rt60("kPlate", 50.0, 0.0) == pytest.approx(7.9)
    assert fx.serum2_reverb_rt60("kHall", 50.0, 30.0) == pytest.approx(3.2)
    assert fx.serum2_reverb_rt60("kHall", 50.0, 60.0) == pytest.approx(3.0 * math.exp(30 / 35))
    assert fx.serum2_reverb_rt60("kVintage", 45.0, 200.0) == pytest.approx(1.8)


def test_eq_and_chorus_helpers():
    assert fx.eq_resonance(0.6, "peak") == pytest.approx(0.8)
    assert fx.eq_resonance(0.2, "pass") == 0.0
    assert fx.eq_resonance(0.6, "shelf") == 0.0
    cutoff, spread = fx.chorus_lowpass(1000.0)
    # low-pass at cutoff + spread * 96 semitones = 1 kHz, high-pass near 20 Hz
    assert cutoff + spread * 96.0 == pytest.approx(fx.hz_to_note(1000.0))
    assert cutoff - spread * 96.0 == pytest.approx(fx.hz_to_note(20.0))
