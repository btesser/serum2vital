"""Assemble a :class:`~serum2vital.mapping.Conversion` into a ``.vital`` file.

A ``.vital`` preset is plain UTF-8 JSON:

    {"author": ..., "comments": ..., "macro1".."macro4": ...,
     "preset_name": ..., "preset_style": ..., "synth_version": "1.5.5",
     "settings": { <775 scalar parameters>, "lfos": [...], "wavetables": [...],
                   "modulations": [...], "sample": {...}, ... }}

Vital fills in anything missing from its own defaults and ignores keys it does
not know, but writing the complete parameter set keeps the output independent of
whatever patch happened to be loaded before.
"""

from __future__ import annotations

import base64
import json
import random
import struct
from pathlib import Path

from .mapping import Conversion
from .vital_defaults import DEFAULTS
from .wavetables import default_wavetable

# Vital's loader reads settings["sample"] without checking that it exists and
# then indexes ["length"] on it, so every preset has to carry one even when the
# sample oscillator is switched off.
SYNTH_VERSION = "1.5.5"


def _placeholder_sample(length: int = 2048) -> dict:
    """A short deterministic noise buffer, matching Vital's own default source."""
    rng = random.Random(0)
    pcm = struct.pack("<%dh" % length, *[rng.randint(-32000, 32000) for _ in range(length)])
    return {
        "name": "White Noise",
        "length": length,
        "sample_rate": 44100,
        "samples": base64.b64encode(pcm).decode("ascii"),
    }

DEFAULT_LFO = {
    "name": "Triangle",
    "num_points": 3,
    "points": [0.0, 1.0, 0.5, 0.0, 1.0, 1.0],
    "powers": [0.0, 0.0, 0.0],
    "smooth": False,
}


def build(conversion: Conversion) -> dict:
    """Return the full preset document for `conversion`."""
    settings = dict(DEFAULTS)
    settings.update(conversion.settings)

    settings["lfos"] = [lfo or dict(DEFAULT_LFO) for lfo in conversion.lfos[:8]]
    while len(settings["lfos"]) < 8:
        settings["lfos"].append(dict(DEFAULT_LFO))

    settings["wavetables"] = [
        table or default_wavetable(f"Init {index + 1}")
        for index, table in enumerate(conversion.wavetables[:3])
    ]
    while len(settings["wavetables"]) < 3:
        settings["wavetables"].append(default_wavetable(f"Init {len(settings['wavetables']) + 1}"))

    # Vital always writes 64 modulation slots; unused ones are blank.
    modulations = list(conversion.modulations[:64])
    modulations += [{"source": "", "destination": ""}] * (64 - len(modulations))
    settings["modulations"] = modulations

    settings["custom_warps"] = [dict(DEFAULT_LFO) for _ in range(3)]
    # Vital 1.5.5 saves three random_values entries; a fourth corrupts its loader.
    settings["random_values"] = [{"seed": 0} for _ in range(3)]
    settings["sample"] = conversion.sample if conversion.sample is not None else _placeholder_sample()

    return {
        "author": conversion.author,
        "comments": conversion.comments,
        "macro1": conversion.macro_names[0],
        "macro2": conversion.macro_names[1],
        "macro3": conversion.macro_names[2],
        "macro4": conversion.macro_names[3],
        "preset_name": conversion.name,
        "preset_style": conversion.style,
        "settings": settings,
        "synth_version": SYNTH_VERSION,
    }


def write(conversion: Conversion, path: str | Path) -> Path:
    """Write `conversion` to `path` as a ``.vital`` preset."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = build(conversion)
    path.write_text(json.dumps(document, separators=(",", ":")), encoding="utf-8")
    return path
