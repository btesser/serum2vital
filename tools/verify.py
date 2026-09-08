"""Sanity-check converted .vital files against what Vital 1.5.5 expects.

Vital fails silently on a malformed preset -- it just refuses to load it -- so
this checks the structural invariants that matter before you copy a few thousand
files into your preset folder.

    python tools/verify.py out/**/*.vital
    python tools/verify.py out            # walks the folder
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from serum2vital.vital_defaults import PARAMS  # noqa: E402

REQUIRED_TOP = {
    "author", "comments", "macro1", "macro2", "macro3", "macro4",
    "preset_name", "preset_style", "settings", "synth_version",
}
WAVE_DATA_BYTES = 2048 * 4


def check(path: Path) -> list[str]:
    problems: list[str] = []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"unreadable JSON: {exc}"]

    missing_top = REQUIRED_TOP - set(document)
    if missing_top:
        problems.append(f"missing top-level keys: {sorted(missing_top)}")

    settings = document.get("settings")
    if not isinstance(settings, dict):
        return problems + ["settings is not an object"]

    # Vital's loader reads settings["sample"] unguarded and indexes ["length"].
    sample = settings.get("sample")
    if not isinstance(sample, dict) or "length" not in sample or "samples" not in sample:
        problems.append("settings.sample missing or malformed (Vital will fail to load)")

    for key, count in (("wavetables", 3), ("lfos", 8), ("modulations", 64)):
        value = settings.get(key)
        if not isinstance(value, list) or len(value) != count:
            problems.append(f"settings.{key} should be a list of {count}")

    for name, value in settings.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        spec = PARAMS.get(name)
        if spec is None:
            problems.append(f"unknown parameter {name!r}")
        elif not (spec[0] - 1e-6 <= value <= spec[1] + 1e-6):
            problems.append(f"{name}={value} outside [{spec[0]}, {spec[1]}]")

    missing_params = set(PARAMS) - set(settings)
    if missing_params:
        problems.append(f"{len(missing_params)} parameters missing, e.g. {sorted(missing_params)[:3]}")

    for index, table in enumerate(settings.get("wavetables") or []):
        try:
            components = table["groups"][0]["components"]
        except Exception:
            problems.append(f"wavetable {index} has no components")
            continue
        for component in components:
            for frame in component.get("keyframes", []):
                size = len(base64.b64decode(frame["wave_data"]))
                if size != WAVE_DATA_BYTES:
                    problems.append(
                        f"wavetable {index} keyframe at {frame.get('position')} "
                        f"decodes to {size} bytes, expected {WAVE_DATA_BYTES}"
                    )
                    break

    for index, lfo in enumerate(settings.get("lfos") or []):
        points = lfo.get("points", [])
        if len(points) != 2 * lfo.get("num_points", 0):
            problems.append(f"lfo {index}: num_points does not match the points list")
        if len(lfo.get("powers", [])) != lfo.get("num_points", 0):
            problems.append(f"lfo {index}: powers list length does not match num_points")

    used = [m for m in (settings.get("modulations") or []) if m.get("source")]
    for slot, mod in enumerate(used, 1):
        if mod["destination"] not in PARAMS:
            problems.append(f"modulation {slot} targets unknown parameter {mod['destination']!r}")

    return problems


def main(argv: list[str]) -> int:
    targets: list[Path] = []
    for entry in argv or ["out"]:
        path = Path(entry)
        if path.is_dir():
            targets.extend(sorted(path.rglob("*.vital")))
        elif path.is_file():
            targets.append(path)

    if not targets:
        print("no .vital files found", file=sys.stderr)
        return 1

    bad = 0
    for path in targets:
        problems = check(path)
        if problems:
            bad += 1
            print(f"FAIL {path}")
            for problem in problems[:6]:
                print(f"     {problem}")

    print(f"\n{len(targets) - bad}/{len(targets)} presets look structurally valid")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
