import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from serum2vital import filter_map as fm  # noqa: E402
from serum2vital.serum_tables import FILTER_NAMES  # noqa: E402

SERUM2_NAMES = [
    "MgL6", "MgL12", "MgL18", "MgL24",
    "L6", "L12", "L18", "L24", "H6", "H12", "H18", "H24",
    "B12", "B24", "P12", "N24",
    "LH12", "LB12", "LP12", "LN12", "HB12", "HP12", "HN12", "BP12", "BN12",
    "PP12", "PN12", "NN12",
    "LBH12", "LBH24", "LPH24", "LNH12", "LNH24", "BPN12", "BPN24",
    "LadderEMS", "LadderMg", "LadderAcid", "DirtyMg",
    "Diffuser", "CombP", "CombN", "Comb2", "Combs", "CombH6P", "CombH6N",
    "CombL6N", "CombHL6P", "CombHL6N",
    "FlangeP", "FlangeN", "FlangeL6P", "FlangeHL6P", "FlangeHL6N",
    "FlangePhase12HL6P", "Phase24P", "Phase24N", "Phase48P", "Phase48N",
    "Phase48H6P", "Phase48HL6P",
    "Wsp", "Exp", "ExpBPF", "Reverb1", "BandReject", "FormantONE", "FormantTWO",
    "DistComb1LP", "DistComb1BP", "DistComb2LP", "DJMixer", "PZ_SVF", "RM",
    "Scream", "Scream3LP", "Allpasses", "ADD_BASS", "HEQ12",
]


def _check_target(target: fm.FilterTarget, label: str) -> None:
    assert 0 <= target.model <= 7, label
    assert 0 <= target.style < fm.STYLE_COUNTS[target.model], label
    assert 0.0 <= target.blend <= 2.0, label
    assert target.var_role in fm.VAR_ROLES, label
    assert target.fidelity in fm.FIDELITIES, label
    if target.fidelity == "exact":
        assert target.note == "", label
    else:
        assert target.note, label
    if target.blend_transpose is not None:
        assert 0.0 <= target.blend_transpose <= 84.0, label
    if target.formant_x is not None:
        assert 0.0 <= target.formant_x <= 1.0 and 0.0 <= target.formant_y <= 1.0, label
    if target.mix_hint is not None:
        assert 0.0 <= target.mix_hint <= 1.0, label
    if target.second is not None:
        assert target.var_role == "second_cutoff", label
        _check_target(target.second, label + " (second)")
    # Slot params and VAR params stay inside Vital's ranges.
    params = target.slot_params()
    assert params["model"] == target.model and params["style"] == target.style
    for var in (0.0, 0.25, 0.5, 0.75, 1.0):
        for cutoff in (8.0, 60.0, 136.0):
            extra = fm.apply_var(target, var, cutoff)
            for key, value in extra.items():
                assert isinstance(value, float), (label, key)
                if key == "blend":
                    assert 0.0 <= value <= 2.0, (label, key)
                elif key == "blend_transpose":
                    assert 0.0 <= value <= 84.0, (label, key)
                elif key in ("mix", "resonance"):
                    assert 0.0 <= value <= 1.0, (label, key)
                elif key == "cutoff":
                    assert 8.0 <= value <= 136.0, (label, key)
                elif key == "formant_transpose":
                    assert -12.0 <= value <= 12.0, (label, key)
                elif key == "style":
                    assert 0 <= value < fm.STYLE_COUNTS[target.model], (label, key)
                else:
                    pytest.fail(f"unexpected apply_var key {key!r} for {label}")


def test_serum1_name_table_matches_serum_tables():
    assert len(FILTER_NAMES) == 96
    assert tuple(FILTER_NAMES) == fm.SERUM1_FILTER_NAMES


@pytest.mark.parametrize("index", range(len(FILTER_NAMES)), ids=FILTER_NAMES)
def test_serum1_targets(index):
    target = fm.target_for_serum1(index)
    _check_target(target, FILTER_NAMES[index])
    assert target == fm.target_for_serum1_name(FILTER_NAMES[index])


@pytest.mark.parametrize("name", SERUM2_NAMES)
def test_serum2_targets(name):
    _check_target(fm.target_for_serum2(name), name)


def test_serum1_only_expected_unsupported():
    unsupported = {FILTER_NAMES[i] for i in range(96)
                   if fm.target_for_serum1(i).fidelity == "unsupported"}
    assert unsupported == {"Ring Mod", "Ring Modx2", "SampHold", "SampHold-"}


def test_serum2_only_rm_unsupported():
    unsupported = {n for n in SERUM2_NAMES if fm.target_for_serum2(n).fidelity == "unsupported"}
    assert unsupported == {"RM"}


