"""Tests for serum2vital.categorize: explicit name cases plus a corpus sample."""

from __future__ import annotations

import glob
import random
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from serum2vital import serum1, serum2  # noqa: E402
from serum2vital.categorize import INSTRUMENTS, categorize  # noqa: E402
from serum2vital.convert import organized_path  # noqa: E402
from serum2vital.mapping import Conversion, convert_serum1  # noqa: E402

import os

SERUM_ROOT = Path(os.environ.get("SERUM_ROOT", "D:/VSTData/serum"))
SERUM1_ROOT = SERUM_ROOT / "Presets"
SERUM2_ROOT = SERUM_ROOT / "Serum 2 Presets"
FOLDER_SAFE = re.compile(r"^[A-Z0-9_]+$")


@pytest.mark.parametrize(
    "name, bank, path, expected",
    [
        ("LD - Good Vibs", "", "Presets/Hardstyle/Pack/LD - Good Vibs.fxp", ("LEAD", "HARDSTYLE", "CLEAN")),
        ("AU_HM_bass_growl_distorted", "", "Presets/x.fxp", ("BASS", "GROWL", "DISTORTED")),
        ("BASS - Filler Growl", "", "Presets/Dubstep/Bad Grizz/Bass/x.fxp", ("BASS", "GROWL", "CLEAN")),
        ("SC - Elephant", "", "Presets/Hardstyle/Screech/x.fxp", ("LEAD", "SCREECH", "CLEAN")),
        ("SSHR_Oldschool_Hardcore_Kick_07", "Hardcore Essential Tools", "x.fxp", ("DRUM", "KICK", "CLEAN")),
        ("PD Compass [KARRA]", "KARRA FOR SERUM 2", "Presets/Splice/x.fxp", ("PAD", "GENERAL", "CLEAN")),
        ("OR - Leslie Organ", "", "Factory/Organ/x.SerumPreset", ("KEYS", "ORGAN", "CLEAN")),
        ("BRM - Braam 03", "", "Tunecraft Cinematic Synths/x.fxp", ("FX", "BRAAM", "CLEAN")),
        ("SY - Vocal Pad 3", "", "Analong/SMF2000S/x.fxp", ("VOCAL", "GENERAL", "CLEAN")),
        ("808 Electric [KARRA]", "", "x.fxp", ("BASS", "808", "CLEAN")),
        ("MO_WS_DR_Kick_Frenchcore_Saw", "", "Water Spirit/x.SerumPreset", ("DRUM", "KICK", "CLEAN")),
        ("Fire Or Ice", "", "Presets/Pads/x.fxp", ("PAD", "GENERAL", "COLD")),
        ("Hip-Hop Toolkit 1", "Hip-Hop Toolkit", "Presets/x.fxp", ("SYNTH", "HIPHOP", "CLEAN")),
        ("SY Legato", "", "Euphoric Wave Serum Bass House Preset Pack/x.fxp", ("SYNTH", "HOUSE", "CLEAN")),
        ("Nameless", "Use Mod Wheel For FX", "Presets/x.fxp", ("SYNTH", "GENERAL", "CLEAN")),
        ("PL - Pluck 2", "", "x.fxp", ("PLUCK", "GENERAL", "CLEAN")),
    ],
)
def test_name_cases(name, bank, path, expected):
    assert categorize(name, bank, path, [], {}) == expected


def test_serum2_arp_tag_and_parent_folder():
    assert categorize("Something", "", "Factory/Bass/Hard/x.SerumPreset", ["Poly"], {}) == ("BASS", "GENERAL", "HARD")
    assert categorize("Something", "", "User/x.SerumPreset", ["Arp", "Poly"], {})[0] == "SEQ"


