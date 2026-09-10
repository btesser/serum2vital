"""Serum wavetables, noise samples and LFO curves -> Vital JSON fragments.

Serum wavetables are plain 32-bit-float mono WAV files whose ``clm `` chunk
declares the frame size (almost always 2048 samples), and Vital's "Wave Source"
component stores exactly the same thing: 2048 float32 samples per keyframe,
base64 encoded.  So the wavetable path is a straight copy rather than a
resynthesis -- only the number of keyframes is reduced, because a 256-frame
Serum table would otherwise add ~2.8 MB of base64 to every preset.

Serum LFO curves and Vital LFO curves are both point lists with a per-segment
tension, so those map across directly too; the only real work is Serum's
screen-space y axis (0 at the top), which Vital's LFO JSON shares (measured:
a curve held at 0 drives a level modulation to its maximum).
"""

from __future__ import annotations

import base64
import math
import struct
from dataclasses import dataclass
from pathlib import Path

VITAL_FRAME_SIZE = 2048
VITAL_MAX_POSITION = 255
DEFAULT_FRAME_LIMIT = 64

# Serum's own y axis for LFO curves is 0..1 top-to-bottom; the tension value is
# 0..1 with 0.5 meaning "straight line".  Vital uses a signed "power" where 0 is
# straight; this scale puts Serum's most extreme curve near Vital's usable limit
# without clipping (Vital accepts roughly +-20).
LFO_POWER_SCALE = 12.0


class WavetableError(Exception):
    """Raised when a Serum wavetable/sample cannot be read."""


@dataclass
class SerumWavetable:
    name: str
    frames: list[list[float]]
    frame_size: int


def _read_wav(path: Path) -> tuple[list[float], int, int, int]:
    """Return (interleaved samples as float, channels, sample_rate, frame_size).

    Handles the float32 and PCM WAV flavours Serum ships, and reports the frame
    size declared in the ``clm `` chunk when present.
    """
    data = path.read_bytes()
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise WavetableError(f"{path.name}: not a RIFF/WAVE file")

    fmt = None
    audio = b""
    frame_size = 0
    offset = 12
    while offset + 8 <= len(data):
        chunk_id = data[offset : offset + 4]
        size = struct.unpack_from("<I", data, offset + 4)[0]
        body = data[offset + 8 : offset + 8 + size]
        if chunk_id == b"fmt ":
            fmt = struct.unpack_from("<HHIIHH", body, 0)
        elif chunk_id == b"data":
            audio = body
        elif chunk_id == b"clm ":
            text = body.decode("latin-1", "replace")
            if text.startswith("<!>"):
                head = text[3:].split()
                if head and head[0].isdigit():
                    frame_size = int(head[0])
        offset += 8 + size + (size & 1)

    if fmt is None or not audio:
        raise WavetableError(f"{path.name}: missing fmt/data chunk")

    audio_format, channels, sample_rate, _, _, bits = fmt
    if audio_format == 3 and bits == 32:
        count = len(audio) // 4
        samples = list(struct.unpack_from("<%df" % count, audio, 0))
    elif audio_format == 1 and bits == 16:
        count = len(audio) // 2
        samples = [v / 32768.0 for v in struct.unpack_from("<%dh" % count, audio, 0)]
    elif audio_format == 1 and bits == 24:
        count = len(audio) // 3
        samples = []
        for i in range(count):
            chunk = audio[i * 3 : i * 3 + 3]
            value = int.from_bytes(chunk, "little", signed=True)
            samples.append(value / 8388608.0)
    elif audio_format == 1 and bits == 32:
        count = len(audio) // 4
        samples = [v / 2147483648.0 for v in struct.unpack_from("<%di" % count, audio, 0)]
    else:
        raise WavetableError(f"{path.name}: unsupported format {audio_format}/{bits}-bit")

    return samples, max(channels, 1), sample_rate, frame_size


def load_serum_wavetable(path: str | Path) -> SerumWavetable:
    """Split a Serum wavetable WAV into single-cycle frames."""
    path = Path(path)
    samples, channels, _sample_rate, declared = _read_wav(path)
    if channels > 1:
        samples = samples[::channels]

    frame_size = declared or VITAL_FRAME_SIZE
    if frame_size <= 0 or len(samples) < frame_size:
        # Anything shorter than one cycle is treated as a single frame.
        frame_size = max(1, len(samples))

    frames = [
        samples[i : i + frame_size]
        for i in range(0, len(samples) - frame_size + 1, frame_size)
    ]
    if not frames:
        raise WavetableError(f"{path.name}: no complete frames")
    return SerumWavetable(name=path.stem, frames=frames, frame_size=frame_size)


