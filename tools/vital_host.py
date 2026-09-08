"""Headless Vital (VST3) host built on pedalboard, for validating converted presets.

Vital's `raw_state` is a JUCE VST3 state XML whose <IComponent> payload is a
JUCE MemoryBlock base64 string ("<decimal size>." + chars, alphabet
".A-Za-z0-9+/", 6-bit chars packed LSB-first).  Decoded, it is a VstW/CcnK
chunk wrapper around the plain .vital JSON (JSON begins at byte offset 176).
This module decodes/encodes that wrapper so a .vital dict can be injected into
the running plugin, read back through pedalboard's parameter list, and rendered.

    python tools/vital_host.py preset.vital [--render out.wav --note 60 --seconds 2]
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

import numpy as np

import os

VITAL_VST3 = os.environ.get("VITAL_VST3", "C:/Program Files/Common Files/VST3/Vital.vst3")

_ALPHABET = ".ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_CHAR_TO_VAL = {c: i for i, c in enumerate(_ALPHABET)}
_JSON_OFFSET = 176
_COMPONENT_RE = re.compile(rb"<IComponent>(.*?)</IComponent>", re.S)
_XML_BINARY_MAGIC = b"VC2!"  # JUCE AudioProcessor::copyXmlToBinary magic


# --------------------------------------------------------------------------- #
# JUCE MemoryBlock base64
# --------------------------------------------------------------------------- #
def decode_juce_base64(s: str | bytes) -> bytes:
    """Decode JUCE MemoryBlock::toBase64Encoding output to bytes."""
    if isinstance(s, bytes):
        s = s.decode("ascii")
    size_str, _, data = s.partition(".")
    size = int(size_str)
    out = bytearray(size)
    for i in range(size):
        byte = 0
        for b in range(8):
            k = i * 8 + b
            val = _CHAR_TO_VAL[data[k // 6]]
            if (val >> (k % 6)) & 1:
                byte |= 1 << b
        out[i] = byte
    return bytes(out)


def encode_juce_base64(b: bytes) -> str:
    """Inverse of decode_juce_base64 (JUCE MemoryBlock::toBase64Encoding)."""
    nbits = len(b) * 8
    nchars = (nbits + 5) // 6
    vals = [0] * nchars
    for i, byte in enumerate(b):
        for bit in range(8):
            if (byte >> bit) & 1:
                k = i * 8 + bit
                vals[k // 6] |= 1 << (k % 6)
    return f"{len(b)}." + "".join(_ALPHABET[v] for v in vals)


# --------------------------------------------------------------------------- #
# VstW / CcnK wrapper around the .vital JSON
# --------------------------------------------------------------------------- #
def _component_payload(raw_state: bytes) -> bytes:
    m = _COMPONENT_RE.search(raw_state)
    if not m:
        raise ValueError("no <IComponent> element in raw_state")
    return decode_juce_base64(m.group(1))


def split_payload(blob: bytes) -> tuple[bytes, bytes, bytes]:
    """Split a decoded IComponent blob into (header, json_bytes, trailer).

    header  = 176 bytes (VstW + CcnK/FBCh + length field)
    trailer = whatever JUCE appended after the JSON (zeros + "JUCEPrivateData")
    """
    if blob[:4] != b"VstW":
        raise ValueError(f"unexpected chunk header {blob[:4]!r}")
    text = blob[_JSON_OFFSET:].decode("utf-8", errors="surrogateescape")
    _, end = json.JSONDecoder().raw_decode(text)
    end_bytes = _JSON_OFFSET + len(text[:end].encode("utf-8", errors="surrogateescape"))
    return blob[:_JSON_OFFSET], blob[_JSON_OFFSET:end_bytes], blob[end_bytes:]


def extract_preset(raw_state: bytes) -> dict:
    """Return the .vital JSON dict embedded in a pedalboard raw_state blob."""
    _, json_bytes, _ = split_payload(_component_payload(raw_state))
    return json.loads(json_bytes.decode("utf-8"))


def _wrap_json(json_bytes: bytes, trailer: bytes = b"") -> bytes:
    """Build the VstW/CcnK/FBCh chunk around raw .vital JSON bytes (+ trailer)."""
    body = bytearray()
    body += b"CcnK" + struct.pack(">I", 0)        # size placeholder, filled below
    body += b"FBCh" + struct.pack(">I", 2)        # chunk format version
    body += b"Vita" + bytes([0, 1, 5, 5])         # plugin id + version 1.5.5
    body += struct.pack(">I", 0)                  # num programs
    body += bytes(128)                            # program name
    body += struct.pack(">I", len(json_bytes) + len(trailer))
    body += json_bytes + trailer
    struct.pack_into(">I", body, 4, len(body) - 8)
    head = b"VstW" + struct.pack(">III", 8, 1, 0)
    return head + bytes(body)


def build_state(raw_state_template: bytes, preset: dict) -> bytes:
    """Return a raw_state with the IComponent JSON replaced by `preset`.

    The template's JUCE private-data trailer is preserved; everything outside
    the <IComponent> element is kept verbatim.
    """
    _, _, trailer = split_payload(_component_payload(raw_state_template))
    json_bytes = json.dumps(preset, separators=(",", ":")).encode("utf-8")
    encoded = encode_juce_base64(_wrap_json(json_bytes, trailer)).encode("ascii")
    new_state, n = _COMPONENT_RE.subn(
        lambda m: b"<IComponent>" + encoded + b"</IComponent>", raw_state_template, count=1
    )
    if n != 1:
        raise ValueError("no <IComponent> element in raw_state template")
    # pedalboard hands us JUCE's copyXmlToBinary() output: "VC2!" magic, a
    # little-endian uint32 XML length (= total - 9), the XML, and a NUL.  JUCE's
    # getXmlFromBinary() truncates to that stored length, so it must be updated
    # or any state larger than the template is silently cut off (and rejected).
    if new_state[:4] == _XML_BINARY_MAGIC:
        new_state = bytearray(new_state)
        struct.pack_into("<I", new_state, 4, len(new_state) - 9)
        new_state = bytes(new_state)
    return new_state


# --------------------------------------------------------------------------- #
# Host
# --------------------------------------------------------------------------- #
# pedalboard keys parameters by Vital's *display* names, which differ from the
# .vital JSON keys for ~1/3 of them.  Applied in order until a name matches.
_JSON_TO_DISPLAY = [
    (r"^env_(\d+)_", r"envelope_\1_"),
    (r"^osc_(\d+)_", r"oscillator_\1_"),
    (r"^(oscillator_\d+_)spectral_morph_", r"\1frequency_morph_"),
    (r"^(oscillator_\d+_)random_phase$", r"\1phase_randomization"),
    (r"^(oscillator_\d+_)frame_spread$", r"\1unison_frame_spread"),
    (r"^(oscillator_\d+_)unison_blend$", r"\1blend"),
    (r"^macro_control_(\d+)$", r"macro_\1"),
    (r"^random_(\d+)_", r"random_lfo_\1_"),
    (r"^(lfo_\d+_|random_lfo_\d+_)keytrack_(transpose|tune)$", r"\1\2"),
    (r"^(lfo_\d+_)delay_time$", r"\1delay"),
    (r"^(lfo_\d+_)fade_time$", r"\1fade_in"),
    (r"_on$", "_switch"),
    (r"_dry_wet$", "_mix"),
    (r"_keytrack$", "_key_track"),
    (r"_blend_transpose$", "_comb_blend_offset"),
    (r"^chorus_(cutoff|spread)$", r"chorus_filter_\1"),
    (r"^compressor_(band|low|high)_", r"\1_"),
    (r"^delay_aux_(frequency|sync|tempo)$", r"delay_\1_2"),
    (r"^reverb_(high|low)_shelf_", r"reverb_\1_"),
]


class VitalHost:
    """pedalboard wrapper around the Vital VST3 plugin."""

    def __init__(self, plugin_path: str = VITAL_VST3):
        self.plugin_path = plugin_path
        self.plugin = None
        self._template = None

    def load(self) -> "VitalHost":
        from pedalboard import load_plugin

        self.plugin = load_plugin(self.plugin_path)
        self._template = bytes(self.plugin.raw_state)
        return self

    # -- state ------------------------------------------------------------- #
    def set_preset(self, preset: dict) -> None:
        self.plugin.raw_state = build_state(self._template, preset)

    def get_preset(self) -> dict:
        return extract_preset(bytes(self.plugin.raw_state))

    def load_file(self, path: str | Path) -> dict:
        preset = json.loads(Path(path).read_text(encoding="utf-8"))
        self.set_preset(preset)
        return preset

    # -- parameters -------------------------------------------------------- #
    @property
    def names(self) -> list[str]:
        return list(self.plugin.parameters.keys())

    def resolve(self, name: str) -> str:
        """Map a .vital JSON settings key (or pedalboard name) to a pedalboard name."""
        params = self.plugin.parameters
        if name in params:
            return name
        cand = name
        for pattern, repl in _JSON_TO_DISPLAY:
            cand = re.sub(pattern, repl, cand)
            if cand in params:
                return cand
        import difflib

        close = difflib.get_close_matches(name, params.keys(), n=3)
        raise KeyError(f"{name!r} is not a Vital parameter (close: {close})")

    def param(self, name: str) -> float:
        """Normalised (0..1) raw value of a parameter as reported by the plugin."""
        return float(self.plugin.parameters[self.resolve(name)].raw_value)

    def param_text(self, name: str) -> str:
        """pedalboard's user-facing value (already unit-converted where it can)."""
        p = self.plugin.parameters[self.resolve(name)]
        return str(getattr(self.plugin, p.python_name))

    # -- audio ------------------------------------------------------------- #
    def render(self, notes, seconds: float, sample_rate: int = 44100) -> np.ndarray:
        """Render `notes` = [(midi_note, velocity, start_s, duration_s), ...].

        Returns a float32 array of shape (channels, samples).
        """
        import mido

        events = []
        for note, vel, start, dur in notes:
            events.append((start, mido.Message("note_on", note=int(note), velocity=int(vel), time=start)))
            events.append((start + dur, mido.Message("note_off", note=int(note), velocity=0, time=start + dur)))
        events.sort(key=lambda e: e[0])
        messages = [m for _, m in events]
        audio = self.plugin(messages, duration=seconds, sample_rate=sample_rate)
        return np.asarray(audio, dtype=np.float32)


