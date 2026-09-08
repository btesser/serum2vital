"""Smoke tests for the Serum 2 effect-rack conversion.

Converts a slice of the Serum 2 factory corpus through `convert_serum2` and
`convert_fx_racks` and checks that every Vital parameter written exists and
sits inside its declared range.  The corpus lives outside the repo, so the
corpus-driven tests skip when it is absent.
"""

from __future__ import annotations

import glob
import math
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from serum2vital import fx_common, serum2, serum2_fx  # noqa: E402
from serum2vital.mapping import Conversion, convert_serum2  # noqa: E402
from serum2vital.vital_defaults import PARAMS  # noqa: E402

import os

CORPUS = os.environ.get("SERUM_ROOT", "D:/VSTData/serum") + "/Serum 2 Presets/**/*.SerumPreset"
SAMPLE_SIZE = 20


def _corpus_files() -> list[str]:
    files = sorted(glob.glob(CORPUS, recursive=True))
    if not files:
        return []
    # Spread the sample across the corpus so several banks are covered.
    step = max(1, len(files) // SAMPLE_SIZE)
    return files[::step][:SAMPLE_SIZE]


def _convert(path: str) -> Conversion:
    patch = serum2.read(path)
    conv = convert_serum2(patch)
    serum2_fx.convert_fx_racks(patch, conv)
    return conv


@pytest.mark.parametrize("path", _corpus_files() or [pytest.param(None, marks=pytest.mark.skip(reason="Serum 2 corpus not available"))])
def test_corpus_preset_converts_within_vital_ranges(path):
    conv = _convert(path)
    assert "effect_chain_order" in conv.settings
    for key, value in conv.settings.items():
        assert key in PARAMS, f"{os.path.basename(path)}: unknown Vital parameter {key}"
        lo, hi = PARAMS[key][0], PARAMS[key][1]
        assert isinstance(value, float) and math.isfinite(value), f"{key} = {value!r}"
        assert lo <= value <= hi, f"{os.path.basename(path)}: {key} = {value} outside [{lo}, {hi}]"
    for note in conv.notes:
        assert not note.startswith("unknown Vital parameter"), note


def test_effect_order_encoding():
    identity = list(fx_common.VITAL_EFFECTS)
    assert fx_common.encode_effect_order(identity) == 0.0
    reversed_order = identity[::-1]
    assert fx_common.encode_effect_order(reversed_order) == math.factorial(9) - 1
    lo, hi = PARAMS["effect_chain_order"][0], PARAMS["effect_chain_order"][1]
    assert lo <= fx_common.encode_effect_order(reversed_order) <= hi
    # Every code is unique across a handful of permutations.
    import itertools

    seen = set()
    for perm in itertools.islice(itertools.permutations(identity), 2000):
        code = fx_common.encode_effect_order(list(perm))
        assert code not in seen
        seen.add(code)


def test_vital_chain_from_rack_keeps_relative_order():
    chain = fx_common.vital_chain_from_rack(["hyper", "distortion", "reverb", "eq", "distortion"])
    assert chain[:4] == ["chorus", "distortion", "reverb", "eq"]
    assert sorted(chain) == sorted(fx_common.VITAL_EFFECTS)
    assert len(chain) == 9


def test_hyper_to_chorus_and_flanger_fallback():
    conv = Conversion(name="t")
    target = fx_common.hyper_to_chorus(
        conv, wet=0.5, rate_hz=0.5, detune=0.3, voices=5, retrig=True, dim_size=0.5, dim_mix=0.2, chorus_busy=False
    )
    assert target == "chorus"
    assert conv.settings["chorus_voices"] == 3.0
    assert conv.settings["chorus_on"] == 1.0
    assert abs(conv.settings["chorus_dry_wet"] - 0.7) < 1e-9
    assert any(n.startswith("unsupported: Hyper retrig") for n in conv.notes)
    assert any(n.startswith("approximation:") for n in conv.notes)

    conv = Conversion(name="t")
    target = fx_common.hyper_to_chorus(
        conv, wet=0.8, rate_hz=1.0, detune=0.5, voices=0, retrig=False, dim_size=0.0, dim_mix=0.4, chorus_busy=True
    )
    assert target == "flanger"
    assert conv.settings["flanger_on"] == 1.0
    assert abs(conv.settings["flanger_dry_wet"] - 0.4) < 1e-9
    assert any(n.startswith("resource-conflict") for n in conv.notes)


def test_dist_mode_index():
    assert fx_common.dist_mode_index("kHardClip") == (1, True)
    assert fx_common.dist_mode_index("Lin.Fold") == (2, True)
    assert fx_common.dist_mode_index("Sin Fold") == (3, True)
    assert fx_common.dist_mode_index("kDownsample") == (5, True)
    assert fx_common.dist_mode_index("Tape Sat.") == (0, False)
    assert fx_common.dist_mode_index("X-Shaper (Asym)")[1] is False
    assert fx_common.dist_mode_index("no such mode") == (0, False)


def test_synthetic_rack_maps_every_module_kind():
    """A hand-built rack exercising conflicts, buses and the chain order."""
    state = {
        "FXRack0": {
            "FX": [
                {"type": 9, "FXHyperD": {"plainParams": {"kParamUnison": 4.0, "kParamWet": 60.0, "kParamRate": 40.0}}},
                {"type": 0, "FXDistortion": {"plainParams": {"kParamMode": "kTapeSat", "kParamDrive": 50.0, "kParamPrePost": 1.0}}},
                {"type": 4, "FXDelay": {"plainParams": {"kParamTimeL": 0.0387, "kParamOffsetL": 1.5, "kParamMode": 1.0, "kParamWet": 25.0}}},
                {"type": 5, "FXComp": {"plainParams": {"kParamMultiband": 1.0, "kParamRatio": 4.0, "kParamThresh": 0.5}}},
                {"type": 7, "FXEQ": {"plainParams": {"kParamType1": 2.0, "kParamFreq1": 80.0, "kParamType2": 1.0, "kParamGain2": 20.0}}},
                {"type": 3, "FXChorus": {"plainParams": "default"}},
                {"type": 6, "FXReverb": {"plainParams": {"kParamType": "kHall", "kParamSize": 70.0, "kParamWet": 20.0}}},
                {"type": 6, "FXReverb": {"plainParams": {"kParamWet": 10.0}}},
                {"type": 8, "FXFilter": {"plainParams": {"kParamType": "LNH24", "kParamVar": 25.0}}},
                {"type": 10, "FXBode": {"plainParams": "default"}},
            ]
        },
        "FXRack1": {"FX": [{"type": 11, "FXConv": {"plainParams": "default"}}]},
    }
    patch = serum2.Serum2Patch(name="synthetic", author="", description="", tags=[], product_version="", state=state)
    conv = Conversion(name="synthetic")
    serum2_fx.convert_fx_racks(patch, conv)

    s = conv.settings
    assert s["chorus_on"] == 1.0 and s["chorus_voices"] == 2.0
    assert s["distortion_type"] == 0.0 and s["distortion_filter_order"] == 1.0
    assert s["delay_style"] == 2.0 and s["delay_sync"] == fx_common.SYNC_DOTTED and s["delay_tempo"] == 9.0
    assert s["compressor_enabled_bands"] == 0.0
    assert s["eq_low_mode"] == 1.0 and s["eq_band_gain"] == 15.0
    assert s["reverb_on"] == 1.0 and abs(s["reverb_size"] - 0.7) < 1e-9
    assert s["filter_fx_model"] == fx_common.FILTER_ANALOG and abs(s["filter_fx_blend"] - 0.5) < 1e-9
    assert any(n.startswith("resource-conflict: second Chorus") for n in conv.notes)
    assert any(n.startswith("resource-conflict: second Reverb") for n in conv.notes)
    assert any(n.startswith("unsupported: Bode") for n in conv.notes)
    assert any(n == "unsupported: FX bus 1 with Conv" for n in conv.notes)

    expected = fx_common.vital_chain_from_rack(["chorus", "distortion", "delay", "compressor", "eq", "reverb", "filter_fx"])
    assert s["effect_chain_order"] == fx_common.encode_effect_order(expected)
    for key, value in s.items():
        assert key in PARAMS
        assert PARAMS[key][0] <= value <= PARAMS[key][1], key
