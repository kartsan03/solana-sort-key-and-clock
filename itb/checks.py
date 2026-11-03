"""Inclusion counts, the per-probe fee check, the cost check and the pilot gates (calibration runs only)."""
import json
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


CAMPAIGN = ("dayA", "dayB", "dayC", "dayD")


def inclusion_by_rank(windows):
    """PREREG 'Inclusion', descriptive: in campaign trains (equal L and D, fee rising 140 lamports per step) the
    share of probes landing in the target block, by fee rank (1 = cheapest), per spacing and ingress kind."""
    out = {}
    for w in windows:
        if w["phase"] not in CAMPAIGN or w["study"] != "M":
            continue
        inc = w["arm"] == "M-inc"
        n = len(w["probes"])
        for p in w["probes"]:
            pos = int(p["label"][1:])
            rank = pos + 1 if inc else n - pos
            for ing in (w.get("ingress") or "unknown", "all"):
                c = out.setdefault(w["train"], {}).setdefault(ing, {}).setdefault(str(rank), [0, 0])
                c[0] += p.get("outcome") == "target_block"
                c[1] += 1
    return {sp: {ing: dict(sorted(r.items(), key=lambda kv: int(kv[0]))) for ing, r in sorted(v.items())}
            for sp, v in sorted(out.items())}


def send_precision(windows):
    """Campaign trains: realised minus planned gap between consecutive sends (sent_ns), per spacing."""
    out = {}
    for w in windows:
        if w["phase"] not in CAMPAIGN or w["study"] != "M":
            continue
        step = 4.0 if w["train"] == "t4" else 12.0
        ts = [p["sent_ns"] for p in sorted(w["probes"], key=lambda p: p["label"]) if p.get("sent_ns")]
        devs = [abs((b - a) / 1e6 - step) for a, b in zip(ts, ts[1:])]
        r = out.setdefault(w["train"], {"trains": 0, "gaps": 0, "devs": [], "off_1ms": 0, "trains_off_1ms": 0})
        r["trains"] += 1
        r["gaps"] += len(devs)
        r["devs"] += devs
        r["off_1ms"] += sum(d > 1 for d in devs)
        r["trains_off_1ms"] += any(d > 1 for d in devs)
    return {sp: {"trains": r["trains"], "gaps": r["gaps"], "median_abs_dev_ms": round(float(np.median(r["devs"])), 4)
                 if r["devs"] else None, "gaps_off_by_more_than_1ms": r["off_1ms"],
                 "trains_with_such_a_gap": r["trains_off_1ms"]} for sp, r in sorted(out.items())}


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


def spend(windows, root, cap=50_000_000):
    """Total cost from committed evidence: the block fee of every probe (data/raw) plus every operations
    transaction (memos, payer funding, sweep) listed in the newest data/audit file. It must equal the audit's
    on-chain fee total, and the audit's balance-based spend plus deposits strangers sent to my wallets."""
    files = sorted((root / "data" / "audit").glob("audit-*.json"))
    if not files:
        return None
    a = json.loads(files[-1].read_text())
    probe = sum(p.get("fee_charged") or 0 for w in windows for p in w["probes"])
    fees, count = Counter(), Counter()
    for o in a.get("ops_transactions", []):
        fees[o["kind"]] += o["fee"]
        count[o["kind"]] += 1
    deposits = [sum(u["deltas"].values()) for u in a["unknown_transactions"]]
    total = probe + sum(fees.values())
    return {"audit_file": files[-1].name, "probe_fees": probe, "ops_fees": dict(sorted(fees.items())),
            "ops_transactions": dict(sorted(count.items())), "total_fees": total,
            "audit_chain_fees": a["fees_on_chain"], "audit_balance_spent": a["balance_spent"],
            "unsolicited_deposits": {"count": len(deposits), "lamports": sum(deposits)},
            "agree": total == a["fees_on_chain"] == a["balance_spent"] + sum(deposits),
            "cap": cap, "under_cap": total <= cap, "left_in_wallets": a["balance_total"]}


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