def _resample_frame(frame: list[float], size: int = VITAL_FRAME_SIZE) -> list[float]:
    """Linearly resample one cycle to Vital's 2048-sample frame."""
    if len(frame) == size:
        return frame
    source_len = len(frame)
    out = []
    for i in range(size):
        position = i * source_len / size
        low = int(position)
        frac = position - low
        a = frame[low % source_len]
        b = frame[(low + 1) % source_len]
        out.append(a + (b - a) * frac)
    return out


def _encode_frame(frame: list[float]) -> str:
    packed = struct.pack("<%df" % VITAL_FRAME_SIZE, *_resample_frame(frame))
    return base64.b64encode(packed).decode("ascii")


def wavetable_to_vital(
    table: SerumWavetable,
    name: str | None = None,
    max_keyframes: int = DEFAULT_FRAME_LIMIT,
) -> dict:
    """Build the Vital wavetable object for one oscillator slot."""
    total = len(table.frames)
    if total <= max_keyframes:
        indices = list(range(total))
    else:
        indices = sorted({round(i * (total - 1) / (max_keyframes - 1)) for i in range(max_keyframes)})

    keyframes = []
    for slot, frame_index in enumerate(indices):
        if len(indices) == 1:
            position = 0
        else:
            position = round(slot * VITAL_MAX_POSITION / (len(indices) - 1))
        keyframes.append(
            {"position": position, "wave_data": _encode_frame(table.frames[frame_index])}
        )

    return {
        "author": "",
        "full_normalize": False,
        "groups": [
            {
                "components": [
                    {
                        # 0 == interpolate in the time domain, matching how Serum
                        # crossfades between adjacent wavetable frames.
                        "interpolation": 0,
                        "interpolation_style": 1,  # kLinear
                        "keyframes": keyframes,
                        "type": "Wave Source",
                    }
                ]
            }
        ],
        "name": name or table.name,
        "remove_all_dc": False,
        "version": "1.5.5",
    }


