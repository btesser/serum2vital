"""Headless Serum (VST2) host built on DawDreamer, for ground-truth read-back.

Loads Serum_x64.dll, loads an .fxp, and exposes Serum's parameters by their
plugin names (which contain spaces: "LFO1 Rate", "Fil Type", "A Vol") with
raw values, display text, and setters.  Rendering goes through DawDreamer's
graph renderer.

IMPORTANT: the Python process segfaults at interpreter exit once a plugin has
been loaded, so every script using this module must end with
``sys.stdout.flush(); os._exit(0)`` and callers should run it in a subprocess.

    python tools/serum_host.py preset.fxp [--params "Fil Type,WarpOscA,LFO1 Rate"]
                                          [--render out.wav --note 48 --seconds 2]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

import os

SERUM_VST2 = os.environ.get("SERUM_VST2", "C:/Program Files/VstPlugins/Serum_x64.dll")
SETTLE_SECONDS = 0.5   # silent render after a preset load (see SerumHost.load_preset)


class SerumHost:
    """DawDreamer wrapper around the Serum VST2 plugin."""

    def __init__(self, plugin_path: str = SERUM_VST2, sample_rate: int = 44100, block_size: int = 512):
        self.plugin_path = plugin_path
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.engine = None
        self.plugin = None
        self._index: dict[str, int] = {}

    def load(self) -> "SerumHost":
        import dawdreamer as daw

        self.engine = daw.RenderEngine(self.sample_rate, self.block_size)
        self.plugin = self.engine.make_plugin_processor("serum", self.plugin_path)
        self._index = {
            self.plugin.get_parameter_name(i): i for i in range(self.plugin.get_plugin_parameter_size())
        }
        return self

    # -- presets ----------------------------------------------------------- #
    def load_preset(self, fxp: str | Path, settle_seconds: float = SETTLE_SECONDS) -> bool:
        """Load an .fxp and let the plugin settle before anything is rendered.

        Serum smooths its parameters across a preset change, so a render made
        straight after loading carries the previous preset's levels gliding
        into the new ones for about half a second (measured: a preset whose
        note sits at -15 dB starts at -2 dB after another preset, -24 dB
        after Init; a second load of the same file does not help, half a
        second of silent rendering does).  Every reference render used to
        carry that onset; `settle` clears it.
        """
        ok = bool(self.plugin.load_preset(str(fxp)))
        if ok and settle_seconds > 0:
            self.settle(settle_seconds)
        return ok

    def settle(self, seconds: float = SETTLE_SECONDS) -> None:
        """Render `seconds` of silence so parameter smoothing reaches the loaded values."""
        self.plugin.clear_midi()
        self.engine.load_graph([(self.plugin, [])])
        self.engine.render(float(seconds))

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
        raise KeyError(f"{name!r} is not a Serum parameter (close: {close})")

    def value(self, name: str) -> float:
        return float(self.plugin.get_parameter(self.index(name)))

    def text(self, name: str) -> str:
        return str(self.plugin.get_parameter_text(self.index(name)))

    def set(self, name: str, v: float) -> None:
        self.plugin.set_parameter(self.index(name), float(v))

    def dump(self) -> dict[str, tuple[float, str]]:
        """{name: (raw value, display text)} for every parameter."""
        return {n: (self.value(n), self.text(n)) for n in self._index}

    # -- audio ------------------------------------------------------------- #
    def render(self, notes, seconds: float) -> np.ndarray:
        """Render `notes` = [(midi_note, velocity, start_s, duration_s), ...].

        Returns a float32 array of shape (channels, samples).
        """
        self.plugin.clear_midi()
        for note, vel, start, dur in notes:
            self.plugin.add_midi_note(int(note), int(vel), float(start), float(dur), beats=False)
        self.engine.load_graph([(self.plugin, [])])
        self.engine.render(float(seconds))
        return np.asarray(self.engine.get_audio(), dtype=np.float32)


def write_wav(path: str | Path, audio: np.ndarray, sample_rate: int) -> None:
    import soundfile as sf

    sf.write(str(path), audio.T if audio.ndim == 2 else audio, sample_rate)


DEFAULT_PARAMS = ["A Vol", "Fil Type", "Fil Cutoff", "LFO1 Rate", "Env1 Atk", "Master Vol"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("preset", help=".fxp file to load")
    ap.add_argument("--params", help="comma-separated parameter names to print", default=None)
    ap.add_argument("--all", action="store_true", help="print every parameter")
    ap.add_argument("--render", metavar="OUT_WAV")
    ap.add_argument("--note", type=int, default=60)
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--sample-rate", type=int, default=44100)
    args = ap.parse_args(argv)

    host = SerumHost(sample_rate=args.sample_rate).load()
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
