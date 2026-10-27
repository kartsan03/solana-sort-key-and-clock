"""Power simulation of the whole decision procedure on synthetic schedulers.

Study K: each simulated validator orders the panel by one candidate key (or FIFO with
network jitter, or at random), with a contamination rate eps (that share of windows
comes out in random order), per-probe landing probability and block splits. The real
analysis code (`study_k`, `calls`) then makes the calls.

Study M: trains through continuous priority, FIFO, or fixed rounds of T ms, and the
overtaking horizon that `overtaking_curve` recovers.
"""
import json
import pathlib

import numpy as np

from . import analyze, verdicts
from . import trains as trains_mod
from .design import LABELS, TRAIN_SPECS, panels_from_json, train
from .probe import ECONOMIC_KEYS, KEYS

ROOT = pathlib.Path(__file__).resolve().parents[1]


def sim_panel_window(rng, panel_name, panel, truth, eps, p_land, p_split, jitter_ms, wid):
    order = list(rng.permutation(list(LABELS)))
    if truth == "random" or rng.random() < eps:
        sched = list(rng.permutation(list(LABELS)))
    elif truth == "fifo":
        arrival = {lab: i * 0.05 + rng.normal(0, jitter_ms) for i, lab in enumerate(order)}
        sched = sorted(LABELS, key=lambda x: arrival[x])
    else:
        vals = {lab: KEYS[truth](q) for lab, q in panel.items()}
        tieb = {lab: rng.random() for lab in LABELS}
        sched = sorted(LABELS, key=lambda x: (vals[x], tieb[x]), reverse=True)
    cut = int(rng.integers(1, 6)) if rng.random() < p_split else 6
    probes = []
    for i, lab in enumerate(sched):
        if rng.random() > p_land:
            probes.append({"label": lab, "outcome": "expired"})
            continue
        slot = 100 if i < cut else 101
        probes.append({"label": lab, "outcome": "target_block", "slot": slot, "index": i})
    return {"window_id": wid, "study": "K", "arm": "K-main", "panel": panel_name, "send_order": order,
            "probes": probes, "status": "stable"}


def run_k(panels, truths, n_windows, eps=0.0, p_land=0.85, p_split=0.1, jitter_ms=1.0, seed=0, null_perms=200):
    """One simulated campaign: {validator: true key}; returns calls for Tier-1 validators."""
    rng = np.random.default_rng(seed)
    names = sorted(panels)
    windows = []
    for v, truth in truths.items():
        for i in range(n_windows):
            pn = names[i % len(names)]
            w = sim_panel_window(rng, pn, panels[pn], truth, eps, p_land, p_split, jitter_ms, f"{v}-{i}")
            w.update(target=v, phase="dayA", client="sim", ingress="sim")
            windows.append(w)
    old = analyze.NULL_PERMS
    analyze.NULL_PERMS = null_perms
    try:
        k = analyze.study_k(windows, panels, np.random.default_rng(seed + 1))
    finally:
        analyze.NULL_PERMS = old
    return verdicts.calls(k, {v: 1 for v in truths}, "dayA"), k


def power_k(panels, n_windows, reps, eps, p_land=0.85, seed=1):
    """Correct-call rate per true key, and false 'rule' rate under random/FIFO, with 8 validators per campaign."""
    truths_cycle = list(ECONOMIC_KEYS)
    correct = {k: 0 for k in truths_cycle}
    seen = {k: 0 for k in truths_cycle}
    false_rule = {"random": 0, "fifo": 0}
    false_seen = {"random": 0, "fifo": 0}
    for r in range(reps):
        truths = {f"v{i}": truths_cycle[(i + r) % len(truths_cycle)] for i in range(6)}
        truths["v6"], truths["v7"] = "random", "fifo"
        c, _ = run_k(panels, truths, n_windows, eps=eps, p_land=p_land, seed=seed * 100_000 + r)
        for v, t in truths.items():
            got = c.get(v, {})
            if t in correct:
                seen[t] += 1
                correct[t] += bool(got.get("identified")) and got.get("key") == t
            else:
                false_seen[t] += 1
                false_rule[t] += bool(got.get("identified"))
    return {"n_windows": n_windows, "eps": eps, "p_land": p_land, "reps": reps,
            "correct_rule_rate": {k: correct[k] / seen[k] for k in correct if seen[k]},
            "false_rule_rate": {k: false_rule[k] / false_seen[k] for k in false_rule}}


# ---- Study M ----

def sim_train(rng, spec, mode, T=20.0, jitter_ms=1.0, service_ms=0.5, p_land=0.9):
    n, spacing = TRAIN_SPECS[spec]
    qs = train(spec, True)                     # increasing priority along send order
    arr = np.array([i * spacing for i in range(n)]) + rng.normal(0, jitter_ms, n)
    pri = np.array([q.pf for q in qs], dtype=float)
    if mode == "fifo":
        order = list(np.argsort(arr))
    elif mode == "rounds":
        phase = rng.uniform(0, T)
        rnd = np.floor((arr + phase) / T)
        order = sorted(range(n), key=lambda i: (rnd[i], -pri[i]))
    else:  # continuous: one tx per service tick, highest priority among those arrived
        order, waiting, t, pending = [], [], 0.0, sorted(range(n), key=lambda i: arr[i])
        while pending or waiting:
            while pending and arr[pending[0]] <= t:
                waiting.append(pending.pop(0))
            if waiting:
                best = max(waiting, key=lambda i: pri[i])
                waiting.remove(best)
                order.append(best)
            t += service_ms
    probes = []
    for pos, i in enumerate(order):
        if rng.random() < p_land:
            probes.append({"label": f"T{i:02d}", "outcome": "target_block", "slot": 100, "index": pos})
    return {"study": "M", "arm": "M-inc", "train": spec, "probes": probes, "status": "stable"}


def horizon_m(mode, n_trains, reps, T=20.0, seed=2):
    rng = np.random.default_rng(seed)
    hs = []
    for _ in range(reps):
        trains = [sim_train(rng, spec, mode, T=T) for spec in ("t4", "t12") for _ in range(n_trains // 2)]
        trains = [w for w in trains if trains_mod.evaluable_train(dict(w, probes=w["probes"] + [{}] * 0))]
        hs.append(trains_mod.overtaking_curve(trains, rng, reps=100)["horizon_ms"])
    hs = [h for h in hs if h is not None]
    return {"mode": mode, "T": T if mode == "rounds" else None, "n_trains": n_trains, "reps": reps,
            "horizon_median": float(np.median(hs)) if hs else None,
            "horizon_p10_p90": [float(np.percentile(hs, 10)), float(np.percentile(hs, 90))] if hs else None}


def main(reps=200):
    panels = panels_from_json(json.loads((ROOT / "design" / "panels.json").read_text())["panels"])
    out = {"k": [], "m": []}
    for n in (16, 22, 28):
        for eps in (0.0, 0.1, 0.25):
            r = power_k(panels, n, reps, eps)
            out["k"].append(r)
            print(json.dumps(r))
    for mode, T in (("fifo", 0), ("continuous", 0), ("rounds", 20.0), ("rounds", 50.0)):
        r = horizon_m(mode, 20, max(20, reps // 5), T=T or 20.0)
        out["m"].append(r)
        print(json.dumps(r))
    (ROOT / "design" / "power.json").write_text(json.dumps(out, indent=1))
