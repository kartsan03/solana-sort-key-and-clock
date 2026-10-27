"""Offline analysis: data/raw -> data/derived (results.json, tables.md), CLAIMS.md, figures/.

Unit of inference is the window (Study K) or the train (Study M), never the probe pair.
With --check (the default under `docker compose up`) the committed derived numbers must
match the recomputed ones exactly (floats to 1e-9 relative).
"""
import gzip
import itertools
import json
import math
import pathlib
import sys
from collections import Counter, defaultdict

import numpy as np
from scipy.stats import binom

from .design import KEY_PAIRS, NAMED, decisive_pairs, panels_from_json
from .probe import ECONOMIC_KEYS, KEYS, Probe

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, DERIVED = ROOT / "data" / "raw", ROOT / "data" / "derived"
SEED = 20261030
THETA0 = 0.75          # a rule must win each contrast in more than 3/4 of informative windows
ALPHA = 0.05
NULL_PERMS = 2000
PHASES = {"smoke": "calibration", "pilot": "calibration", "A": "dayA", "B": "dayB"}
DOCUMENTED = {"Agave": "agave_int", "JitoLabs": "agave_int", "Firedancer": "fd_exact"}


def jl(path):
    if not path.exists():
        return []
    with gzip.open(path, "rt") as f:
        return [json.loads(x) for x in f if x.strip()]


def phase_of(run_id):
    return PHASES.get(run_id.split("-")[0], "other")


# ---------------- loading ----------------

def load(raw=RAW):
    windows = []
    for d in sorted(p for p in raw.iterdir() if p.is_dir()) if raw.exists() else []:
        outs = {o["sig"]: o for o in jl(d / "outcomes.jsonl.gz")}
        if not outs:
            continue
        probes = defaultdict(list)
        for p in jl(d / "probes.jsonl.gz"):
            p.update(outs.get(p["sig"], {"outcome": "missing"}))
            probes[p["window_id"]].append(p)
        snaps = [s for s in jl(d / "snapshots.jsonl.gz") if s.get("kind") == "gossip"]
        for w in jl(d / "windows.jsonl.gz"):
            if "planned_ns" not in w:
                continue
            w["phase"] = phase_of(w["run_id"])
            w["probes"] = sorted(probes.get(w["window_id"], []), key=lambda p: p["label"])
            w["status"] = bracket(w, snaps)
            windows.append(w)
    return windows


def bracket(w, snaps, max_ns=60_000_000_000):
    """'stable', 'transition' or 'unbracketed', from gossip snapshots either side of the send."""
    t = w["planned_ns"][0]
    before = [s for s in snaps if s["t_ns"] <= t and t - s["t_ns"] <= max_ns and w["target"] in s["nodes"]]
    after = [s for s in snaps if s["t_ns"] >= t and s["t_ns"] - t <= max_ns and w["target"] in s["nodes"]]
    if not before or not after:
        return "unbracketed"
    a, b = before[-1]["nodes"][w["target"]], after[0]["nodes"][w["target"]]
    same = all(a.get(k) == b.get(k) for k in ("client", "ingress", "tpuQuic"))
    return "stable" if same else "transition"


def family(w):
    return w.get("client") or "unknown"


# ---------------- Study K ----------------

def block_orders(w):
    """{slot: [labels in block order]} for probes that landed in the target window."""
    by = defaultdict(list)
    for p in w["probes"]:
        if p.get("outcome") == "target_block" and p.get("index") is not None:
            by[p["slot"]].append((p["index"], p["label"]))
    return {s: [lab for _, lab in sorted(v)] for s, v in by.items()}


def first_of(orders, x, y):
    """Label that came first if x and y share a block, else None."""
    for seq in orders.values():
        if x in seq and y in seq:
            return x if seq.index(x) < seq.index(y) else y
    return None


def window_contrasts(w, panel):
    """{(k1, k2): +1 if k1 won the window, -1 if k2 won, absent if not informative}."""
    orders = block_orders(w)
    dp = decisive_pairs(panel)
    out = {}
    for kp, pairs in dp.items():
        votes = 0
        for x, y in pairs:
            f = first_of(orders, x, y)
            if f is None:
                continue
            r1 = ranks(panel, kp[0])
            k1_first = x if r1[x] > r1[y] else y
            votes += 1 if f == k1_first else -1
        if votes:
            out[kp] = 1 if votes > 0 else -1
    return out


def p_greater(wins, n, theta=THETA0):
    """One-sided exact binomial p-value for H0: win prob <= theta."""
    return float(binom.sf(wins - 1, n, theta)) if n else 1.0