def test_specific_mappings():
    mg24 = fm.target_for_serum1_name("MG Low 24")
    assert (mg24.model, mg24.style, mg24.blend, mg24.fidelity) == (2, 1, 0.0, "exact")
    mg6 = fm.target_for_serum1_name("MG Low 6")
    assert (mg6.model, mg6.style, mg6.fidelity) == (2, 0, "approximation")

    high12 = fm.target_for_serum1_name("High 12")
    assert (high12.model, high12.style, high12.blend, high12.fidelity) == (0, 0, 2.0, "exact")
    band24 = fm.target_for_serum1_name("Band 24")
    assert (band24.style, band24.blend) == (1, 1.0)
    peak12 = fm.target_for_serum1_name("Peak 12")
    assert (peak12.style, peak12.blend) == (4, 1.0)
    notch12 = fm.target_for_serum1_name("Notch 12")
    assert (notch12.style, notch12.blend) == (2, 1.0)

    ln12 = fm.target_for_serum1_name("LN 12")
    assert ln12.var_role == "second_cutoff"
    assert (ln12.blend, ln12.second.style, ln12.second.blend) == (0.0, 2, 1.0)

    lbh = fm.target_for_serum1_name("L/B/H 24")
    assert (lbh.model, lbh.style, lbh.var_role, lbh.fidelity) == (0, 1, "morph_blend", "exact")
    assert fm.apply_var(lbh, 0.5, 60.0) == {"blend": 1.0}
    assert fm.apply_var(lbh, 1.0, 60.0) == {"blend": 2.0}
    lnh = fm.target_for_serum1_name("L/N/H 12")
    assert lnh.style == 2
    bpn = fm.target_for_serum1_name("B/P/N 12")
    assert bpn.style == 4

    cmb_pos = fm.target_for_serum1_name("Cmb +")
    cmb_neg = fm.target_for_serum1_name("Cmb -")
    assert cmb_pos.model == 6 and cmb_pos.style == 0 and cmb_neg.style == 0
    assert fm.map_resonance(cmb_pos, 1.0) == 1.0
    assert fm.map_resonance(cmb_neg, 1.0) == 0.0
    assert fm.map_resonance(cmb_pos, 0.0) == 0.5
    flg_pos = fm.target_for_serum1_name("Flg +")
    flg_neg = fm.target_for_serum1_name("Flg -")
    assert (flg_pos.style, flg_neg.style) == (1, 2)
    assert fm.map_resonance(flg_neg, 0.7) == pytest.approx(0.7)
    hl = fm.target_for_serum1_name("Cmb HL6+")
    assert hl.style == 3 and hl.var_role == "feedback_filter"
    assert fm.apply_var(hl, 0.5, 60.0) == {"blend": 1.0, "blend_transpose": 0.0}
    l6 = fm.target_for_serum1_name("Cmb L6+")
    assert l6.blend == 0.0
    assert fm.apply_var(l6, 60.0 / 135.0, 48.0)["blend_transpose"] == pytest.approx(12.0)

    phs = fm.target_for_serum1_name("Phs 48-")
    assert (phs.model, phs.style, phs.blend) == (7, 1, 1.0)
    assert fm.target_for_serum1_name("Phs 24+").blend == 0.0

    eq = fm.target_for_serum1_name("Low EQ 12")
    assert eq.var_role == "gain"
    assert fm.apply_var(eq, 0.5, 60.0) == {"mix": 0.0}
    assert fm.apply_var(eq, 1.0, 60.0) == {"style": 0.0, "blend": 0.0, "mix": 1.0}
    assert fm.apply_var(eq, 0.0, 60.0) == {"style": 0.0, "blend": 2.0, "mix": 1.0}

    formant = fm.target_for_serum1_name("Formant-II")
    assert formant.model == 5 and formant.var_role == "formant"
    assert fm.apply_var(formant, 1.0, 60.0) == {"formant_transpose": 12.0}
    assert fm.formant_xy_from_cutoff(8.0, 1) == (0.0, 0.0)
    assert fm.formant_xy_from_cutoff(135.0, 2) == (1.0, 0.0)

    french = fm.target_for_serum1_name("French LP")
    assert (french.model, french.style, french.fidelity) == (4, 1, "character")
    german = fm.target_for_serum1_name("German LP")
    assert (german.model, german.style) == (2, 1)
    scream = fm.target_for_serum1_name("Scream BP")
    assert (scream.model, scream.style, scream.blend) == (1, 1, 1.0)

    dist = fm.target_for_serum1_name("Dist.Comb 2 LP")
    assert dist.model == 6 and dist.resonance_polarity == -1
    extra = fm.apply_var(dist, 40.0 / 135.0, 70.0)
    assert extra["cutoff"] == pytest.approx(40.0) and extra["blend_transpose"] == pytest.approx(30.0)

    ring = fm.target_for_serum1_name("Ring Mod")
    assert ring.fidelity == "unsupported" and ring.mix_hint == 0.0

    # Serum 2 aliases resolve to the same targets as their Serum 1 names.
    assert fm.target_for_serum2("MgL24") == mg24
    assert fm.target_for_serum2("LNH12") == lnh
    assert fm.target_for_serum2("CombHL6P") == hl
    assert fm.target_for_serum2("Phase48N") == phs
    assert fm.target_for_serum2("HEQ12") == fm.target_for_serum1_name("High EQ 12")
    assert fm.target_for_serum2("FlangePhase12HL6P") == fm.target_for_serum1_name("FPhs 12HL6+")
    assert fm.target_for_serum2("LadderAcid").model == 2
    assert fm.target_for_serum2("DirtyMg").model == 1
    assert fm.target_for_serum2("Comb2").resonance_polarity == -1


def test_unknown_names_fall_back():
    assert fm.target_for_serum1(999).fidelity == "unsupported"
    assert fm.target_for_serum2("NoSuchFilter").fidelity == "unsupported"
