"""Write a Serum 1 ``.fxp`` with byte-level edits to the decompressed state.

Serum's opaque chunk is not a single zlib stream.  It is

    zlib(state blob)              the 172,736-byte state described in FORMATS.md
    zlib(second block)            16,384 bytes, identical between presets
    uint32                        unknown, identical between presets
    uint32 (little-endian)        length of the first zlib stream

and the plugin refuses a chunk whose second part is missing or whose final
length word does not match (it silently keeps the previous state), which is
why earlier attempts at crafting fixtures "loaded" as Init.  Keeping the
trailer verbatim and rewriting the length word makes edited presets load.

    python tools/craft_fxp.py src.fxp dst.fxp OFFSET=f32:VALUE [OFFSET=u16:VALUE ...]

Offsets are into the decompressed state (hex or decimal).
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

FXP_HEADER = 60


def split(path: str | Path) -> tuple[bytes, bytearray, bytes]:
    """Return (fxp header, decompressed state, trailer after the first zlib stream)."""
    data = Path(path).read_bytes()
    chunk = data[FXP_HEADER:]
    decomp = zlib.decompressobj()
    blob = decomp.decompress(chunk)
    used = len(chunk) - len(decomp.unused_data)
    return data[:FXP_HEADER], bytearray(blob), chunk[used:]


def write(src: str | Path, dst: str | Path, edits: list[tuple[int, bytes]]) -> Path:
    """Copy `src` to `dst` applying `edits` = [(offset, raw bytes), ...]."""
    header, blob, trailer = split(src)
    for offset, raw in edits:
        blob[offset : offset + len(raw)] = raw
    stream = zlib.compress(bytes(blob), 1)
    chunk = stream + trailer[:-4] + struct.pack("<I", len(stream))
    header = bytearray(header)
    struct.pack_into(">I", header, 56, len(chunk))
    struct.pack_into(">I", header, 4, FXP_HEADER + len(chunk))   # Serum stores the whole file size here
    Path(dst).write_bytes(bytes(header) + chunk)
    return Path(dst)


def f32(value: float) -> bytes:
    return struct.pack("<f", value)


def _parse_edit(text: str) -> tuple[int, bytes]:
    where, spec = text.split("=", 1)
    kind, value = spec.split(":", 1)
    offset = int(where, 0)
    if kind == "f32":
        return offset, f32(float(value))
    if kind == "u16":
        return offset, struct.pack("<H", int(value, 0))
    if kind == "u8":
        return offset, bytes([int(value, 0)])
    if kind == "hex":
        return offset, bytes.fromhex(value)
    raise SystemExit(f"unknown edit type {kind!r}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    out = write(sys.argv[1], sys.argv[2], [_parse_edit(e) for e in sys.argv[3:]])
    print(f"wrote {out}")