def clopper_pearson(k, n, conf=0.95):
    from scipy.stats import beta
    if n == 0:
        return [0.0, 1.0]
    a = (1 - conf) / 2
    lo = 0.0 if k == 0 else float(beta.ppf(a, k, n - k + 1))
    hi = 1.0 if k == n else float(beta.ppf(1 - a, k + 1, n - k))
    return [lo, hi]


def key_table(results_by_pair):
    """Per key: wins/n against every rival, the intersection-union p-value and min win rate."""
    table = {}
    for k in ECONOMIC_KEYS:
        rivals = {}
        for (k1, k2), (w1, n) in results_by_pair.items():
            if k in (k1, k2):
                wins = w1 if k == k1 else n - w1
                rivals[k2 if k == k1 else k1] = {"wins": wins, "n": n, "rate": wins / n if n else None,
                                                 "p": p_greater(wins, n), "ci": clopper_pearson(wins, n)}
        p_iut = max(r["p"] for r in rivals.values())
        rates = [r["rate"] for r in rivals.values() if r["rate"] is not None]
        table[k] = {"rivals": rivals, "p_iut": p_iut, "min_rate": min(rates) if len(rates) == len(rivals) else None,
                    "min_n": min(r["n"] for r in rivals.values())}
    return table


_RANKS = {}


def ranks(panel, key):
    """Integer rank per label (higher = earlier under `key`), equal for ties. Cached."""
    ck = (tuple(sorted((lab, q.L, q.p, q.D) for lab, q in panel.items())), key)
    if ck not in _RANKS:
        vals = sorted({KEYS[key](q) for q in panel.values()})
        _RANKS[ck] = {lab: vals.index(KEYS[key](q)) for lab, q in panel.items()}
    return _RANKS[ck]


def agreement(orders, panel, key):
    """Share of same-block probe pairs ordered as `key` predicts (ties excluded)."""
    r = ranks(panel, key)
    agree = tot = 0
    for seq in orders.values():
        for i, j in itertools.combinations(range(len(seq)), 2):
            a, b = r[seq[i]], r[seq[j]]
            if a != b:
                tot += 1
                agree += a > b
    return agree, tot


def randomisation_null(ws, panels, key, rng):
    """P-value that `key`'s agreement beats in-block random orderings of the same landed probes."""
    obs = sum(agreement(block_orders(w), panels[w["panel"]], key)[0] for w in ws)
    hits = 0
    for _ in range(NULL_PERMS):
        tot = 0
        for w in ws:
            orders = {s: list(rng.permutation(seq)) for s, seq in block_orders(w).items()}
            tot += agreement(orders, panels[w["panel"]], key)[0]
        hits += tot >= obs
    return (hits + 1) / (NULL_PERMS + 1)


def fifo_stats(ws):
    """For each window: share of same-block pairs whose order matches send order."""
    agree = tot = 0
    for w in ws:
        rank = {lab: i for i, lab in enumerate(w["send_order"])}
        for seq in block_orders(w).values():
            for i, j in itertools.combinations(range(len(seq)), 2):
                tot += 1
                agree += rank[seq[i]] < rank[seq[j]]
    return {"agree": agree, "pairs": tot, "rate": agree / tot if tot else None}


def evaluable(w, need=4):
    return any(len(seq) >= need for seq in block_orders(w).values())


def study_k(windows, panels, rng):
    out = {}
    by_v = defaultdict(list)
    for w in windows:
        if w["study"] == "K" and w["status"] != "transition":
            by_v[(w["target"], w["phase"])].append(w)
    for (v, ph), ws in sorted(by_v.items()):
        main = [w for w in ws if w["arm"] == "K-main"]
        res = Counter()
        n_inf = Counter()
        for w in main:
            for kp, s in window_contrasts(w, panels[w["panel"]]).items():
                n_inf[kp] += 1
                res[kp] += s > 0
        table = key_table({kp: (res[kp], n_inf[kp]) for kp in KEY_PAIRS})
        best = min(ECONOMIC_KEYS, key=lambda k: (table[k]["p_iut"], -(table[k]["min_rate"] or 0)))
        desc = {}
        for k in ECONOMIC_KEYS:
            a = t = 0
            for w in main:
                x, y = agreement(block_orders(w), panels[w["panel"]], k)
                a, t = a + x, t + y
            desc[k] = a / t if t else None
        arms = {arm: fifo_stats([w for w in ws if w["arm"] == arm]) for arm in ("K-main", "K-null", "K-free")}
        free = [w for w in ws if w["arm"] == "K-free"]
        free_agree = {k: _agree_rate(free, panels, k) for k in (best,)}
        out[f"{v}|{ph}"] = {
            "validator": v, "phase": ph, "family": family(ws[0]), "ingress": ws[0].get("ingress"),
            "windows": len(ws), "k_main": len(main), "evaluable": sum(evaluable(w) for w in main),
            "informative": {f"{a}|{b}": n_inf[(a, b)] for a, b in KEY_PAIRS},
            "named": {c: {"n": n_inf[kp], "k1_wins": res[kp]} for c, kp in NAMED.items()},
            "keys": table, "best": best, "agreement": desc, "send_order": arms, "k_free_best_agreement": free_agree,
            "null_p_best": randomisation_null(main, panels, best, rng) if main else None,
        }
    return out


