"""Verdicts: identification and strictness per validator (Holm over Tier 1), and the day-B/C holdout."""
from .analyze import ALPHA, DOCUMENTED, MIN_EVALUABLE, STRICT


def holm(pvals, alpha=ALPHA):
    """{name: rejected?} under Holm's step-down procedure."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    out, m, stop = {}, len(items), False
    for i, (name, p) in enumerate(items):
        if stop or p > alpha / (m - i):
            stop = True
            out[name] = False
        else:
            out[name] = True
    return out


def calls(k_results, tiers, phase, family_of=None):
    """Per validator: which key (identification, Holm across Tier 1) and how strictly it holds."""
    rows = {name: r for name, r in k_results.items() if r["phase"] == phase}
    t1 = {name: r["keys"][r["best"]]["p_iut"] for name, r in rows.items() if tiers.get(r["validator"]) == 1}
    rej = holm(t1)
    out = {}
    for name, r in rows.items():
        best = r["keys"][r["best"]]
        tier = tiers.get(r["validator"])
        identified = rej.get(name, False) if tier == 1 else best["p_iut"] <= ALPHA
        # strict needs every rival's lower bound >= STRICT, so the weakest rival is the lowest lower bound
        # (a rival with no informative window counts as weakest); ties keep the first rival in key order
        weakest = min(best["rivals"].values(), key=lambda x: x["ci"][0] if x["n"] > 0 else -1)
        strict = weakest["n"] > 0 and weakest["ci"][0] >= STRICT
        null_p = r["null_p_best"] if r["null_p_best"] is not None else 1.0
        if r["evaluable"] < MIN_EVALUABLE or best["min_n"] < 5:
            verdict = "insufficient data"
        elif identified:
            verdict = "rule (strict)" if strict else "rule (loose)"
        elif null_p <= ALPHA:
            verdict = "order, no single key"
        else:
            verdict = "no rule detected"
        out[r["validator"]] = {"tier": tier, "family": r["family"], "key": r["best"], "verdict": verdict,
                               "identified": identified, "strict": strict, "p_iut": best["p_iut"],
                               "min_rate": best["min_rate"], "min_rate_ci": weakest["ci"], "min_n": best["min_n"],
                               "null_p": null_p, "documented_key": DOCUMENTED.get(r["family"]),
                               "matches_documented": r["best"] == DOCUMENTED[r["family"]] if r["family"] in DOCUMENTED else None}
    return out



def holdout(k_results, m_results, tiers, predictions):
    """Days B-D: does each validator's pre-registered key (from day A) pass the identification test,
    and does its predicted horizon fall inside that day's interval? A day with fewer than MIN_EVALUABLE
    evaluable K-main panels, or fewer than 5 informative windows against some rival, is "insufficient data"
    (PREREG), whatever the test says. Holm still runs over every Tier-1 validator of the day."""
    out = {}
    for ph in ("dayB", "dayC", "dayD"):
        rows = {r["validator"]: r for r in k_results.values() if r["phase"] == ph and r["validator"] in predictions}
        pv = {v: r["keys"][predictions[v]["key"]]["p_iut"] for v, r in rows.items()}
        rej_t1 = holm({v: p for v, p in pv.items() if tiers.get(v) == 1})
        res = {}
        for v, r in rows.items():
            k = predictions[v]["key"]
            kt = r["keys"][k]
            accepted = rej_t1.get(v, False) if tiers.get(v) == 1 else kt["p_iut"] <= ALPHA
            enough = r["evaluable"] >= MIN_EVALUABLE and kt["min_n"] >= 5      # the registered data gate
            res[v] = {"predicted": k, "p_iut": kt["p_iut"], "min_rate": kt["min_rate"], "min_n": kt["min_n"],
                      "evaluable": r["evaluable"], "best_this_day": r["best"], "accepted": accepted and enough,
                      "status": ("passed" if accepted else "failed") if enough else "insufficient data"}
        for v, p in predictions.items():
            m = m_results.get(f"{v}|{ph}", {}).get("increasing", {})
            if p.get("horizon_ms") is not None and m.get("horizon_ci"):
                lo, hi = m["horizon_ci"]
                inside = lo <= p["horizon_ms"] <= hi
                if not inside and m.get("censored") and p["horizon_ms"] > hi:
                    inside = None             # the day's horizon is only a lower bound: inconclusive, not a miss
                res.setdefault(v, {})["horizon"] = {"predicted_ms": p["horizon_ms"], "ci": [lo, hi],
                                                   "censored": bool(m.get("censored")), "inside": inside}
        if res:
            out[ph] = res
    return out
