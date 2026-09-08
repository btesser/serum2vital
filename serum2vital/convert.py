"""Command line interface: convert Serum 1/2 presets into Vital presets.

    python -m serum2vital "<Serum data folder>/Presets" --serum-root "<Serum data folder>" --out ./out
    python -m serum2vital one_preset.fxp --out ./out --report report.json

Nothing is written until you pass --out, and existing files are skipped unless
you pass --overwrite, so a first run can safely be pointed at a whole library.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from . import serum1, serum2
from .categorize import categorize
from .serum1 import NotASerumPreset as NotASerum1
from .serum2 import NotASerumPreset as NotASerum2
from .mapping import Conversion, convert_serum1, convert_serum2
from .wavetables import (
    builtin_wavetable,
    DEFAULT_FRAME_LIMIT,
    WavetableError,
    load_serum_wavetable,
    sample_to_vital,
    wavetable_to_vital,
)
from .writer import write

SERUM1_EXTENSIONS = {".fxp"}
SERUM2_EXTENSIONS = {".serumpreset"}


@dataclass
class Options:
    serum_root: Path | None = None
    max_frames: int = DEFAULT_FRAME_LIMIT
    max_sample_seconds: float = 4.0
    wavetables: bool = True
    samples: bool = True


@dataclass
class Result:
    source: Path
    output: Path | None = None
    status: str = "ok"          # ok | skipped | failed
    detail: str = ""
    notes: list[str] = field(default_factory=list)
    category: tuple[str, str, str] | None = None


# Where Serum keeps the assets a preset can point at.  Serum 2 presets use paths
# like "S2 Tables/Digital/FM Piano.wav" that are relative to its own Tables
# folder, while Serum 1 presets use "Analog/Basic Shapes.wav"; searching both
# roots handles either, plus presets that reference the other version's library.
TABLE_ROOTS = ("Tables", "Serum 2 Presets/Tables")
NOISE_ROOTS = ("Noises", "Serum 2 Presets/Noises")


def _find_asset(root: Path, subdirs: tuple[str, ...], reference: str, cache: dict) -> Path | None:
    """Resolve a Serum asset reference such as 'Analog/Basic Shapes.wav'."""
    if not reference:
        return None
    reference = reference.replace("\\", "/").lstrip("/")
    for subdir in subdirs:
        candidate = root.joinpath(subdir, reference)
        if candidate.is_file():
            return candidate

    # Serum records a path relative to whichever library folder the table came
    # from, so fall back to an index of file names built once per run.  This also
    # rescues presets whose table has since been moved between packs.
    name = Path(reference).name.lower()
    for subdir in subdirs:
        base = root / subdir
        if not base.is_dir():
            continue
        index = cache.get(base)
        if index is None:
            index = {}
            for found in base.rglob("*.wav"):
                index.setdefault(found.name.lower(), found)
            cache[base] = index
        if name in index:
            return index[name]
    return None


def _attach_assets(conv: Conversion, options: Options, cache: dict) -> None:
    """Load the Serum wavetables and noise sample this preset refers to."""
    if options.serum_root is None:
        if any(conv.wavetable_refs):
            conv.note("no --serum-root given; oscillators use a placeholder sine wavetable")
        return

    if options.wavetables:
        for slot, reference in enumerate(conv.wavetable_refs):
            if not reference:
                continue
            path = _find_asset(options.serum_root, TABLE_ROOTS, reference, cache)
            if path is None:
                # Serum's basic shapes live inside the plugin, not in Tables/.
                if reference.endswith("Default Shapes.wav"):
                    reference = "saw.wav"
                shape = builtin_wavetable(reference)
                if shape is not None:
                    conv.wavetables[slot] = shape
                else:
                    conv.note(f"wavetable {reference!r} not found under {options.serum_root}")
                continue
            try:
                table = load_serum_wavetable(path)
            except WavetableError as exc:
                conv.note(f"wavetable {reference!r} unreadable: {exc}")
                continue
            conv.wavetables[slot] = wavetable_to_vital(
                table, name=Path(reference).stem, max_keyframes=options.max_frames
            )

    if options.samples and conv.sample_ref:
        path = _find_asset(options.serum_root, NOISE_ROOTS, conv.sample_ref, cache)
        if path is None:
            conv.note(f"noise sample {conv.sample_ref!r} not found under {options.serum_root}")
        else:
            sample = sample_to_vital(path, name=Path(conv.sample_ref).stem,
                                     max_seconds=options.max_sample_seconds)
            if sample is None:
                conv.note(f"noise sample {conv.sample_ref!r} unreadable")
            else:
                conv.sample = sample


def convert_file(path: Path, options: Options, cache: dict | None = None) -> Conversion:
    """Parse one Serum preset and map it to a Vital conversion."""
    suffix = path.suffix.lower()
    if suffix in SERUM2_EXTENSIONS:
        patch = serum2.read(str(path))
        conv = convert_serum2(patch)
        bank, tags = patch.description, list(patch.tags)
    elif suffix in SERUM1_EXTENSIONS:
        patch = serum1.read(str(path))
        conv = convert_serum1(patch)
        bank, tags = patch.menu, []
    else:
        raise ValueError(f"unsupported extension {suffix!r}")
    _attach_assets(conv, options, cache if cache is not None else {})
    conv.category = categorize(conv.name, bank, str(path), tags, conv.settings, notes=conv.notes)
    return conv


def collect(inputs: list[Path]) -> list[Path]:
    """Gather every preset under `inputs`, skipping obvious non-presets.

    Preset packs distributed as macOS archives carry AppleDouble sidecars named
    `._Something.fxp`; they have the same extension but hold a resource fork, so
    they are dropped here rather than counted as failures.
    """
    found: list[Path] = []
    seen: set[str] = set()
    for entry in inputs:
        if entry.is_dir():
            for path in sorted(_walk(entry)):
                if path.suffix.lower() not in SERUM1_EXTENSIONS | SERUM2_EXTENSIONS:
                    continue
                if path.name.startswith("._"):
                    continue
                key = str(path.resolve()).lower()
                if key in seen:
                    continue
                seen.add(key)
                found.append(path)
        elif entry.is_file():
            found.append(entry)
    return found


def _is_reparse_point(path: Path) -> bool:
    import os
    import stat

    try:
        attributes = os.lstat(path).st_file_attributes
    except (OSError, AttributeError):
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _walk(root: Path):
    """rglob that does not descend into symlinks/junctions.

    Serum 2 installs a junction "S1 Presets" pointing back at the Serum 1
    library, which would otherwise convert every Serum 1 preset twice.
    """
    for child in root.iterdir():
        if child.is_dir():
            if child.is_symlink() or _is_reparse_point(child):
                continue
            yield from _walk(child)
        else:
            yield child


def output_path(source: Path, inputs: list[Path], out_root: Path, flatten: bool) -> Path:
    if flatten:
        return out_root / f"{source.stem}.vital"
    for entry in inputs:
        if entry.is_dir():
            try:
                return (out_root / source.relative_to(entry)).with_suffix(".vital")
            except ValueError:
                continue
    return out_root / f"{source.stem}.vital"


_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def organized_path(conv: Conversion, source: Path, out_root: Path, claimed: set[Path]) -> Path:
    """<out>/<INSTRUMENT>/<TYPE>/<MODIFIER>/<name>.vital, unique within this run.

    Preset names repeat across packs, so a second "Reese 01" gets " (author)"
    appended, and a third (or an authorless one) " (2)", " (3)", ...
    """
    instrument, type_, modifier = conv.category or ("SYNTH", "GENERAL", "CLEAN")
    folder = out_root / instrument / type_ / modifier
    stem = _UNSAFE_FILENAME.sub("_", conv.name).strip(" ._") or source.stem
    author = _UNSAFE_FILENAME.sub("_", conv.author).strip(" ._")
    candidates = [stem]
    if author:
        candidates.append(f"{stem} ({author})")
    for candidate in candidates:
        target = folder / f"{candidate}.vital"
        if target not in claimed:
            claimed.add(target)
            return target
    counter = 2
    while (target := folder / f"{stem} ({counter}).vital") in claimed:
        counter += 1
    claimed.add(target)
    return target


def run(args: argparse.Namespace) -> int:
    inputs = [Path(p) for p in args.inputs]
    missing = [p for p in inputs if not p.exists()]
    if missing:
        print("no such path: " + ", ".join(str(p) for p in missing), file=sys.stderr)
        return 2

    sources = collect(inputs)
    if args.limit:
        sources = sources[: args.limit]
    if not sources:
        print("no Serum presets found", file=sys.stderr)
        return 1

    serum_root = Path(args.serum_root) if args.serum_root else None
    if serum_root is not None and not serum_root.is_dir():
        print(f"--serum-root {serum_root} is not a directory", file=sys.stderr)
        return 2

    options = Options(
        serum_root=serum_root,
        max_frames=args.max_frames,
        max_sample_seconds=args.max_sample_seconds,
        wavetables=not args.no_wavetables,
        samples=not args.no_samples,
    )
    out_root = Path(args.out) if args.out else None

    asset_cache: dict = {}
    claimed: set[Path] = set()
    results: list[Result] = []
    for index, source in enumerate(sources, 1):
        result = Result(source=source)
        try:
            conv = convert_file(source, options, asset_cache)
            result.notes = list(conv.notes)
            result.category = conv.category
            if out_root is not None:
                if args.organize:
                    target = organized_path(conv, source, out_root, claimed)
                else:
                    target = output_path(source, inputs, out_root, args.flatten)
                if target.exists() and not args.overwrite:
                    result.status = "skipped"
                    result.detail = "output exists (use --overwrite)"
                else:
                    write(conv, target)
                    result.output = target
            else:
                result.status = "ok"
                result.detail = "dry run (no --out given)"
        except (NotASerum1, NotASerum2) as exc:
            # Preset folders routinely hold other plugins' .fxp files.
            result.status = "skipped"
            result.detail = str(exc)
        except Exception as exc:  # one bad preset must not stop a library run
            result.status = "failed"
            result.detail = f"{type(exc).__name__}: {exc}"
            if args.traceback:
                traceback.print_exc()
        results.append(result)

        if args.verbose or result.status == "failed":
            print(f"[{index}/{len(sources)}] {result.status:7s} {source.name} {result.detail}")
        elif index % 100 == 0:
            print(f"[{index}/{len(sources)}] ...", flush=True)

    ok = sum(1 for r in results if r.status == "ok")
    skipped = sum(1 for r in results if r.status == "skipped")
    failed = sum(1 for r in results if r.status == "failed")
    print(f"\n{ok} converted, {skipped} skipped, {failed} failed (of {len(results)})")

    note_counts: dict[str, int] = {}
    class_counts: dict[str, int] = {}
    for result in results:
        for note in result.notes:
            note_counts[note] = note_counts.get(note, 0) + 1
            fidelity = note.split(":", 1)[0] if ":" in note else "other"
            class_counts[fidelity] = class_counts.get(fidelity, 0) + 1
    if note_counts:
        print("\nnotes by fidelity class (approximation / conflict / unsupported / unknown):")
        for fidelity, count in sorted(class_counts.items(), key=lambda kv: -kv[1]):
            print(f"  {count:6d}x  {fidelity}")
        print("\nmost common conversion notes:")
        for note, count in sorted(note_counts.items(), key=lambda kv: -kv[1])[:20]:
            print(f"  {count:6d}x  {note}")

    if args.organize:
        instrument_counts: dict[str, int] = {}
        folder_counts: dict[str, int] = {}
        for result in results:
            if result.category:
                instrument_counts[result.category[0]] = instrument_counts.get(result.category[0], 0) + 1
                folder = "/".join(result.category)
                folder_counts[folder] = folder_counts.get(folder, 0) + 1
        if instrument_counts:
            print("\npresets by instrument:")
            for instrument, count in sorted(instrument_counts.items(), key=lambda kv: -kv[1]):
                print(f"  {count:6d}x  {instrument}")
            print(f"\nmost common folders ({len(folder_counts)} in total):")
            for folder, count in sorted(folder_counts.items(), key=lambda kv: -kv[1])[:20]:
                print(f"  {count:6d}x  {folder}")

    if args.report:
        report = {
            "converted": ok,
            "skipped": skipped,
            "failed": failed,
            "notes": note_counts,
            "results": [
                {
                    "source": str(r.source),
                    "output": str(r.output) if r.output else None,
                    "status": r.status,
                    "detail": r.detail,
                    "notes": r.notes,
                    "category": list(r.category) if r.category else None,
                }
                for r in results
            ],
        }
        Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nwrote report to {args.report}")

    return 1 if failed and not ok else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="serum2vital",
        description="Convert Xfer Serum 1 (.fxp) and Serum 2 (.SerumPreset) presets to Vital (.vital).",
    )
    parser.add_argument("inputs", nargs="+", help="preset files or folders to convert")
    parser.add_argument("--out", help="output folder; omit for a dry run that only reports")
    parser.add_argument(
        "--serum-root",
        help="Serum data folder containing Tables/ and Noises/ (the folder Serum calls 'Serum Presets'), "
        "used to embed the wavetables a preset refers to",
    )
    parser.add_argument("--max-frames", type=int, default=DEFAULT_FRAME_LIMIT,
                        help=f"max wavetable keyframes to embed (default {DEFAULT_FRAME_LIMIT})")
    parser.add_argument("--max-sample-seconds", type=float, default=4.0,
                        help="trim embedded noise samples to this length (default 4)")
    parser.add_argument("--no-wavetables", action="store_true", help="skip wavetable embedding")
    parser.add_argument("--no-samples", action="store_true", help="skip noise-sample embedding")
    parser.add_argument("--flatten", action="store_true", help="write all output into one folder")
    parser.add_argument("--organize", action="store_true",
                        help="write into <out>/INSTRUMENT/TYPE/MODIFIER/ folders classified from "
                        "the preset name, bank, source folder and sound")
    parser.add_argument("--overwrite", action="store_true", help="replace existing .vital files")
    parser.add_argument("--limit", type=int, help="only process the first N presets")
    parser.add_argument("--report", help="write a JSON conversion report here")
    parser.add_argument("-v", "--verbose", action="store_true", help="log every preset")
    parser.add_argument("--traceback", action="store_true", help="print tracebacks on failure")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
