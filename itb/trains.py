"""Study M: overtaking curve and horizon from in-window probe trains (unit = train)."""
import itertools
import math
from collections import Counter, defaultdict

import numpy as np

from .analyze import family


def train_pairs(w):
    """(gap_ms, overtook) for every pair of train probes that landed in the same target block."""
    spacing = 4.0 if w["train"] == "t4" else 12.0
    by_label = {p["label"]: p for p in w["probes"] if p.get("outcome") == "target_block" and p.get("index") is not None}
    out = []
    labels = sorted(by_label)
    for i, j in itertools.combinations(range(len(labels)), 2):
        a, b = by_label[labels[i]], by_label[labels[j]]       # a was sent before b
        if a["slot"] != b["slot"]:
            continue
        gap = (int(labels[j][1:]) - int(labels[i][1:])) * spacing
        out.append((gap, b["index"] < a["index"]))
    return out


def overtaking_curve(trains, rng, reps=1000):
    gaps = sorted({g for w in trains for g, _ in train_pairs(w)})
    if not trains or not gaps:
        return {"gaps": [], "rate": [], "ci": [], "horizon_ms": None, "horizon_ci": None, "trains": len(trains)}
    per = [train_pairs(w) for w in trains]

    def curve(sample):
        rate = []
        for g in gaps:
            v = [o for prs in sample for gg, o in prs if gg == g]
            rate.append(sum(v) / len(v) if v else float("nan"))
        return rate

    def horizon(rate):
        h = None
        for g, r in zip(gaps, rate):
            if not math.isnan(r) and r >= 0.5:
                h = g
        return h if h is not None else 0.0

    rate = curve(per)
    boots, hs = [], []
    for _ in range(reps):
        idx = rng.integers(0, len(per), len(per))
        r = curve([per[i] for i in idx])
        boots.append(r)
        hs.append(horizon(r))
    arr = np.array(boots, dtype=float)
    ci = [[float(np.nanpercentile(arr[:, i], 2.5)), float(np.nanpercentile(arr[:, i], 97.5))]
          if not np.all(np.isnan(arr[:, i])) else [None, None] for i in range(len(gaps))]
    return {"gaps": gaps, "rate": rate, "ci": ci, "horizon_ms": horizon(rate),
            "horizon_ci": [float(np.percentile(hs, 2.5)), float(np.percentile(hs, 97.5))], "trains": len(trains)}


def evaluable_train(w):
    n = len(w["probes"])
    need = 8 if n == 12 else 7
    by = Counter(p["slot"] for p in w["probes"] if p.get("outcome") == "target_block")
    return bool(by) and max(by.values()) >= need


def study_m(windows, rng):
    out = {}
    by_v = defaultdict(list)
    for w in windows:
        if w["study"] == "M" and w["status"] != "transition":
            by_v[(w["target"], w["phase"])].append(w)
    for (v, ph), ws in sorted(by_v.items()):
        inc = [w for w in ws if w["arm"] == "M-inc"]
        dec = [w for w in ws if w["arm"] == "M-dec"]
        out[f"{v}|{ph}"] = {"validator": v, "phase": ph, "family": family(ws[0]), "trains": len(ws),
                            "evaluable": sum(evaluable_train(w) for w in ws),
                            "increasing": overtaking_curve([w for w in inc if evaluable_train(w)], rng),
                            "decreasing": overtaking_curve([w for w in dec if evaluable_train(w)], rng)}
    return out
