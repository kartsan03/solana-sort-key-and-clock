"""The Harmonic cap sweep readout recovers the model that generated synthetic windows."""
import random

from itb import capsweep as cs


def windows(X, beta, n=6, shuffle=False, seed=1):
    rng, out = random.Random(seed), []
    for name in cs.PANELS:
        for i in range(n):
            o = list(cs.order(name, X, beta))
            if shuffle:
                rng.shuffle(o)
            out.append({"phase": "capsweep", "arm": "K-main", "status": "stable", "panel": name,
                        "window_id": f"S-{name}-{i}", "target": "T" * (i % 2 + 1),
                        "probes": [{"label": lab, "outcome": "target_block", "slot": 7, "index": j, "sig": lab,
                                    "fee": 1, "fee_charged": 1} for j, lab in enumerate(o)]})
    return out


def test_classes_match_the_designed_thresholds():
    s1 = cs.classes("S1", "X", cs.X_GRID, 0.0)
    assert [lo for lo, _, _ in s1][1:] == [2246, 2466, 2699, 2947, 3210, 3489, 3783, 4098]
    assert s1[-1][2] == cs.order("S1", 4400, 1.0)                   # X >= 4098 looks uncapped on S1
    for n in ("S2", "S3"):                                           # hard cap: 40,000-CU probes first, by fee
        assert cs.order(n, 3000, 0.0) == "FEDCBA" and cs.order(n, 3000, 1.0) == "CBAFED"
        assert len(cs.classes(n, "beta", cs.BETA_GRID, 3000)) == 10
    assert cs.order("S2", 3000, 0.001) != "FEDCBA"                   # ~36 extra CU is already visible


def test_soft_cap_is_recovered():
    r = cs.analyze(windows(3000, 0.012))
    m = r["models"]["capped (best X, beta)"]
    assert r["verdict"].startswith("soft cap") and m["matches"] == 18
    assert m["X"][0] <= 3000 <= m["X"][1] and m["beta"][0] <= 0.012 <= m["beta"][1] and m["beta"][0] > 0
    assert m["beta"][1] - m["beta"][0] < 0.005 and m["X"][1] - m["X"][0] < 300


def test_hard_cap_and_no_cap():
    assert cs.analyze(windows(3000, 0))["verdict"] == "hard cap not excluded"
    assert cs.analyze(windows(3000, 1.0))["verdict"] == "no cap"


def test_noise_and_thin_data():
    assert cs.analyze(windows(3000, 0.012, shuffle=True))["verdict"] == "the capped model does not fit"
    assert cs.analyze(windows(3000, 0.012, n=3))["verdict"].startswith("too few")
    # windows from registered phases are ignored
    assert cs.analyze([dict(w, phase="dayD") for w in windows(3000, 0)])["windows"] == 0


def test_report_table_renders():
    from itb.report import capsweep_table
    text = "\n".join(capsweep_table({"capsweep": cs.analyze(windows(3000, 0.012))}))
    assert "soft cap" in text and "S3 | 6 |" in text
    assert capsweep_table({"capsweep": cs.analyze([])}) == []


def test_joint_check_fits_one_model_across_phases():
    import json
    from itb.analyze import ROOT
    target = next(iter(json.loads((ROOT / "design" / "capsweep-targets.json").read_text())))
    ws = [dict(w, target=target, study="K") for w in windows(1800, 0.15)]
    saved = dict(cs.PANELS)
    j = cs.joint(ws, ROOT)
    assert cs.PANELS == saved                                        # P1/P2 are added only inside the check
    assert j["full_windows"] == j["best_matches"] == 18
    assert j["X"][0] <= 1800 <= j["X"][1] and j["beta"][0] <= 0.15 <= j["beta"][1]
