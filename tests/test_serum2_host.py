"""Plugin-free tests for the Serum 2 state builder in tools/serum2_host.py.

The plugin itself is exercised by running the tool; here we check the
container codec and the preset-to-state split that Serum 2 requires (a
container must carry exactly its own key set, or Serum keeps its old state).
"""

import hashlib
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

try:
    import cbor2  # noqa: F401
    import zstandard  # noqa: F401
except ImportError:  # pragma: no cover - optional Serum 2 dependencies
    cbor2 = zstandard = None

import serum2_host as s2  # noqa: E402
import vital_host as vh  # noqa: E402

PROCESSOR = {"component": "processor", "version": 9.0, "mpeEnabled": False,
             "Env0": {"plainParams": "default"}, "Oscillator0": {"plainParams": "default"},
             "FXRack0": {"plainParams": "default"}}
CONTROLLER = {"component": "controller", "version": 9.0, "presetName": " - Init - ", "presetAuthor": "",
              "presetDescription": "", "Osc": {"tab": 0}, "SerumGUI": {"zoom": 1.0}}
PRESET_META = {"fileType": "SerumPreset", "presetName": "Wobble", "presetAuthor": "me", "presetDescription": "d",
               "version": 5.0}
PRESET = {"fileType": "SerumPreset", "version": 5.0, "mpeEnabled": True, "presetName": "Wobble",
          "Env0": {"plainParams": {"kParamAttack": 0.5}}, "Oscillator0": {"plainParams": {"kParamOctave": 1.0}},
          "FXRack0": {"plainParams": "default"}, "Osc": {"tab": 2}, "SerumGUI": {"zoom": 2.0},
          "Filter": {"gui": 1}}  # "Filter" exists on neither side of the plugin state


def fake_state(component: bytes, controller: bytes) -> bytes:
    xml = (b'<?xml version="1.0" encoding="UTF-8"?> <VST3PluginState><IComponent>'
           + vh.encode_juce_base64(component).encode() + b"</IComponent><IEditController>"
           + vh.encode_juce_base64(controller).encode() + b"</IEditController></VST3PluginState>")
    body = xml + b"\x00"
    return b"VC2!" + struct.pack("<I", len(body)) + body


@unittest.skipIf(cbor2 is None, "needs zstandard + cbor2")
class XferContainer(unittest.TestCase):
    def test_roundtrip_and_hash(self):
        blob = s2.build_xfer({"component": "processor"}, PROCESSOR)
        self.assertTrue(blob.startswith(s2.MAGIC))
        meta, doc = s2.parse_xfer(blob)
        self.assertEqual(doc, PROCESSOR)
        n = struct.unpack_from("<Q", blob, 9)[0]
        payload = blob[17 + n + 8:]
        self.assertEqual(meta["hash"], hashlib.md5(payload).hexdigest())
        self.assertEqual(struct.unpack_from("<II", blob, 17 + n)[1], s2.ENCODING_ZSTD)

    def test_rejects_other_containers(self):
        with self.assertRaises(ValueError):
            s2.parse_xfer(b"VstW" + bytes(32))


@unittest.skipIf(cbor2 is None, "needs zstandard + cbor2")
class StateFromPreset(unittest.TestCase):
    def setUp(self):
        self.template = fake_state(s2.build_xfer({"component": "processor"}, PROCESSOR),
                                   s2.build_xfer({"component": "controller"}, CONTROLLER))

    def test_each_container_keeps_its_own_key_set(self):
        state = s2.state_from_preset(self.template, PRESET, PRESET_META)
        _, comp = s2.parse_xfer(s2.get_blob(state, "IComponent"))
        _, ctrl = s2.parse_xfer(s2.get_blob(state, "IEditController"))
        self.assertEqual(set(comp), set(PROCESSOR))
        self.assertEqual(set(ctrl), set(CONTROLLER))
        # values come from the preset where it has the key ...
        self.assertEqual(comp["Env0"], {"plainParams": {"kParamAttack": 0.5}})
        self.assertEqual(comp["mpeEnabled"], True)
        self.assertEqual(ctrl["Osc"], {"tab": 2})
        # ... and stay at the template's value where it does not
        self.assertEqual(comp["component"], "processor")
        self.assertEqual(ctrl["component"], "controller")

    def test_controller_gets_the_preset_identity(self):
        state = s2.state_from_preset(self.template, PRESET, PRESET_META)
        meta, ctrl = s2.parse_xfer(s2.get_blob(state, "IEditController"))
        self.assertEqual(ctrl["presetName"], "Wobble")
        self.assertEqual(ctrl["presetAuthor"], "me")
        self.assertEqual(meta["presetName"], "Wobble")

    def test_accepts_raw_preset_bytes_and_fixes_xml_length(self):
        raw = s2.build_xfer(PRESET_META, PRESET)
        state = s2.state_from_preset(self.template, raw)
        self.assertEqual(state[:4], b"VC2!")
        self.assertEqual(struct.unpack("<I", state[4:8])[0], len(state) - 9)
        self.assertTrue(state.endswith(b"</VST3PluginState>\x00"))
        _, comp = s2.parse_xfer(s2.get_blob(state, "IComponent"))
        self.assertEqual(comp["Oscillator0"], {"plainParams": {"kParamOctave": 1.0}})


if __name__ == "__main__":
    unittest.main()