# Serum's basic shapes live inside the plugin rather than in Tables/, but a
# preset still refers to them by a file-like name (e.g. "User/Triangle.wav"), so
# they have to be synthesised instead of loaded.
def _builtin_shape(kind: str) -> list[float] | None:
    n = VITAL_FRAME_SIZE
    two_pi = 2.0 * math.pi
    if kind in ("sin", "sine"):
        return [math.sin(two_pi * i / n) for i in range(n)]
    if kind in ("tri", "triangle"):
        return [4.0 * abs((i / n + 0.25) % 1.0 - 0.5) - 1.0 for i in range(n)]
    if kind in ("square", "sqr"):
        return [1.0 if i < n // 2 else -1.0 for i in range(n)]
    if kind in ("saw", "sawtooth", "saw up"):
        return [2.0 * (i / n) - 1.0 for i in range(n)]
    if kind in ("saw down", "ramp down"):
        return [1.0 - 2.0 * (i / n) for i in range(n)]
    if kind in ("pulse", "pulse width"):
        return [1.0 if i < n // 4 else -1.0 for i in range(n)]
    if kind in ("roundrect", "round rect", "rounded square"):
        # Serum's RoundRect sub shape: a square with rounded corners.
        return [math.tanh(4.0 * math.sin(two_pi * i / n)) / math.tanh(4.0) for i in range(n)]
    return None


def builtin_wavetable(reference: str) -> dict | None:
    """Build a wavetable for one of Serum's internal basic shapes, if `reference`
    names one (e.g. "User/Triangle.wav")."""
    stem = Path(reference.replace("\\", "/")).stem.strip().lower()
    frame = _builtin_shape(stem)
    if frame is None:
        return None
    return {
        "author": "",
        "full_normalize": False,
        "groups": [
            {
                "components": [
                    {
                        "interpolation": 0,
                        "interpolation_style": 0,
                        "keyframes": [{"position": 0, "wave_data": _encode_frame(frame)}],
                        "type": "Wave Source",
                    }
                ]
            }
        ],
        "name": Path(reference).stem,
        "remove_all_dc": False,
        "version": "1.5.5",
    }


def default_wavetable(name: str = "Init") -> dict:
    """A single-frame sine wavetable, used when the Serum table can't be found."""
    frame = [math.sin(2.0 * math.pi * i / VITAL_FRAME_SIZE) for i in range(VITAL_FRAME_SIZE)]
    return {
        "author": "",
        "full_normalize": False,
        "groups": [
            {
                "components": [
                    {
                        "interpolation": 0,
                        "interpolation_style": 0,
                        "keyframes": [{"position": 0, "wave_data": _encode_frame(frame)}],
                        "type": "Wave Source",
                    }
                ]
            }
        ],
        "name": name,
        "remove_all_dc": False,
        "version": "1.5.5",
    }


def sample_to_vital(path: str | Path, name: str | None = None, max_seconds: float = 4.0) -> dict | None:
    """Convert a Serum noise/sample WAV into Vital's `sample` object (16-bit PCM)."""
    path = Path(path)
    try:
        samples, channels, sample_rate, _ = _read_wav(path)
    except WavetableError:
        return None

    left = samples[::channels] if channels > 1 else samples
    right = samples[1::channels] if channels > 1 else None

    limit = int(sample_rate * max_seconds)
    left = left[:limit]
    if right is not None:
        right = right[:limit]

    def encode(values: list[float]) -> str:
        pcm = struct.pack(
            "<%dh" % len(values),
            *[max(-32768, min(32767, int(round(v * 32767.0)))) for v in values],
        )
        return base64.b64encode(pcm).decode("ascii")

    data = {
        "name": name or path.stem,
        "length": len(left),
        "sample_rate": sample_rate,
        "samples": encode(left),
    }
    if right is not None and len(right) == len(left):
        data["samples_stereo"] = encode(right)
    return data


def lfo_to_vital(shape, name: str = "Serum", invert_y: bool = True, close_loop: bool = False,
                 power_sign: float = 1.0) -> dict:
    """Convert a :class:`serum1.LfoShape` into Vital's LFO curve object.

    Vital stores ``points`` as a flat [x0, y0, x1, y1, ...] list with y = 0 at
    the top (measured: a curve held at 0 drives a level modulation to its
    maximum), and one ``power`` per point (0 = straight segment).

    ``invert_y`` flips the stored y for a format whose axis points the other
    way; ``close_loop`` replaces the final point's value with the first point's,
    for an editor that ties the two ends together.  For Serum 1 both were
    settled by rendering LFO-to-level routings through the plugin: Serum's y
    has the same orientation as Vital's (no inversion) and the loop closes, so
    the default shape (0,0)-(0.5,1)-(1,1) plays as a triangle.
    """
    xs, ys, curves = list(shape.xs), list(shape.ys), list(shape.curves)
    if close_loop and len(ys) >= 3:
        closed = ys[:-1] + [ys[0]]
        # A flat curve (all points equal) makes Vital's voice collapse even when
        # the LFO is not routed anywhere, so never produce one.
        if max(closed) - min(closed) > 1e-3:
            ys = closed
    if len(xs) < 2:
        # Fall back to Vital's own default triangle.
        return {
            "name": name,
            "num_points": 3,
            "points": [0.0, 1.0, 0.5, 0.0, 1.0, 1.0],
            "powers": [0.0, 0.0, 0.0],
            "smooth": False,
        }

    points: list[float] = []
    for x, y in zip(xs, ys):
        points.append(max(0.0, min(1.0, x)))
        points.append(max(0.0, min(1.0, 1.0 - y if invert_y else y)))

    powers = []
    for i in range(len(xs)):
        curve = curves[i] if i < len(curves) else 0.5
        powers.append(max(-20.0, min(20.0, power_sign * (curve - 0.5) * 2.0 * LFO_POWER_SCALE)))

    return {
        "name": name,
        "num_points": len(xs),
        "points": points,
        "powers": powers,
        "smooth": False,
    }


def read_shp(path: str | Path):
    """Read a standalone Serum ``.shp`` LFO shape file.

    Layout: 64 float64 tension values, 64 float64 x positions (0..388), 64
    float64 y positions (0..240, 0 at the top), 64 unused, then a uint32 point
    count.  Returns a :class:`serum1.LfoShape`.
    """
    from .serum1 import LfoShape

    blob = Path(path).read_bytes()
    if len(blob) < 2048 + 4:
        raise WavetableError(f"{Path(path).name}: too short for a .shp file")

    values = struct.unpack_from("<256d", blob, 0)
    count = struct.unpack_from("<I", blob, 2048)[0]

    curves = list(values[0:64])
    xs = [v / 388.0 for v in values[64:128]]
    ys = [v / 240.0 for v in values[128:192]]

    # The stored count is the segment count for some factory shapes and the point
    # count for others, so trust the x array: the shape ends when it reaches the
    # right edge.
    end = len(xs)
    for i, x in enumerate(xs):
        if x >= 1.0 - 1e-9:
            end = i + 1
            break
    end = max(end, min(count, len(xs)))

    return LfoShape(xs=xs[:end], ys=ys[:end], curves=curves[: max(end - 1, 1)])
