"""The analysis recovers known rules from synthetic campaigns and stays quiet on noise."""
import json
import pathlib

import numpy as np

from itb import trains, verdicts
from itb.design import panels_from_json
from itb.sim import run_k, sim_train

PANELS = panels_from_json(json.loads((pathlib.Path(__file__).parents[1] / "design" / "panels.json").read_text())["panels"])


def test_recovers_each_rule_and_rejects_noise():
    truths = {"a": "agave_int", "f": "fd_exact", "b": "fee_per_cost", "p": "pf_per_cost", "r": "random", "q": "fifo"}
    calls, _ = run_k(PANELS, truths, 26, seed=11, null_perms=100)
    for v in "afbp":
        assert calls[v]["identified"] and calls[v]["key"] == truths[v] and calls[v]["verdict"] == "rule (strict)"
    assert not calls["r"]["identified"] and not calls["q"]["identified"]


def test_fingerprint_needs_exact_order():
    # fd_exact data must not be called agave_int: they differ only on the fingerprint pairs
    calls, _ = run_k(PANELS, {"f": "fd_exact"}, 26, seed=3, null_perms=50)
    assert calls["f"]["key"] == "fd_exact"


def test_holm():
    assert verdicts.holm({"x": 0.001, "y": 0.02, "z": 0.04}) == {"x": True, "y": True, "z": True}
    assert verdicts.holm({"x": 0.001, "y": 0.03, "z": 0.04}) == {"x": True, "y": False, "z": False}


def test_overtaking_curve_fifo_vs_rounds():
    rng = np.random.default_rng(0)
    fifo = [sim_train(rng, s, "fifo", jitter_ms=0.2) for s in ("t4", "t12") for _ in range(8)]
    rounds = [sim_train(rng, s, "rounds", T=50.0, jitter_ms=0.2) for s in ("t4", "t12") for _ in range(8)]
    hf = trains.overtaking_curve(fifo, rng, reps=50)["horizon_ms"]
    hr = trains.overtaking_curve(rounds, rng, reps=50)["horizon_ms"]
    assert hf == 0.0 and hr >= 12.0


def test_holdout_horizon_inside_interval():
    k = {"V|dayB": {"phase": "dayB", "validator": "V", "best": "agave_int",
                    "keys": {"agave_int": {"p_iut": 0.001, "min_rate": 0.9, "min_n": 20}}}}
    m = {"V|dayB": {"increasing": {"horizon_ci": [4.0, 12.0]}}}
    out = verdicts.holdout(k, m, {"V": 1}, {"V": {"key": "agave_int", "horizon_ms": 8.0}})["dayB"]["V"]
    assert out["accepted"] and out["horizon"]["inside"]
    out = verdicts.holdout(k, m, {"V": 1}, {"V": {"key": "agave_int", "horizon_ms": 20.0}})["dayB"]["V"]
    assert not out["horizon"]["inside"]


def test_predict_follows_the_registered_rule(tmp_path, monkeypatch):
    import argparse
    import json
    from itb import campaign
    (tmp_path / "data" / "derived").mkdir(parents=True)
    (tmp_path / "design").mkdir()
    cands = {"A1": {"family": "Agave", "tier": 1}, "H1": {"family": "HarmonicAgave", "tier": 1},
             "H2": {"family": "HarmonicAgave", "tier": 2}, "X": {"family": "Rakurai", "tier": None}}
    res = {"calls": {"dayA": {"A1": {"key": "fd_exact", "verdict": "partial"},
                              "H1": {"key": "pf_per_cost", "verdict": "rule"},
                              "X": {"key": "cu_price", "verdict": "rule"}}},
           "study_m": {"H1|dayA": {"increasing": {"horizon_ms": 16.0}}}}
    (tmp_path / "design" / "candidates.json").write_text(json.dumps(cands))
    (tmp_path / "data" / "derived" / "results.json").write_text(json.dumps(res))
    monkeypatch.setattr(campaign, "ROOT", tmp_path)
    campaign.cmd_predict(argparse.Namespace())
    p = json.loads((tmp_path / "design" / "predictions-dayB.json").read_text())["validators"]
    assert p["A1"]["key"] == "agave_int" and p["A1"]["dayA_best"] == "fd_exact"   # source key wins
    assert p["H1"]["key"] == "pf_per_cost" and p["H1"]["horizon_ms"] == 16.0
    assert p["H2"]["key"] == "pf_per_cost" and p["H2"]["tier"] == 2
    assert "X" not in p                                                           # calibration-only
