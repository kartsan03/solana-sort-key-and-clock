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
from .probe import ECONOMIC_KEYS, KEYS

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW, DERIVED = ROOT / "data" / "raw", ROOT / "data" / "derived"
SEED = 20261030
THETA_ID = 0.5         # identification: the key beats each rival in more than half of informative windows
STRICT = 0.75          # strictness: lower 95% bound of the weakest rival's win rate at least this
ALPHA = 0.05
MIN_EVALUABLE = 15     # fewer evaluable K-main panels on a day -> "insufficient data"
NULL_PERMS = 2000
PHASES = {"smoke": "calibration", "pilot": "calibration", "A": "dayA", "B": "dayB", "C": "dayC", "D": "dayD"}
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
        loads = {b["slot"]: b.get("n_tx") for b in jl(d / "blocks.jsonl.gz") if not b.get("skipped")}
        for w in jl(d / "windows.jsonl.gz"):
            if "planned_ns" not in w:
                continue
            w["phase"] = phase_of(w["run_id"])
            w["probes"] = sorted(probes.get(w["window_id"], []), key=lambda p: p["label"])
            w["status"] = bracket(w, snaps)
            slots = Counter(p["slot"] for p in w["probes"] if p.get("outcome") == "target_block")
            w["block_load"] = loads.get(slots.most_common(1)[0][0]) if slots else None
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


def p_greater(wins, n, theta=THETA_ID):
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


def load_terciles(windows):
    """Cut points (transactions per block) splitting each phase's K-main windows into thirds."""
    cuts = {}
    for ph in {w["phase"] for w in windows}:
        xs = sorted(w["block_load"] for w in windows if w["phase"] == ph and w["study"] == "K"
                    and w.get("block_load") is not None)
        cuts[ph] = [xs[len(xs) // 3], xs[2 * len(xs) // 3]] if len(xs) >= 3 else None
    return cuts


def study_k(windows, panels, rng):
    out = {}
    cuts = load_terciles(windows)
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
        by_load = {}
        c = cuts.get(ph)
        if c:
            for name, lo, hi in (("low", -1, c[0]), ("mid", c[0], c[1]), ("high", c[1], 10**9)):
                sub = [w for w in main if w.get("block_load") is not None and lo < w["block_load"] <= hi]
                by_load[name] = {"windows": len(sub), "best_key_agreement": _agree_rate(sub, panels, best)}
        free = [w for w in ws if w["arm"] == "K-free"]
        free_agree = {k: _agree_rate(free, panels, k) for k in (best,)}
        out[f"{v}|{ph}"] = {
            "validator": v, "phase": ph, "family": family(ws[0]), "ingress": ws[0].get("ingress"),
            "windows": len(ws), "k_main": len(main), "evaluable": sum(evaluable(w) for w in main),
            "informative": {f"{a}|{b}": n_inf[(a, b)] for a, b in KEY_PAIRS},
            "named": {c: {"n": n_inf[kp], "k1_wins": res[kp]} for c, kp in NAMED.items()},
            "keys": table, "best": best, "agreement": desc, "send_order": arms, "k_free_best_agreement": free_agree,
            "null_p_best": randomisation_null(main, panels, best, rng) if main else None,
            "by_block_load": by_load, "load_cuts": c,
        }
    return out


def _agree_rate(ws, panels, k):
    a = t = 0
    for w in ws:
        x, y = agreement(block_orders(w), panels[w["panel"]], k)
        a, t = a + x, t + y
    return a / t if t else None


# ---------------- driver ----------------

def compute():
    panels = panels_from_json(json.loads((ROOT / "design" / "panels.json").read_text())["panels"])
    cands = json.loads((ROOT / "design" / "candidates.json").read_text())
    tiers = {k: v["tier"] for k, v in cands.items()}
    windows = load()
    rng = np.random.default_rng(SEED)
    from .checks import fee_check, gates, inclusion
    from .trains import study_m
    from .verdicts import calls, holdout
    k = study_k(windows, panels, rng)
    res = {"n_windows": len(windows), "phases": dict(Counter(w["phase"] for w in windows)),
           "study_k": k, "calls": {ph: calls(k, tiers, ph) for ph in ("calibration", "dayA", "dayB", "dayC", "dayD")},
           "study_m": study_m(windows, rng), "inclusion": inclusion(windows), "fees": fee_check(windows),
           "gates": gates(windows, panels)}
    pred_path = ROOT / "design" / "predictions-dayB.json"
    if pred_path.exists():
        preds = json.loads(pred_path.read_text())["validators"]
        res["holdout"] = holdout(k, res["study_m"], tiers, preds)
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
