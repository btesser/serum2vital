"""Headless Serum 2 (VST3) host built on DawDreamer, for ground-truth read-back.

Serum 2 keeps its VST3 state as two ``XferJson`` containers (one for the
processor, one for the edit controller), each a JSON metadata header plus a
zstd-compressed CBOR map keyed by module name (``Oscillator0``, ``Env0``,
``FXRack0`` ...).  A ``.SerumPreset`` file is the *union* of both maps under a
``fileType: SerumPreset`` header.  Serum rejects a processor state that carries
keys it does not own (the controller's ``Osc``, ``Filter``, ``SerumGUI`` ...),
silently keeping its previous state, which is why a naive "paste the preset
into the state" fails.  This module splits the preset by the key sets of the
plugin's own saved state and rebuilds each container (md5 of the compressed
payload in the header ``hash``), which Serum accepts.

IMPORTANT: as with tools/serum_host.py, the process segfaults at interpreter
exit once a plugin has been loaded, so scripts must end with
``sys.stdout.flush(); os._exit(0)`` and callers should run them in a
subprocess.

    python tools/serum2_host.py preset.SerumPreset [--params "A Level,Filter 1 Type"]
                                                   [--render out.wav --note 48 --seconds 2]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vital_host import decode_juce_base64, encode_juce_base64  # noqa: E402

SERUM2_VST3 = os.environ.get("SERUM2_VST3", "C:/Program Files/Common Files/VST3/Serum2.vst3")
SETTLE_SECONDS = 0.5   # silent render after a preset load (see load_preset)

MAGIC = b"XferJson\x00"
ENCODING_ZSTD = 2
_XML_BINARY_MAGIC = b"VC2!"


# --------------------------------------------------------------------------- #
# XferJson container
# --------------------------------------------------------------------------- #
def parse_xfer(blob: bytes) -> tuple[dict, dict]:
    """Return (metadata, CBOR document) of an XferJson container."""
    import cbor2
    import zstandard

    if not blob.startswith(MAGIC):
        raise ValueError("not an XferJson container")
    n = struct.unpack_from("<Q", blob, len(MAGIC))[0]
    off = len(MAGIC) + 8
    meta = json.loads(blob[off : off + n])
    off += n
    size, enc = struct.unpack_from("<II", blob, off)
    if enc != ENCODING_ZSTD:
        raise ValueError(f"unsupported payload encoding {enc}")
    dec = zstandard.ZstdDecompressor(max_window_size=2**31).decompress(blob[off + 8 :], max_output_size=size + 64)
    return meta, cbor2.loads(dec)


def build_xfer(meta: dict, doc: dict, level: int = 3) -> bytes:
    """Inverse of parse_xfer; the header ``hash`` is the md5 of the zstd payload."""
    import cbor2
    import zstandard

    dec = cbor2.dumps(doc)
    comp = zstandard.ZstdCompressor(level=level).compress(dec)
    meta = dict(meta, hash=hashlib.md5(comp).hexdigest())
    mj = json.dumps(meta, separators=(",", ":")).encode("utf-8")
    return MAGIC + struct.pack("<Q", len(mj)) + mj + struct.pack("<II", len(dec), ENCODING_ZSTD) + comp


# --------------------------------------------------------------------------- #
# JUCE VST3 state XML (DawDreamer save_state / load_state files)
# --------------------------------------------------------------------------- #
def _tag_re(tag: str) -> re.Pattern:
    return re.compile(rb"<%s>(.*?)</%s>" % (tag.encode(), tag.encode()), re.S)


def get_blob(state: bytes, tag: str) -> bytes:
    m = _tag_re(tag).search(state)
    if not m:
        raise ValueError(f"no <{tag}> element in state")
    return decode_juce_base64(m.group(1))


def put_blob(state: bytes, tag: str, blob: bytes) -> bytes:
    enc = encode_juce_base64(blob).encode("ascii")
    open_tag, close_tag = b"<" + tag.encode() + b">", b"</" + tag.encode() + b">"
    new, n = _tag_re(tag).subn(lambda m: open_tag + enc + close_tag, state, count=1)
    if n != 1:
        raise ValueError(f"no <{tag}> element in state")
    if new[:4] == _XML_BINARY_MAGIC:  # JUCE copyXmlToBinary: fix the stored XML length
        new = bytearray(new)
        struct.pack_into("<I", new, 4, len(new) - 9)
        new = bytes(new)
    return new


def state_from_preset(template_state: bytes, preset: bytes | dict, preset_meta: dict | None = None) -> bytes:
    """Build a loadable VST3 state from a .SerumPreset (bytes or parsed CBOR doc).

    Each container of `template_state` keeps exactly its own key set; values
    are taken from the preset where the key exists there, else left as in the
    template.  Keys the preset lacks therefore stay at the template's (Init)
    values, which matches Serum's own "absent means default" convention.
    """
    if isinstance(preset, (bytes, bytearray)):
        preset_meta, preset = parse_xfer(bytes(preset))
    preset_meta = preset_meta or {}
    names = {
        "presetName": preset_meta.get("presetName", ""),
        "presetAuthor": preset_meta.get("presetAuthor", ""),
        "presetDescription": preset_meta.get("presetDescription", ""),
    }
    state = template_state
    for tag, extra in (("IComponent", {}), ("IEditController", names)):
        meta, doc = parse_xfer(get_blob(state, tag))
        new_doc = {k: (preset[k] if k in preset else v) for k, v in doc.items()}
        new_doc.update({k: v for k, v in extra.items() if k in doc})
        state = put_blob(state, tag, build_xfer(dict(meta, **extra), new_doc))
    return state


# --------------------------------------------------------------------------- #
# Host
# --------------------------------------------------------------------------- #
class Serum2Host:
    """DawDreamer wrapper around the Serum 2 VST3 plugin."""

    def __init__(self, plugin_path: str = SERUM2_VST3, sample_rate: int = 44100, block_size: int = 512,
                 scratch: str | Path | None = None):
        self.plugin_path = plugin_path
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.engine = None
        self.plugin = None
        self._index: dict[str, int] = {}
        self._template: bytes | None = None
        self._scratch = Path(scratch) if scratch else Path(os.environ.get("TEMP", ".")) / "serum2_host"

    def load(self) -> "Serum2Host":
        import dawdreamer as daw

        self.engine = daw.RenderEngine(self.sample_rate, self.block_size)
        self.plugin = self.engine.make_plugin_processor("serum2", self.plugin_path)
        self._index = {
            self.plugin.get_parameter_name(i): i for i in range(self.plugin.get_plugin_parameter_size())
        }
        self._scratch.mkdir(parents=True, exist_ok=True)
        self._template = self.get_state()
        return self

    # -- state ------------------------------------------------------------- #
    def _path(self, name: str) -> str:
        return str(self._scratch / f"{os.getpid()}_{name}")

    def get_state(self) -> bytes:
        path = self._path("state.bin")
        self.plugin.save_state(path)
        return Path(path).read_bytes()

    def set_state(self, state: bytes) -> None:
        path = self._path("state.bin")
        Path(path).write_bytes(state)
        self.plugin.load_state(path)

    def reset(self) -> None:
        """Back to the state the plugin had right after loading (Init)."""
        self.set_state(self._template)

    def load_preset(self, path: str | Path, settle_seconds: float = SETTLE_SECONDS) -> bool:
        """Load a .SerumPreset; True when Serum's read-back reflects it.

        Ends with a short silent render, as SerumHost.load_preset does: Serum 1
        glides its parameters from the previous preset for about half a second
        after a load and every reference render used to start inside that
        glide.  Serum 2 showed only about 1 dB of onset difference in the same
        test, but the settle is kept on both hosts so a reference never
        depends on what was loaded before it.
        """
        raw = Path(path).read_bytes()
        meta, doc = parse_xfer(raw)
        self.set_state(state_from_preset(self._template, doc, meta))
        back = self.controller_doc()
        if settle_seconds > 0:
            self.settle(settle_seconds)
        return back.get("presetName") == meta.get("presetName", "")

    def settle(self, seconds: float = SETTLE_SECONDS) -> None:
        """Render `seconds` of silence so the loaded state is fully in effect."""
        self.plugin.clear_midi()
        self.engine.load_graph([(self.plugin, [])])
        self.engine.render(float(seconds))

    def processor_doc(self) -> dict:
        """Serum's own processor state (CBOR map: module -> {plainParams: ...})."""
        return parse_xfer(get_blob(self.get_state(), "IComponent"))[1]

    def controller_doc(self) -> dict:
        return parse_xfer(get_blob(self.get_state(), "IEditController"))[1]

    # -- parameters -------------------------------------------------------- #
    @property
    def names(self) -> list[str]:
        return list(self._index)

    def index(self, name: str) -> int:
        if name in self._index:
            return self._index[name]
        lower = {k.lower(): v for k, v in self._index.items()}
        if name.lower() in lower:
            return lower[name.lower()]
        import difflib

        close = difflib.get_close_matches(name, self._index, n=3)
        raise KeyError(f"{name!r} is not a Serum 2 parameter (close: {close})")

    def value(self, name: str) -> float:
        return float(self.plugin.get_parameter(self.index(name)))

    def text(self, name: str) -> str:
        return str(self.plugin.get_parameter_text(self.index(name)))

    def set(self, name: str, v: float) -> None:
        self.plugin.set_parameter(self.index(name), float(v))

    def dump(self) -> dict[str, tuple[float, str]]:
        return {n: (self.value(n), self.text(n)) for n in self._index}

    # -- audio ------------------------------------------------------------- #
    def render(self, notes, seconds: float) -> np.ndarray:
        """Render `notes` = [(midi_note, velocity, start_s, duration_s), ...] -> (channels, samples)."""
        self.plugin.clear_midi()
        for note, vel, start, dur in notes:
            self.plugin.add_midi_note(int(note), int(vel), float(start), float(dur), beats=False)
        self.engine.load_graph([(self.plugin, [])])
        self.engine.render(float(seconds))
        return np.asarray(self.engine.get_audio(), dtype=np.float32)


