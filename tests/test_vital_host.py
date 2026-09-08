"""Plugin-free tests for the Vital state codec in tools/vital_host.py."""

import json
import os
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import vital_host as vh  # noqa: E402


def fake_raw_state(preset: dict, trailer: bytes = bytes(17) + b"JUCEPrivateData") -> bytes:
    payload = vh._wrap_json(json.dumps(preset, separators=(",", ":")).encode(), trailer)
    xml = (b'<?xml version="1.0" encoding="UTF-8"?> <VST3PluginState><IComponent>'
           + vh.encode_juce_base64(payload).encode() + b"</IComponent></VST3PluginState>")
    body = xml + b"\x00"
    return b"VC2!" + struct.pack("<I", len(body) + 8 - 9 + 1) + body


class JuceBase64(unittest.TestCase):
    def test_roundtrip_many_sizes(self):
        for size in list(range(0, 40)) + [1000, 4097]:
            data = os.urandom(size)
            self.assertEqual(vh.decode_juce_base64(vh.encode_juce_base64(data)), data, size)

    def test_size_prefix_and_char_count(self):
        enc = vh.encode_juce_base64(b"abc")
        self.assertTrue(enc.startswith("3."))
        self.assertEqual(len(enc), 2 + 4)  # 24 bits -> 4 chars

    def test_lsb_first_packing(self):
        # byte 0x01 -> first 6-bit char has value 1 -> 'A' (alphabet index 1)
        self.assertEqual(vh.encode_juce_base64(b"\x01"), "1.A.")


class ChunkWrapper(unittest.TestCase):
    def test_wrap_and_split(self):
        js = b'{"a":1}'
        blob = vh._wrap_json(js, b"tail")
        head, body, tail = vh.split_payload(blob)
        self.assertEqual(blob[:4], b"VstW")
        self.assertEqual(len(head), 176)
        self.assertEqual(body, js)
        self.assertEqual(tail, b"tail")
        self.assertEqual(struct.unpack(">I", blob[172:176])[0], len(js) + 4)
        self.assertEqual(struct.unpack(">I", blob[20:24])[0], len(blob) - 16 - 8)

    def test_build_state_updates_length_header_and_roundtrips(self):
        template = fake_raw_state({"preset_name": "", "settings": {}})
        big = {"preset_name": "x" * 500, "settings": {"filter_1_cutoff": 30.0}}
        state = vh.build_state(template, big)
        self.assertEqual(state[:4], b"VC2!")
        self.assertEqual(struct.unpack("<I", state[4:8])[0], len(state) - 9)
        self.assertEqual(vh.extract_preset(state), big)
        self.assertTrue(state.endswith(b"</VST3PluginState>\x00"))


if __name__ == "__main__":
    unittest.main()
