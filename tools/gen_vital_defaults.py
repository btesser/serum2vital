"""Generate serum2vital/vital_defaults.py from Vital's own synth_parameters.cpp.

Vital (GPLv3, https://github.com/mtytel/vital) declares every synth parameter in
src/common/synth_parameters.cpp as a `ValueDetails` literal:

    { name, version_added, min, max, default_value,
      post_offset, display_multiply, value_scale, display_invert,
      display_units, display_name, string_lookup }

and then expands the per-module lists (env/lfo/random/osc/filter/mod) into
`<prefix>_<n>_<name>` ids in ValueDetailsLookup's constructor.

This script reproduces that expansion so we get an authoritative table of every
Vital parameter id, its range and its factory default -- which is exactly what a
converter needs in order to emit a valid "init patch plus overrides".

Usage:
    curl -o synth_parameters.cpp \
      https://raw.githubusercontent.com/mtytel/vital/main/src/common/synth_parameters.cpp
    python tools/gen_vital_defaults.py synth_parameters.cpp serum2vital/vital_defaults.py
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

# Constants referenced by the parameter table, resolved from Vital's headers.
# (synth_constants.h, distortion.h, digital_svf.h, random_lfo.h, synth_lfo.h,
#  synth_oscillator.h, compressor.h, voice_handler.h, wave_frame.h)
CONSTANTS = {
    "kNumLfos": 8,
    "kNumOscillators": 3,
    "kNumOscillatorWaveFrames": 257,
    "kNumEnvelopes": 6,
    "kNumRandomLfos": 4,
    "kNumMacros": 4,
    "kNumFilters": 2,
    "kNumFormants": 4,
    "kNumChannels": 2,
    "kMaxPolyphony": 33,
    "kMaxActivePolyphony": 32,
    "kMaxModulationConnections": 64,
    "kNumFilterModels": 8,
    "constants::kNumSourceDestinations": 5,
    "constants::kNumEffects": 9,
    "vital::kNumEffects": 9,
    "kNumSourceDestinations": 5,
    "kNumEffects": 9,
    "Distortion::kMinDrive": -30.0,
    "Distortion::kMaxDrive": 30.0,
    "DigitalSvf::kMinGain": -15.0,
    "DigitalSvf::kMaxGain": 15.0,
    "RandomLfo::kNumStyles": 4,
    "SynthLfo::kNumSyncTypes": 6,
    "SynthLfo::kNumSyncOptions": 5,
    "SynthOscillator::kNumUnisonStackTypes": 11,
    "SynthOscillator::kNumDistortionTypes": 13,
    "SynthOscillator::kNumSpectralMorphTypes": 12,
    "MultibandCompressor::kNumBandOptions": 4,
    "PredefinedWaveFrames::kNumShapes": 6,
    "VoiceHandler::kNumVoiceOverrides": 2,
    "VoiceHandler::kNumVoicePriorities": 5,
    "VoiceHandler::kKill": 0,
    "VoiceHandler::kRoundRobin": 4,
    "kDegreesPerCycle": 360.0,
}

SCALES = {
    "kIndexed": "indexed",
    "kLinear": "linear",
    "kQuadratic": "quadratic",
    "kCubic": "cubic",
    "kQuartic": "quartic",
    "kSquareRoot": "square_root",
    "kExponential": "exponential",
}

# ValueDetails entry: "name", version, 5 numeric exprs, ValueDetails::kScale, ...
ENTRY_RE = re.compile(
    r'\{\s*"([^"]*)"\s*,\s*(0x[0-9a-fA-F]+)\s*,'      # name, version
    r'\s*([^,]+?)\s*,\s*([^,]+?)\s*,\s*([^,]+?)\s*,'   # min, max, default
    r'\s*([^,]+?)\s*,\s*([^,]+?)\s*,'                  # post_offset, display_multiply
    r'\s*ValueDetails::(k\w+)\s*,'                     # value_scale
    r'\s*(true|false)\s*,'                             # display_invert
    r'\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,'                # units, display name
    r'\s*(?:nullptr|[\w:]+)\s*\}',                     # string_lookup
    re.S,
)


def evaluate(expr: str) -> float:
    """Evaluate a C++ numeric expression made of literals and known constants."""
    expr = expr.strip().rstrip("f")
    expr = re.sub(r"\bf\b", "", expr)
    # Namespace qualifiers carry no information here; the class-qualified names
    # that do (Distortion::, DigitalSvf::, ...) are listed in CONSTANTS.
    expr = expr.replace("vital::", "").replace("constants::", "")
    # Longest names first so `SynthLfo::kNumSyncTypes` wins over `kNumSyncTypes`.
    for name in sorted(CONSTANTS, key=len, reverse=True):
        expr = expr.replace(name, repr(CONSTANTS[name]))
    expr = expr.replace("utils::", "")
    expr = re.sub(r"(\d)f\b", r"\1", expr)
    try:
        return float(eval(expr, {"__builtins__": {}}, {"factorial": math.factorial}))  # noqa: S307
    except Exception as exc:  # pragma: no cover - surfaces unresolved constants
        raise SystemExit(f"cannot evaluate C++ expression {expr!r}: {exc}")


def parse_array(source: str, array_name: str) -> list[dict]:
    start = source.index(f"ValueDetailsLookup::{array_name}[] = {{")
    depth, i = 0, source.index("{", start)
    for end in range(i, len(source)):
        if source[end] == "{":
            depth += 1
        elif source[end] == "}":
            depth -= 1
            if depth == 0:
                break
    body = source[i : end + 1]

    out = []
    for m in ENTRY_RE.finditer(body):
        name, version, mn, mx, dflt, post, mult, scale, invert, units, disp = m.groups()
        out.append(
            {
                "name": name,
                "min": evaluate(mn),
                "max": evaluate(mx),
                "default": evaluate(dflt),
                "post_offset": evaluate(post),
                "display_multiply": evaluate(mult),
                "scale": SCALES[scale],
                "display_invert": invert == "true",
                "units": units,
                "display_name": disp,
            }
        )
    return out


def main(cpp_path: str, out_path: str) -> None:
    source = Path(cpp_path).read_text(encoding="utf-8", errors="replace")

    globals_ = parse_array(source, "parameter_list")
    groups = {
        "env": (parse_array(source, "env_parameter_list"), CONSTANTS["kNumEnvelopes"]),
        "lfo": (parse_array(source, "lfo_parameter_list"), CONSTANTS["kNumLfos"]),
        "random": (parse_array(source, "random_lfo_parameter_list"), CONSTANTS["kNumRandomLfos"]),
        "osc": (parse_array(source, "osc_parameter_list"), CONSTANTS["kNumOscillators"]),
        "filter": (parse_array(source, "filter_parameter_list"), CONSTANTS["kNumFilters"]),
        "modulation": (parse_array(source, "mod_parameter_list"), CONSTANTS["kMaxModulationConnections"]),
    }

    params: dict[str, dict] = {}
    for entry in globals_:
        params[entry["name"]] = entry

    for prefix, (entries, count) in groups.items():
        for index in range(1, count + 1):
            for entry in entries:
                copy = dict(entry)
                copy["name"] = f"{prefix}_{index}_{entry['name']}"
                params[copy["name"]] = copy

    # `filter_fx_*` is an extra filter group keyed by "fx" rather than a number.
    for entry in groups["filter"][0]:
        copy = dict(entry)
        copy["name"] = f"filter_fx_{entry['name']}"
        params[copy["name"]] = copy

    # The public mtytel/vital tree is Vital 1.0.x; released Vital is 1.5.5.
    # Reconcile the two so the emitted preset matches what 1.5.5 actually reads.
    # (Vital ignores unknown keys and defaults missing ones, so this is belt and
    # braces -- but it keeps the generated table honest about what exists.)
    for name in list(params):
        # 1.5.5 dropped the sub oscillator and the per-source filter input
        # toggles; source routing now goes through osc_<n>_destination.
        if name.startswith("sub_") or name == "compressor_low_band_unused":
            del params[name]
        elif re.match(r"filter_\d+_(?:osc[123]|sample)_input$", name):
            del params[name]
        elif re.match(r"filter_fx_(?:osc[123]|sample|filter)_input$", name):
            del params[name]
    for osc in range(1, CONSTANTS["kNumOscillators"] + 1):
        params[f"osc_{osc}_spectral_morph_phase"] = {
            "name": f"osc_{osc}_spectral_morph_phase",
            "min": 0.0, "max": 1.0, "default": 0.5,
            "post_offset": 0.0, "display_multiply": 100.0,
            "scale": "linear", "display_invert": False,
            "units": "%", "display_name": f"Oscillator {osc} Frequency Morph Phase",
        }

    # Overrides applied at the end of ValueDetailsLookup's constructor.
    for name, value in {
        "osc_1_on": 1.0,
        "osc_2_destination": 1.0,
        "osc_3_destination": 3.0,


    }.items():
        params[name]["default"] = value

    lines = [
        '"""Vital parameter table -- AUTO-GENERATED, do not edit by hand.',
        "",
        "Regenerate with tools/gen_vital_defaults.py from Vital's synth_parameters.cpp.",
        "Each entry is (min, max, default, scale).",
        '"""',
        "",
        "PARAMS = {",
    ]
    for name in sorted(params):
        p = params[name]
        lines.append(
            "    %r: (%r, %r, %r, %r)," % (name, p["min"], p["max"], p["default"], p["scale"])
        )
    lines += [
        "}",
        "",
        "DEFAULTS = {name: spec[2] for name, spec in PARAMS.items()}",
        "",
        "",
        "def clamp(name, value):",
        '    """Clamp `value` into the declared range of Vital parameter `name`."""',
        "    spec = PARAMS.get(name)",
        "    if spec is None:",
        "        return value",
        "    return max(spec[0], min(spec[1], value))",
        "",
    ]
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_path}: {len(params)} parameters")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
