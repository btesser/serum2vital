"""Serum 2 routing matrix: FX bus sends and per-source destinations."""

from serum2vital import mapping, serum2


def _patch(state):
    return serum2.Serum2Patch(name="synthetic", author="", description="", tags=[], product_version="", state=state)


def test_bus_only_oscillator_keeps_its_send_level():
    # Factory preset pattern (e.g. "BA - The Even Odds"): level knob at zero,
    # 100% send to FX bus 1, so the oscillator is audible only through the bus.
    conv = mapping.convert_serum2(_patch({
        "Oscillator0": {"plainParams": {"kParamVolume": 0.00017}},
        "Oscillator1": {"plainParams": {"kParamEnable": 1.0, "kParamVolume": 0.0}},
        "RoutingSlot0": {"plainParams": {"kParamFXBus1Level": 100.0}},
        "RoutingSlot1": {"plainParams": {"kParamFXBus2Level": 60.0, "kParamRoutingDest": "kRoutingDestNone"}},
    }))
    assert conv.settings["osc_1_level"] == 1.0
    assert conv.settings["osc_2_level"] == 0.6
    assert conv.settings["osc_1_destination"] == 0.0      # slot 0 defaults to the filter
    assert conv.settings["osc_2_destination"] == 3.0      # "None": only the (flattened) bus chain
    assert sum("reaches the output only through an FX bus" in n for n in conv.notes) == 2


def test_serum2_phase_conventions():
    conv = mapping.convert_serum2(_patch({
        "Oscillator0": {"plainParams": {"kParamVolume": 0.5}, "WTOsc0": {"plainParams": {"kParamInitialPhase": 90.0, "kParamRandomPhase": 0.0}}},
        "Oscillator1": {"plainParams": {"kParamEnable": 1.0, "kParamVolume": 0.5}},
        "Oscillator4": {"plainParams": {"kParamEnable": 1.0, "kParamVolume": 0.5}, "SubOsc4": {"plainParams": {"kParamShape": "kSine"}}},
        "LFO0": {"plainParams": {"kParamPhase": 90.0}},
    }))
    assert conv.settings["osc_1_phase"] == 0.75 and conv.settings["osc_1_random_phase"] == 0.0
    assert conv.settings["osc_2_phase"] == 0.0          # Serum 2 default 180 degrees
    assert conv.settings["osc_3_phase"] == 0.0 and conv.settings["osc_3_random_phase"] == 0.0
    assert conv.settings["lfo_1_phase"] == 0.25


def test_routing_destinations_and_defaults():
    conv = mapping.convert_serum2(_patch({
        "Oscillator0": {"plainParams": {"kParamVolume": 0.5}},
        "Oscillator1": {"plainParams": {"kParamEnable": 1.0, "kParamVolume": 0.5}},
        "Oscillator2": {"plainParams": {"kParamEnable": 1.0, "kParamVolume": 0.5}},
        "RoutingSlot1": {"plainParams": {"kParamRoutingDest": "kRoutingDestFilter"}},
        "RoutingSlot2": {"plainParams": {"kParamRoutingDest": "kRoutingDestMaster"}},
    }))
    assert conv.settings["osc_1_level"] == 0.5 and conv.settings["osc_1_destination"] == 0.0
    assert conv.settings["osc_2_destination"] == 0.0
    assert conv.settings["osc_3_destination"] == 4.0      # master: bypasses the effects
    assert not any("FX bus" in n for n in conv.notes)
