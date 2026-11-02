"""Exploratory follow-up on the four Harmonic validators (runs S-*, after the registered days).

Day A showed that Harmonic validators order queued probes by Agave's integer priority, except that the
compute-unit limit seems to count toward cost only up to some cap X (1660 <= X <= 4098, locked in memo #2
as exploratory). This sweep measures X and asks whether the limit above X counts at all:

    cost_eff = cost - L + min(L, X) + floor(beta * max(L - X, 0))
    priority = floor((pf + 2500) * 1e6 / (cost_eff + 1))

beta = 0 is a hard cap; beta = 1 is plain agave_int. Panel S1 puts three 700-CU probes against three
4,400-CU probes: it brackets X in steps of about 250 CU. Panels S2 (fine) and S3 (coarse) put three 4,400-CU
probes against three 40,000-CU probes that pay a little more: under a hard cap both sizes cost the same and
the 40,000-CU probes go first; every extra CU counted above X pushes them back, one pair at a time. S2 brackets
that extra cost (beta * 35,600 CU) between 25 and 1,000 CU, S3 between 300 and 5,000 CU.
Nothing here feeds a registered call.
"""
import json
from collections import Counter

import numpy as np

from .probe import BASE_REWARD, Probe

D32K = 32 * 1024
PANELS = {
    "S1": {"A": (700, 2_000_000), "B": (700, 2_341_000), "C": (700, 2_703_000),
           "D": (4400, 1_188_000), "E": (4400, 1_532_000), "F": (4400, 1_942_000)},
    "S2": {"A": (4400, 944_545), "B": (4400, 983_181), "C": (4400, 1_022_727),
           "D": (40_000, 113_500), "E": (40_000, 127_325), "F": (40_000, 142_250)},
    "S3": {"A": (4400, 767_500), "B": (4400, 889_545), "C": (4400, 1_022_727),
           "D": (40_000, 124_600), "E": (40_000, 180_725), "F": (40_000, 253_675)},
}
PANELS = {n: {k: Probe(L, p, D32K) for k, (L, p) in pr.items()} for n, pr in PANELS.items()}
LABELS = "ABCDEF"
X_GRID = np.arange(1500, 4401)
BETA_GRID = np.round(np.concatenate([np.arange(0, 0.0301, 0.0002), np.arange(0.031, 0.1501, 0.001),
                                     np.arange(0.16, 1.0001, 0.01)]), 4)
MIN_FULL = 4                                                      # fully landed windows needed per panel
FIT_SHARE = 0.8                                                   # best model must match this share of them


def c_eff(L, X, beta):
    X, beta = np.asarray(X), np.asarray(beta)
    return np.minimum(L, X) + np.floor(beta * np.maximum(L - X, 0) + 1e-9).astype(np.int64)


def codes(name, X, beta):
    """Predicted block order at each (X, beta), as an integer code (ties broken by label)."""
    pr = np.stack([(q.pf + BASE_REWARD) * 1_000_000 // (q.cost - q.L + c_eff(q.L, X, beta) + 1)
                   for q in (PANELS[name][k] for k in LABELS)], axis=-1)
    idx = np.argsort(-pr, axis=-1, kind="stable")
    return (idx * 6 ** np.arange(5, -1, -1)).sum(axis=-1)


def code_of(order):
    return sum(LABELS.index(c) * 6 ** (5 - i) for i, c in enumerate(order))