def _agree_rate(ws, panels, k):
    a = t = 0
    for w in ws:
        x, y = agreement(block_orders(w), panels[w["panel"]], k)
        a, t = a + x, t + y
    return a / t if t else None


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


def calls(k_results, tiers, phase):
    """Rule / partial / no rule per validator for one phase; Holm across the Tier-1 validators."""
    rows = {name: r for name, r in k_results.items() if r["phase"] == phase}
    t1 = {name: r["keys"][r["best"]]["p_iut"] for name, r in rows.items() if tiers.get(r["validator"]) == 1}
    rej = holm(t1)
    out = {}
    for name, r in rows.items():
        best = r["keys"][r["best"]]
        tier = tiers.get(r["validator"])
        rule = rej.get(name, False) if tier == 1 else best["p_iut"] <= ALPHA
        if rule:
            verdict = "rule"
        elif best["min_rate"] is not None and best["min_rate"] > 0.5 and (r["null_p_best"] or 1) <= ALPHA:
            verdict = "partial"
        elif (r["null_p_best"] or 1) > ALPHA:
            verdict = "no rule detected"
        else:
            verdict = "partial"
        if best["min_n"] < 1:
            verdict = "insufficient data"
        out[r["validator"]] = {"tier": tier, "family": r["family"], "key": r["best"], "verdict": verdict,
                               "p_iut": best["p_iut"], "min_rate": best["min_rate"], "min_n": best["min_n"],
                               "documented_key": DOCUMENTED.get(r["family"])}
    return out


# ---------------- Study M ----------------

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



# ---------------- pilot gates (calibration runs only) ----------------

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


# ---------------- driver ----------------

def compute():
    panels = panels_from_json(json.loads((ROOT / "design" / "panels.json").read_text())["panels"])
    cands = json.loads((ROOT / "design" / "candidates.json").read_text())
    tiers = {k: v["tier"] for k, v in cands.items()}
    windows = load()
    rng = np.random.default_rng(SEED)
    k = study_k(windows, panels, rng)
    res = {"n_windows": len(windows), "phases": dict(Counter(w["phase"] for w in windows)),
           "study_k": k, "calls": {ph: calls(k, tiers, ph) for ph in ("calibration", "dayA", "dayB")},
           "study_m": study_m(windows, rng), "inclusion": inclusion(windows), "fees": fee_check(windows),
           "gates": gates(windows, panels)}
    return json.loads(json.dumps(res, sort_keys=True, default=str))


def same(a, b, path="$"):
    if isinstance(a, float) or isinstance(b, float):
        if a is None or b is None or not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12):
            return [f"{path}: {a!r} != {b!r}"]
        return []
    if isinstance(a, dict) and isinstance(b, dict):
        diffs = [f"{path}: keys differ {sorted(set(a) ^ set(b))[:5]}"] if set(a) != set(b) else []
        for k in sorted(set(a) & set(b)):
            diffs += same(a[k], b[k], f"{path}.{k}")
        return diffs
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: length {len(a)} != {len(b)}"]
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in same(x, y, f"{path}[{i}]")]
    return [] if a == b else [f"{path}: {a!r} != {b!r}"]


def main(check=True):
    res = compute()
    DERIVED.mkdir(parents=True, exist_ok=True)
    path = DERIVED / "results.json"
    if check and path.exists():
        diffs = same(json.loads(path.read_text()), res)
        if diffs:
            print(f"MISMATCH: {len(diffs)} differences vs committed data/derived/results.json", file=sys.stderr)
            for d in diffs[:30]:
                print("  " + d, file=sys.stderr)
            return 1
        print(f"OK: recomputed results match committed numbers ({res['n_windows']} windows)")
    else:
        path.write_text(json.dumps(res, indent=1, sort_keys=True))
        print(f"wrote {path} ({res['n_windows']} windows)")
    try:
        from .report import write_outputs
    except ImportError:
        return 0
    write_outputs(res, check=check)
    return 0
