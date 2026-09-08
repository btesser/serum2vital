"""Reader for Xfer Serum 2 presets (``.SerumPreset`` and friends).

Container layout (little-endian throughout):

    b"XferJson\\x00"
    uint64   length of the JSON metadata header
    bytes    JSON metadata  (presetName, presetAuthor, tags, productVersion, ...)
    uint32   size of the payload once decompressed
    uint32   payload encoding (2 == zstd)
    bytes    zstd frame wrapping a CBOR document

The CBOR document is a flat map of module name -> module state, e.g. ``Env0``,
``LFO3``, ``Oscillator1``, ``VoiceFilter0``, ``ModSlot17``, ``FXRack0``.  Each
module carries a ``plainParams`` entry which is either the string ``"default"``
(the module is entirely at its defaults) or a map holding **only** the
parameters that differ from their default -- so absence means "default", and a
converter has to supply Serum's defaults itself.

Unlike Serum 1, values here are in real units already (Hz, dB, seconds, ...),
which is why the Serum 2 path needs no denormalisation table.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAGIC = b"XferJson\x00"
ENCODING_ZSTD = 2


class SerumReadError(Exception):
    """Raised when a Serum 2 preset is present but cannot be parsed."""


class NotASerumPreset(SerumReadError):
    """The file does not carry a Serum 2 container header at all."""


@dataclass
class Serum2Patch:
    name: str
    author: str
    description: str
    tags: list[str]
    product_version: str
    meta: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    source_path: str = ""
    version: str = "serum2"

    def module(self, name: str) -> dict[str, Any]:
        value = self.state.get(name)
        return value if isinstance(value, dict) else {}

    def plain_params(self, module: str) -> dict[str, float]:
        """Non-default parameters of `module`; empty when it is untouched."""
        params = self.module(module).get("plainParams")
        return params if isinstance(params, dict) else {}

    def param(self, module: str, key: str, default: float) -> float:
        """A Serum 2 parameter, falling back to the caller's known default."""
        value = self.plain_params(module).get(key, default)
        return value if isinstance(value, (int, float)) else default

    def osc_type(self, index: int) -> str:
        """e.g. 'kOsc_Wavetable', 'kOsc_MultiSample', 'kOsc_Sample'."""
        value = self.plain_params(f"Oscillator{index}").get("kParamType")
        return value if isinstance(value, str) else "kOsc_Wavetable"


def _decompress(payload: bytes, expected: int) -> bytes:
    try:
        import zstandard
    except ImportError as exc:  # pragma: no cover - environment issue
        raise SerumReadError(
            "reading Serum 2 presets needs the 'zstandard' package "
            "(pip install zstandard cbor2)"
        ) from exc
    decompressor = zstandard.ZstdDecompressor(max_window_size=2**31)
    return decompressor.decompress(payload, max_output_size=expected + 64)


def read(path: str) -> Serum2Patch:
    """Parse a Serum 2 preset into a :class:`Serum2Patch`."""
    try:
        import cbor2
    except ImportError as exc:  # pragma: no cover - environment issue
        raise SerumReadError(
            "reading Serum 2 presets needs the 'cbor2' package "
            "(pip install zstandard cbor2)"
        ) from exc

    data = Path(path).read_bytes()
    if not data.startswith(MAGIC):
        raise NotASerumPreset("missing XferJson header")

    json_length = struct.unpack_from("<Q", data, len(MAGIC))[0]
    header_end = len(MAGIC) + 8
    try:
        meta = json.loads(data[header_end : header_end + json_length])
    except ValueError as exc:
        raise SerumReadError(f"bad JSON metadata header: {exc}") from exc

    cursor = header_end + json_length
    raw_size, encoding = struct.unpack_from("<2I", data, cursor)
    if encoding != ENCODING_ZSTD:
        raise SerumReadError(f"unsupported payload encoding {encoding}")

    blob = _decompress(data[cursor + 8 :], raw_size)
    state = cbor2.loads(blob)
    if not isinstance(state, dict):
        raise SerumReadError("payload is not a CBOR map")

    return Serum2Patch(
        name=str(meta.get("presetName") or state.get("presetName") or Path(path).stem),
        author=str(meta.get("presetAuthor") or ""),
        description=str(meta.get("presetDescription") or ""),
        tags=[str(t) for t in meta.get("tags", []) if isinstance(t, str)],
        product_version=str(meta.get("productVersion") or ""),
        meta=meta,
        state=state,
        source_path=path,
    )