def test_settings_heuristics():
    pad = {"env_1_attack": 1.0, "env_1_sustain": 1.0}
    assert categorize("Untitled", "", "", [], pad) == ("PAD", "GENERAL", "CLEAN")
    pluck = {"env_1_attack": 0.0, "env_1_decay": 0.9, "env_1_sustain": 0.0}
    assert categorize("Untitled", "", "", [], pluck)[0] == "PLUCK"
    assert categorize("Untitled", "", "", [], {"osc_1_transpose": -24})[0] == "BASS"
    assert categorize("Untitled", "", "", [], {"sample_on": 1, "osc_1_on": 0, "osc_2_on": 0})[0] == "DRUM"

    assert categorize("X", "", "", [], {"distortion_on": 1, "distortion_drive": 20})[2] == "AGGRESSIVE"
    assert categorize("X", "", "", [], {"osc_1_distortion_type": 7})[2] == "AGGRESSIVE"
    assert categorize("X", "", "", [], {}, notes=["approximation: Hyper placed in the flanger"])[2] == "WIDE"
    assert categorize("X", "", "", [], {"osc_1_unison_voices": 8})[2] == "WIDE"
    assert categorize("X", "", "", [], {"chorus_on": 1})[2] == "WIDE"
    assert categorize("X", "", "", [], {"filter_1_on": 1, "filter_1_cutoff": 40})[2] == "DARK"
    assert categorize("X", "", "", [], {"reverb_on": 1, "delay_on": 1})[2] == "WET"
    assert categorize("X", "", "", [], {"reverb_on": 1})[2] == "CLEAN"


def test_parts_are_folder_safe_for_odd_input():
    result = categorize("weird/name: 100%", "", "", [], {})
    assert all(FOLDER_SAFE.match(part) for part in result)


def test_organized_path_collisions(tmp_path):
    claimed: set[Path] = set()
    a = Conversion(name="Reese 01", author="Alice")
    a.category = ("BASS", "REESE", "CLEAN")
    b = Conversion(name="Reese 01", author="Bob")
    b.category = ("BASS", "REESE", "CLEAN")
    c = Conversion(name="Reese 01", author="Bob")
    c.category = ("BASS", "REESE", "CLEAN")
    d = Conversion(name="Lead/Pluck: <x>", author="")
    d.category = ("LEAD", "GENERAL", "CLEAN")
    src = Path("x.fxp")
    assert organized_path(a, src, tmp_path, claimed) == tmp_path / "BASS/REESE/CLEAN/Reese 01.vital"
    assert organized_path(b, src, tmp_path, claimed) == tmp_path / "BASS/REESE/CLEAN/Reese 01 (Bob).vital"
    assert organized_path(c, src, tmp_path, claimed) == tmp_path / "BASS/REESE/CLEAN/Reese 01 (2).vital"
    assert organized_path(d, src, tmp_path, claimed) == tmp_path / "LEAD/GENERAL/CLEAN/Lead_Pluck_ _x.vital"


def _corpus_sample(limit: int = 150) -> list[Path]:
    files = [Path(p) for p in glob.glob(str(SERUM1_ROOT / "**" / "*.fxp"), recursive=True)
             if not Path(p).name.startswith("._")]
    files += [Path(p) for p in glob.glob(str(SERUM2_ROOT / "**" / "*.SerumPreset"), recursive=True)]
    random.Random(7).shuffle(files)
    return files[:limit]


@pytest.mark.skipif(not SERUM1_ROOT.is_dir(), reason="Serum preset corpus not available")
def test_corpus_sample_is_folder_safe():
    checked = 0
    for path in _corpus_sample():
        try:
            if path.suffix.lower() == ".serumpreset":
                patch = serum2.read(str(path))
                result = categorize(patch.name, patch.description, str(path), patch.tags, {})
            else:
                patch = serum1.read(str(path))
                conv = convert_serum1(patch)
                result = categorize(patch.name, patch.menu, str(path), [], conv.settings, notes=conv.notes)
        except (serum1.NotASerumPreset, serum2.NotASerumPreset):
            continue
        assert len(result) == 3
        assert all(part and FOLDER_SAFE.match(part) for part in result), (path, result)
        assert result[0] in INSTRUMENTS
        checked += 1
    assert checked > 50
