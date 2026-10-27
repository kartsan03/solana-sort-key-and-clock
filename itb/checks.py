"""Inclusion counts, the per-probe fee check and the pilot gates (calibration runs only)."""
from collections import Counter, defaultdict

import numpy as np

from .analyze import DOCUMENTED, evaluable, family, window_contrasts


# ---------------- inclusion ----------------

def inclusion(windows):
    out = defaultdict(Counter)
    for w in windows:
        for p in w["probes"]:
            out[f"{w['target']}|{w['phase']}"][p.get("outcome", "missing")] += 1
    return {k: dict(v) for k, v in sorted(out.items())}


def fee_check(windows):
    """Every landed probe was charged exactly 5000 + ceil(L*p/1e6)."""
    bad, n = [], 0
    for w in windows:
        for p in w["probes"]:
            if p.get("outcome") in ("target_block", "other_leader", "later_window_same_leader") and "fee_charged" in p:
                n += 1
                if p["fee_charged"] != p["fee"]:
                    bad.append(p["sig"])
    return {"checked": n, "mismatches": bad}




EXEC_COST = 720 + 600 + 7 + 600 + 8      # executed cost of any landed probe (meta.costUnits)


def gates(windows, panels):
    """Engineering hard stops (F3-eng, F4, F5) and calibration gates (F1, F2, anchor) per validator."""
    cal = [w for w in windows if w["phase"] == "calibration"]
    out, fee_bad, cost_bad = {}, [], []
    spacing_err = []
    for w in cal:
        for p in w["probes"]:
            if "fee_charged" in p and p["fee_charged"] != p["fee"]:
                fee_bad.append(p["sig"])
            if p.get("cost_units") is not None and (p["cost_units"] != EXEC_COST or p.get("cu_consumed") != 600):
                cost_bad.append(p["sig"])
        if w["study"] == "M":
            sent = [p["sent_ns"] for p in sorted(w["probes"], key=lambda p: p["label"]) if "sent_ns" in p]
            plan = sorted(w["planned_ns"])
            spacing_err += [abs((b - a) - (d - c)) / 1e6 for a, b, c, d in zip(sent, sent[1:], plan, plan[1:])]
    by_v = defaultdict(list)
    for w in cal:
        by_v[w["target"]].append(w)
    for v, ws in sorted(by_v.items()):
        probes = [p for w in ws for p in w["probes"]]
        landed = [p for p in probes if p.get("outcome") in ("target_block", "other_leader", "later_window_same_leader")]
        target = [p for p in probes if p.get("outcome") == "target_block"]
        main = [w for w in ws if w["study"] == "K" and w["arm"] == "K-main"]
        inf = sum(len(window_contrasts(w, panels[w["panel"]])) > 0 for w in main)
        charged = sum(p.get("fee_charged") or 0 for p in probes)
        fam = family(ws[0])
        doc = DOCUMENTED.get(fam)
        agree = None
        if doc and main:
            wins = n = 0
            for w in main:
                for kp, sgn in window_contrasts(w, panels[w["panel"]]).items():
                    if doc in kp:
                        n += 1
                        wins += (sgn > 0) == (kp[0] == doc)
            agree = wins / n if n else None
        slots = Counter((p["slot"] - w["slot0"]) for w in ws for p in w["probes"] if p.get("outcome") == "target_block")
        out[v] = {"family": fam, "ingress": ws[0].get("ingress"), "windows": len(ws), "probes": len(probes),
                  "landed": len(landed), "target_rate": len(target) / len(probes) if probes else None,
                  "outcomes": dict(Counter(p.get("outcome") for p in probes)),
                  "k_main": len(main), "k_main_informative": inf,
                  "evaluable_rate": sum(evaluable(w) for w in main) / len(main) if main else None,
                  "lamports_per_informative": charged / inf if inf else None,
                  "documented_key": doc, "documented_agreement": agree,
                  "landing_slot_in_window": {str(k): v for k, v in sorted(slots.items())},
                  "anchor_outside_rate": 1 - len(target) / len(landed) if landed else None}
    return {"per_validator": out, "F5_fee_mismatch": fee_bad, "exec_cost_mismatch": cost_bad,
            "F4_spacing_err_ms": {"median": float(np.median(spacing_err)) if spacing_err else None,
                                  "p90": float(np.percentile(spacing_err, 90)) if spacing_err else None,
                                  "n": len(spacing_err)}}