def write_wav(path: str | Path, audio: np.ndarray, sample_rate: int) -> None:
    import soundfile as sf

    sf.write(str(path), audio.T if audio.ndim == 2 else audio, sample_rate)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
REPORT_PARAMS = ["filter_1_cutoff", "osc_1_level", "lfo_1_sync", "lfo_1_frequency", "env_1_attack"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("preset", help=".vital file to inject")
    ap.add_argument("--render", metavar="OUT_WAV")
    ap.add_argument("--note", type=int, default=60)
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--sample-rate", type=int, default=44100)
    args = ap.parse_args(argv)

    host = VitalHost().load()
    preset = host.load_file(args.preset)
    back = host.get_preset()
    settings = preset.get("settings", {})
    print(f"preset: {preset.get('preset_name')!r}")
    print(f"  state accepted by Vital: {back.get('preset_name') == preset.get('preset_name')}")
    for key in REPORT_PARAMS:
        print(f"  {key:16s} json={settings.get(key)!s:>10}  readback_json={back['settings'].get(key)!s:>10}"
              f"  raw={host.param(key):.6g}  text={host.param_text(key)!r}")
    mods = [m for m in back.get("settings", {}).get("modulations", []) if m.get("source")]
    print(f"  modulations with source (read-back): {len(mods)}")
    for m in mods[:8]:
        print(f"    {m.get('source')} -> {m.get('destination')}")

    if args.render:
        audio = host.render([(args.note, 100, 0.0, args.seconds * 0.75)], args.seconds, args.sample_rate)
        write_wav(args.render, audio, args.sample_rate)
        rms = float(np.sqrt(np.mean(audio ** 2)))
        print(f"  rendered {audio.shape} -> {args.render}  peak={np.abs(audio).max():.4f} rms={rms:.5f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