def order_of(code):
    return "".join(LABELS[int(code) // 6 ** (5 - i) % 6] for i in range(6))


def order(name, X, beta):
    return order_of(codes(name, np.array([X]), np.array([beta]))[0])


def classes(name, along, values, fixed):
    """[[lo, hi, order], ...] as X (beta fixed) or beta (X fixed) runs over `values`."""
    out = []
    for v in values:
        o = order(name, v, fixed) if along == "X" else order(name, fixed, v)
        v = float(v) if along == "beta" else int(v)
        if out and out[-1][2] == o:
            out[-1][1] = v
        else:
            out.append([v, v, o])
    return out


def full_windows(windows):
    """Per panel: block order of every stable K-main sweep window whose six probes share one target block."""
    out = {n: [] for n in PANELS}
    for w in windows:
        if w["phase"] != "capsweep" or w.get("arm") != "K-main" or w.get("status") != "stable":
            continue
        got = [p for p in w["probes"] if p.get("outcome") == "target_block" and p.get("index") is not None]
        if len(got) == 6 and len({p["slot"] for p in got}) == 1:
            out[w["panel"]].append({"window_id": w["window_id"], "target": w["target"],
                                    "order": "".join(p["label"] for p in sorted(got, key=lambda p: p["index"]))})
    return out


def span(a):
    return [a.min().item(), a.max().item()] if len(a) else None


def fit(full):
    X = np.repeat(X_GRID, len(BETA_GRID))
    B = np.tile(BETA_GRID, len(X_GRID))
    total, panels = np.zeros(len(X), dtype=np.int64), {}
    for n in PANELS:
        obs = Counter(r["order"] for r in full[n])
        c = codes(n, X, B)
        s = sum(k * (c == code_of(o)) for o, k in obs.items()) if obs else np.zeros(len(X), dtype=np.int64)
        total += s
        top = s == s.max()
        panels[n] = {"full_windows": len(full[n]), "orders": dict(sorted(obs.items())), "best_matches": int(s.max()),
                     "X": span(X[top]) if obs else None, "beta": span(B[top]) if obs else None}
    n_all = sum(len(full[n]) for n in PANELS)
    best, top = int(total.max()), total == total.max()
    hard = B == 0
    hard_best = int(total[hard].max())
    betas = B[top]
    models = {"no_cap (agave_int)": int(total[B == 1].max()),
              "hard_cap": {"matches": hard_best, "X": span(X[hard & (total == hard_best)])},
              "capped (best X, beta)": {"matches": best, "X": span(X[top]), "beta": span(betas),
                                        "extra_cu_40000_vs_4400": span(np.floor(betas * 35_600 + 1e-9).astype(int))}}
    small = [n for n in PANELS if len(full[n]) < MIN_FULL]
    if small:
        verdict = f"too few fully landed windows ({', '.join(small)})"
    elif best < FIT_SHARE * n_all:
        verdict = "the capped model does not fit"
    elif betas.min() == 0:
        verdict = "hard cap not excluded"
    elif betas.max() < 1:
        verdict = "soft cap: the limit above X still counts, at a reduced slope"
    else:
        verdict = "no cap"
    return {"full_windows": n_all, "panels": panels, "models": models, "verdict": verdict}


def analyze(windows):
    from .checks import fee_check
    sw = [w for w in windows if w["phase"] == "capsweep"]
    full = full_windows(sw)
    per_target = {}
    for n in PANELS:
        for r in full[n]:
            per_target.setdefault(r["target"], {}).setdefault(n, Counter())[r["order"]] += 1
    return {"windows": len(sw), "arms": dict(Counter(w.get("arm") for w in sw)),
            "transition": sum(w.get("status") != "stable" for w in sw), **fit(full),
            "per_validator": {t: {n: dict(sorted(c.items())) for n, c in sorted(v.items())}
                              for t, v in sorted(per_target.items())},
            "fees": fee_check(sw)}


def joint(windows, root):
    """Consistency check added after the sweep (not in memo #3): one (X, beta) for every fully landed, stable K-main
    window on the four Harmonic validators, all phases (calibration, days A-D, sweep), campaign panels P1/P2 included."""
    from .orders import full_order
    targets = set(json.loads((root / "design" / "capsweep-targets.json").read_text()))
    pan = json.loads((root / "design" / "panels.json").read_text())["panels"]
    panels = {**PANELS, **{n: {k: Probe(v["L"], v["p"], v["D"]) for k, v in pan[n].items()} for n in ("P1", "P2")}}
    obs = {}
    for w in windows:
        if w["target"] in targets and w.get("study") == "K" and w.get("arm") == "K-main" and w.get("status") == "stable":
            ps = full_order(w)
            if ps is not None:
                c = obs.setdefault((w["phase"], w["panel"]), Counter())
                c["".join(p["label"] for p in ps)] += 1
    xs = np.arange(1300, 4401)
    X, B = np.repeat(xs, len(BETA_GRID)), np.tile(BETA_GRID, len(xs))
    saved = dict(PANELS)
    PANELS.update(panels)
    try:
        hits = {k: sum(n * (codes(k[1], X, B) == code_of(o)) for o, n in c.items()) for k, c in obs.items()}
    finally:
        PANELS.clear()
        PANELS.update(saved)
    total = sum(hits.values()) if hits else np.zeros(len(X), dtype=np.int64)
    top = total == total.max()
    after = [k for k in hits if k[0] not in ("calibration", "dayA")]          # after memo #2 fixed the formula
    return {"full_windows": sum(sum(c.values()) for c in obs.values()), "best_matches": int(total.max()),
            "X": span(X[top]), "beta": span(B[top]), "hard_cap": int(total[B == 0].max()),
            "no_cap (agave_int)": int(total[B == 1].max()),
            "after_memo2": {"full_windows": sum(sum(obs[k].values()) for k in after),
                            "matches_at_best": span(sum(hits[k] for k in after)[top]) if after else None},
            "groups": {f"{ph}|{pa}": {"full_windows": sum(obs[(ph, pa)].values()),
                                     "matches_at_best": span(hits[(ph, pa)][top])} for ph, pa in sorted(obs)}}


def design(root):
    """design/capsweep.json: panels, the order each (X, beta) predicts, the readout and the prediction."""
    targets = json.loads((root / "design" / "capsweep-targets.json").read_text())
    fee = {n: sum(q.fee for q in p.values()) for n, p in PANELS.items()}
    d = {
        "label": "exploratory follow-up (not registered); designed after days A-C, locked by memo #3 before any probe",
        "model": " ".join(__doc__.split("\n\n")[1].split()),
        "panels": {n: {k: {"L": q.L, "p": q.p, "D": q.D} for k, q in sorted(p.items())} for n, p in PANELS.items()},
        "max_fee": fee,
        "classes": {"S1 over X, beta = 0": classes("S1", "X", X_GRID, 0.0),
                    **{f"{n} over beta, X = 3000": classes(n, "beta", BETA_GRID, 3000) for n in ("S2", "S3")}},
        "grid": {"X": [int(X_GRID[0]), int(X_GRID[-1])], "beta": "0..0.03 step 0.0002, 0.031..0.15 step 0.001, "
                 "0.16..1 step 0.01"},
        "targets": targets,
        "plan": ("itb plan --targets design/capsweep-targets.json --panels design/capsweep.json --run-id S-1102 "
                 "--hours 6, started after the day D data commit. K-main arm only (shared lock); panel drawn at "
                 "random per window; send order, payer slots and send offset drawn as in the campaign. If the cap "
                 "left after day D is below the plan's maximum + 300,000 lamports, K drops by one per validator "
                 "until it fits."),
        "readout": ("Full window = stable K-main window with all six probes in one target block. For each (X, beta) "
                    "on the grid, count full windows whose block order equals the predicted order, over all three "
                    "panels. Report the maximisers' X and beta ranges, the best hard cap (beta = 0) and no cap "
                    f"(agave_int). Verdict: 'too few' if a panel has < {MIN_FULL} full windows; 'does not fit' if "
                    f"the best model matches < {FIT_SHARE:.0%} of them; else 'hard cap not excluded' if beta = 0 is "
                    "a maximiser, 'soft cap' if every maximiser has 0 < beta < 1, 'no cap' otherwise. Orders are "
                    "also reported per validator and per panel."),
        "prediction": "X in 1660..4098 (S1 inside those classes) and beta = 0 is not a maximiser (soft cap).",
    }
    path = root / "design" / "capsweep.json"
    path.write_text(json.dumps(d, indent=1) + "\n")
    return path, d
