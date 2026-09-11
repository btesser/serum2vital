"""LFO 5-8 switches in the classic Serum 1 layout (record at 0x6DB8).

The record was located by re-saving classic presets through the current
Serum build and correlating the plugin's flags against the old bytes; the
crafted fixtures of tools/lfo58_fixtures.py confirm every flag.  The tests
here check the reader on a synthetic blob (always) and on library presets
whose plugin read-back is known (when the library is present).
"""

import os
from pathlib import Path

import pytest

from serum2vital import serum1

SERUM_ROOT = Path(os.environ.get("SERUM_ROOT", "D:/VSTData/serum"))
REC = serum1.CLASSIC_SETTINGS_5_8
FLAGS = REC + serum1.CLASSIC_SETTINGS_FLAGS


def flags(s: serum1.LfoSettings) -> tuple:
    return (int(s.anchor), int(s.hz_mode), int(s.dotted), int(s.triplet),
            int(s.mode != "off"), int(s.mode == "env"))


def classic_blob(size: int) -> bytearray:
    """A zeroed blob the reader takes for the classic layout, with default switches."""
    blob = bytearray(size)
    blob[serum1.CLASSIC_BLOCKS[0]] = 1        # classic region not all zero
    for record in (serum1.CLASSIC_SETTINGS, REC):
        if record + serum1.CLASSIC_SETTINGS_END <= size:
            blob[record + serum1.CLASSIC_SETTINGS_FLAGS : record + serum1.CLASSIC_SETTINGS_FLAGS + 4] = b"\x01" * 4
    return blob


def test_lfo58_record_layout_matches_lfo14():
    blob = classic_blob(REC + serum1.CLASSIC_SETTINGS_END)
    blob[FLAGS + 4 + 0] = 1          # LFO 5 Hz mode
    blob[FLAGS + 8 + 1] = 1          # LFO 6 dotted
    blob[FLAGS + 12 + 2] = 1         # LFO 7 triplet
    blob[FLAGS + 16 + 3] = 1         # LFO 8 mode TRIG
    blob[FLAGS + 16 + 0] = 1         # LFO 5 mode ENV (both bytes)
    blob[FLAGS + 20 + 0] = 1
    blob[FLAGS + 0 + 1] = 0          # LFO 6 anchor off
    settings = serum1._read_classic_settings(bytes(blob))
    assert [s.known for s in settings] == [True] * 8
    assert flags(settings[4]) == (1, 1, 0, 0, 1, 1)
    assert flags(settings[5]) == (0, 0, 1, 0, 0, 0)
    assert flags(settings[6]) == (1, 0, 0, 1, 0, 0)
    assert flags(settings[7]) == (1, 0, 0, 0, 1, 0)
    assert flags(settings[0]) == (1, 0, 0, 0, 0, 0)


def test_short_blob_defaults_lfo58_as_serum_does():
    settings = serum1._read_classic_settings(bytes(classic_blob(20704)))
    assert [s.known for s in settings[:4]] == [True] * 4
    for s in settings[4:]:
        assert not s.known
        assert flags(s) == (1, 0, 0, 0, 0, 0)


def test_junk_flag_bytes_are_not_trusted():
    blob = classic_blob(REC + serum1.CLASSIC_SETTINGS_END)
    blob[FLAGS + 4 + 1] = 0x18
    settings = serum1._read_classic_settings(bytes(blob))
    assert settings[4].known and not settings[5].known


# (library preset, LFO, plugin read-back of anchor, hz, dotted, triplet, not-off, env)
LIBRARY_CASES = [
    ("Presets/Barcade/Fragment Audio- Arcade Serum-Free/SQ Boss Fight.fxp", 5, (1, 0, 0, 0, 1, 0)),
    ("Presets/Barcade/Fragment Audio- Arcade Serum-Free/SQ Boss Fight.fxp", 6, (0, 1, 0, 0, 0, 0)),
    ("Presets/BLA - Chiptune For Serum/DR - Kick.fxp", 5, (0, 1, 0, 0, 1, 1)),
    ("Presets/80s Synths/PAD - Take On Me.fxp", 5, (1, 1, 0, 0, 0, 0)),
    ("Presets/80s Synths/PAD - Take On Me.fxp", 8, (1, 1, 0, 0, 1, 0)),
    ("Presets/Dubstep/Deflo Serum Presets/Deflo - Sly me riser.fxp", 5, (1, 0, 0, 1, 0, 0)),
]


@pytest.mark.parametrize("rel,lfo,expected", LIBRARY_CASES)
def test_library_presets_match_plugin_readback(rel, lfo, expected):
    path = SERUM_ROOT / rel
    if not path.is_file():
        pytest.skip(f"{rel} not present")
    patch = serum1.read(str(path))
    assert patch.layout == "classic"
    s = patch.lfo_shapes[lfo - 1].settings
    assert s.known
    assert flags(s) == expected


def test_pre_lfo58_build_preset_is_reported_unknown():
    path = SERUM_ROOT / "Presets/Analong/ADSR_SRM_DD_ACID303_Preset.fxp"
    if not path.is_file():
        pytest.skip("preset not present")
    patch = serum1.read(str(path))
    assert len(serum1.decompress(str(path))) < REC + serum1.CLASSIC_SETTINGS_END
    for s in (shape.settings for shape in patch.lfo_shapes[4:]):
        assert not s.known and flags(s) == (1, 0, 0, 0, 0, 0)
