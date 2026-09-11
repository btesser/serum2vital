"""LFO 5-8 switch fixtures for the classic Serum 1 layout.

The LFO 5-8 panel switches (ANCH, BPM off, DOT, TRIP, mode) are not VST
parameters, and the LFO 5-8 tab could not be reached in the GUI session that
produced DebugPresets/serum1, so these fixtures are crafted instead: one
classic-layout library preset with all LFO 5-8 switches at their defaults is
copied with a single flag byte changed in the 0x6DB8 record
(tools/craft_fxp.py), then every copy is loaded through the plugin and the
plugin's own state (which the current build writes in the new layout, where
all eight LFOs' flags are known) is read back and compared with the intent.

    python tools/lfo58_fixtures.py craft [--base preset.fxp]   # out/fixtures/lfo58/*.fxp + manifest.json
    python tools/lfo58_fixtures.py readback                    # load each fixture through Serum, compare flags
    python tools/lfo58_fixtures.py survey [--limit N]          # library: reader vs plugin for all eight LFOs

`survey` is how the record was located: it re-saves classic presets through
the plugin and reports where serum2vital.serum1 disagrees with it (none, as
of the 0x6DB8 reading).  The plugin is loaded in-process, so the `readback`
and `survey` commands end with os._exit (DawDreamer hosts crash at exit).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import zlib
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT))

import craft_fxp                                   # noqa: E402
from serum2vital import serum1                     # noqa: E402

SERUM_ROOT = Path(os.environ.get("SERUM_ROOT", "D:/VSTData/serum"))
OUT = ROOT / "out" / "fixtures" / "lfo58"
FLAG_NAMES = ("anchor", "hz", "dotted", "triplet", "not_off", "env")
DEFAULT_FLAGS = (1, 0, 0, 0, 0, 0)
RECORD_END = serum1.CLASSIC_SETTINGS_5_8 + serum1.CLASSIC_SETTINGS_END

# name -> (lfo number, {flag index: value})
CASES = {
    "lfo5 anch off": (5, {0: 0}),
    "lfo5 hz": (5, {1: 1}),
    "lfo5 dot": (5, {2: 1}),
    "lfo5 trip": (5, {3: 1}),
    "lfo5 trig": (5, {4: 1}),
    "lfo5 env": (5, {4: 1, 5: 1}),
    "lfo6 anch off": (6, {0: 0}),
    "lfo6 hz": (6, {1: 1}),
    "lfo6 dot": (6, {2: 1}),
    "lfo6 trip": (6, {3: 1}),
    "lfo6 trig": (6, {4: 1}),
    "lfo6 env": (6, {4: 1, 5: 1}),
    "lfo7 hz": (7, {1: 1}),
    "lfo8 trip": (8, {3: 1}),
}


def flag_offset(lfo: int, flag: int) -> int:
    """Byte offset of one flag in the classic LFO 5-8 record."""
    return serum1.CLASSIC_SETTINGS_5_8 + serum1.CLASSIC_SETTINGS_FLAGS + 4 * flag + (lfo - 5)


def settings_flags(s: serum1.LfoSettings) -> tuple[int, ...]:
    return (int(s.anchor), int(s.hz_mode), int(s.dotted), int(s.triplet),
            int(s.mode != "off"), int(s.mode == "env"))


def classic_lfo58_default(path: Path) -> bool:
    """True for a classic-layout preset whose LFO 5-8 record holds only defaults."""
    try:
        patch = serum1.read(str(path))
    except serum1.SerumReadError:
        return False
    if patch.layout != "classic":
        return False
    return all(s.known and settings_flags(s) == DEFAULT_FLAGS
               for s in (shape.settings for shape in patch.lfo_shapes[4:]))


def find_base() -> Path:
    for path in sorted((SERUM_ROOT / "Presets").rglob("*.fxp")):
        if classic_lfo58_default(path):
            return path
    raise SystemExit(f"no classic-layout preset with default LFO 5-8 switches under {SERUM_ROOT}")


# -- plugin read-back --------------------------------------------------------- #


def state_blob(data: bytes) -> bytes | None:
    """The decompressed state inside what DawDreamer's save_state wrote."""
    for i in range(len(data) - 1):
        if data[i] == 0x78 and data[i + 1] in (0x01, 0x5E, 0x9C, 0xDA):
            try:
                blob = zlib.decompressobj().decompress(data[i:])
            except zlib.error:
                continue
            if len(blob) >= serum1.NEW_LFO_BASE + 8 * serum1.NEW_LFO_STRIDE:
                return blob
    return None