def write_wav(path: str | Path, audio: np.ndarray, sample_rate: int) -> None:
    import soundfile as sf

    sf.write(str(path), audio.T if audio.ndim == 2 else audio, sample_rate)


DEFAULT_PARAMS = ["Main Vol", "A Enable", "A Level", "A Octave", "Filter 1 On", "Filter 1 Type", "Filter 1 Freq",
                  "Env 1 Attack", "Env 1 Release", "LFO 1 Rate"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("preset", help=".SerumPreset file to load")
    ap.add_argument("--params", help="comma-separated parameter names to print", default=None)
    ap.add_argument("--all", action="store_true", help="print every parameter")
    ap.add_argument("--render", metavar="OUT_WAV")
    ap.add_argument("--note", type=int, default=48)
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--sample-rate", type=int, default=44100)
    args = ap.parse_args(argv)

    host = Serum2Host(sample_rate=args.sample_rate).load()
    ok = host.load_preset(args.preset)
    print(f"preset: {args.preset}  loaded={ok}  params={len(host.names)}")
    names = host.names if args.all else [n.strip() for n in args.params.split(",")] if args.params else DEFAULT_PARAMS
    for name in names:
        try:
            print(f"  {name:20s} value={host.value(name):.6f}  text={host.text(name)!r}")
        except KeyError as exc:
            print(f"  {name:20s} {exc}")

    if args.render:
        audio = host.render([(args.note, 100, 0.0, args.seconds * 0.75)], args.seconds)
        write_wav(args.render, audio, args.sample_rate)
        rms = float(np.sqrt(np.mean(audio ** 2)))
        print(f"  rendered {audio.shape} -> {args.render}  peak={np.abs(audio).max():.4f} rms={rms:.5f}")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)  # DawDreamer-hosted plugins crash at normal interpreter exit