def plugin_lfo_flags(host, preset: Path, scratch: Path) -> list[tuple[int, ...]] | None:
    """Load `preset` in Serum, save its state and return the eight LFOs' flag tuples."""
    if not host.load_preset(preset):
        return None
    host.plugin.save_state(str(scratch))
    blob = state_blob(scratch.read_bytes())
    if blob is None:
        return None
    return [
        tuple(blob[serum1.NEW_LFO_BASE + i * serum1.NEW_LFO_STRIDE + serum1.NEW_OFF_FLAGS:][:6])
        for i in range(8)
    ]


def load_host():
    from serum_host import SerumHost
    return SerumHost().load()


# -- commands ----------------------------------------------------------------- #


def craft(base: Path | None) -> None:
    base = base or find_base()
    if not classic_lfo58_default(base):
        raise SystemExit(f"{base} is not a classic-layout preset with default LFO 5-8 switches")
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, (lfo, changes) in CASES.items():
        edits = [(flag_offset(lfo, flag), bytes([value])) for flag, value in changes.items()]
        dst = craft_fxp.write(base, OUT / f"{name}.fxp", edits)
        expected = list(DEFAULT_FLAGS)
        for flag, value in changes.items():
            expected[flag] = value
        manifest.append({"name": name, "file": dst.name, "lfo": lfo, "expected": expected,
                         "edits": [[hex(off), raw.hex()] for off, raw in edits]})
    (OUT / "manifest.json").write_text(json.dumps({"base": str(base), "cases": manifest}, indent=1))
    print(f"wrote {len(manifest)} fixtures from {base.name} to {OUT}")


def readback() -> int:
    manifest = json.loads((OUT / "manifest.json").read_text())
    host = load_host()
    scratch = OUT / "state.bin"
    failures = 0
    print(f"{'fixture':16s} {'reader':22s} {'plugin':22s} ok")
    for case in manifest["cases"]:
        path = OUT / case["file"]
        lfo = case["lfo"]
        expected = tuple(case["expected"])
        reader = settings_flags(serum1.read(str(path)).lfo_shapes[lfo - 1].settings)
        plugin = plugin_lfo_flags(host, path, scratch)
        got = plugin[lfo - 1] if plugin else None
        ok = reader == expected == got
        failures += not ok
        print(f"{case['name']:16s} {str(reader):22s} {str(got):22s} {'yes' if ok else 'NO'}")
    print("all fixtures agree" if not failures else f"{failures} fixture(s) disagree")
    return 1 if failures else 0


def survey(limit: int) -> int:
    host = load_host()
    scratch = OUT / "state.bin"
    OUT.mkdir(parents=True, exist_ok=True)
    checked = 0
    short = 0
    mismatches: list[tuple[str, int, tuple, tuple]] = []
    for path in sorted((SERUM_ROOT / "Presets").rglob("*.fxp")):
        try:
            patch = serum1.read(str(path))
        except serum1.SerumReadError:
            continue
        if patch.layout != "classic":
            continue
        plugin = plugin_lfo_flags(host, path, scratch)
        if plugin is None:
            continue
        checked += 1
        if len(serum1.decompress(str(path))) < RECORD_END:
            short += 1
        for i, shape in enumerate(patch.lfo_shapes):
            mine = settings_flags(shape.settings)
            if mine != plugin[i]:
                mismatches.append((path.name, i + 1, mine, plugin[i]))
        if checked >= limit:
            break
    print(f"checked {checked} classic presets ({short} end before the LFO 5-8 record); "
          f"{len(mismatches)} LFO switch mismatches against the plugin")
    for name, lfo, mine, theirs in mismatches[:40]:
        print(f"  {name}: LFO {lfo} reader {mine} plugin {theirs}")
    return 1 if mismatches else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("craft")
    c.add_argument("--base", type=Path, default=None)
    sub.add_parser("readback")
    s = sub.add_parser("survey")
    s.add_argument("--limit", type=int, default=400)
    args = ap.parse_args(argv)
    if args.cmd == "craft":
        craft(args.base)
        return 0
    code = readback() if args.cmd == "readback" else survey(args.limit)
    sys.stdout.flush()
    os._exit(code)


if __name__ == "__main__":
    sys.exit(main())
