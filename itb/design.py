"""Experimental design: probe panels, trains, and per-window randomisation.

A panel is 6 probes sent together just before a leader window. It is built so that
every pair of candidate sort keys orders at least two probe pairs in opposite ways
("decisive pairs"), so whichever probe lands first tells the keys apart.
"""
import itertools
import json
import random
import secrets

from .probe import ECONOMIC_KEYS, KEYS, PAGE_BYTES, Probe, predicted_order, predicts

KEY_PAIRS = list(itertools.combinations(ECONOMIC_KEYS, 2))
# Named contrasts used in the write-up (each is one key pair).
NAMED = {
    "C-fp": ("agave_int", "fd_exact"),        # +1 and floor vs exact ratio
    "C-base0": ("fd_exact", "pf_per_cost"),   # base-fee share 2,500 vs 0
    "C-base5": ("fd_exact", "fee_per_cost"),  # 2,500 vs 5,000
    "C-div": ("fd_exact", "fee_per_cu"),      # divide by cost vs by requested CU
    "C-price": ("fd_exact", "cu_price"),
    "C-fee": ("fd_exact", "total_fee"),
    "C-cheap": ("fd_exact", "cheapest"),
}
MARGIN = 0.01        # every key in a non-fingerprint decisive pair differs by >= 1 %
LABELS = "ABCDEF"


def p_for_pf(L, pf):
    """Smallest micro-lamport price whose priority fee is exactly pf lamports."""
    return 0 if pf == 0 else (pf - 1) * 10**6 // L + 1


def make(L, pf, pages_):
    q = Probe(L, p_for_pf(L, pf), pages_ * PAGE_BYTES)
    assert q.pf == pf
    return q


def rel_margin(key, a, b):
    ka, kb = float(KEYS[key](a)), float(KEYS[key](b))
    m = max(abs(ka), abs(kb))
    return abs(ka - kb) / m if m else 0.0


def decisive_pairs(panel):
    """{(k1, k2): [(x, y), ...]} probe-label pairs where k1 and k2 strictly disagree."""
    out = {kp: [] for kp in KEY_PAIRS}
    for x, y in itertools.combinations(sorted(panel), 2):
        a, b = panel[x], panel[y]
        s = {k: predicts(k, a, b) for k in ECONOMIC_KEYS}
        for k1, k2 in KEY_PAIRS:
            if s[k1] * s[k2] != -1:
                continue
            if (k1, k2) != NAMED["C-fp"]:
                if min(rel_margin(k1, a, b), rel_margin(k2, a, b)) < MARGIN:
                    continue
            out[(k1, k2)].append((x, y))
    return out


def composition(panel, pair):
    a, b = panel[pair[0]], panel[pair[1]]
    if a.D == b.D:
        return "L"
    if a.L == b.L:
        return "D"
    return "LD"


def score(panel, fp_kind, fee_cap):
    dp = decisive_pairs(panel)
    s = sum(min(len(v), 2) for v in dp.values())
    fp = [p for p in dp[NAMED["C-fp"]] if composition(panel, p) == fp_kind]
    s += 3 * min(len(fp), 2)
    fee = sum(q.fee for q in panel.values())
    if fee > fee_cap:
        s -= (fee - fee_cap) / 500
    return s


def search_panel(rng, fp_kind, fee_cap=40_000, iters=4000):
    """Hill-climb a 6-probe panel; fp_kind 'L' or 'D' sets how the fingerprint pairs differ."""
    Ls = list(range(700, 6001, 100))
    pages_ = [1, 1, 1, 2, 4, 8, 16, 64, 256, 1024, 2048]

    def rand_probe():
        return make(rng.choice(Ls), rng.randrange(0, 3001), rng.choice(pages_))

    def snap(cur):
        """Re-price one probe so it forms a fingerprint pair of the wanted kind with another."""
        x, y = rng.sample(LABELS, 2)
        a, b = cur[x], cur[y]
        if fp_kind == "D":
            b = make(a.L, b.pf, b.D // PAGE_BYTES if b.D != a.D else rng.choice(pages_[3:]))
        else:
            b = make(b.L if b.L != a.L else a.L + 1000, b.pf, a.D // PAGE_BYTES)
        target = (a.pf + 2500) * b.cost / a.cost - 2500
        for pf in range(max(0, int(target) - 3), int(target) + 4):
            c = make(b.L, pf, b.D // PAGE_BYTES)
            if predicts("agave_int", a, c) * predicts("fd_exact", a, c) == -1:
                out = dict(cur)
                out[y] = c
                return out
        return cur

    def tweak(q):
        L, pf, pg = q.L, q.pf, q.D // PAGE_BYTES
        r = rng.random()
        if r < 0.4:
            pf = max(0, min(3500, pf + rng.randint(-60, 60)))
        elif r < 0.7:
            L = max(700, min(6000, L + rng.choice([-100, 100, -300, 300])))
        elif r < 0.85:
            pg = rng.choice(pages_)
        else:
            return rand_probe()
        return make(L, pf, pg)

    best, best_s = None, -1e9
    for _ in range(6):
        cur = {lab: rand_probe() for lab in LABELS}
        cur_s = score(cur, fp_kind, fee_cap)
        for _ in range(iters):
            if rng.random() < 0.15:
                cand = snap(cur)
            else:
                lab = rng.choice(LABELS)
                cand = dict(cur)
                cand[lab] = tweak(cur[lab])
            if len(set(cand.values())) < 6:
                continue
            s = score(cand, fp_kind, fee_cap)
            if s >= cur_s:
                cur, cur_s = cand, s
        if cur_s > best_s:
            best, best_s = cur, cur_s
    return best


def panel_report(panel):
    dp = decisive_pairs(panel)
    missing = [kp for kp, v in dp.items() if not v]
    thin = [kp for kp, v in dp.items() if len(v) == 1]
    return {"fee": sum(q.fee for q in panel.values()), "missing": missing, "single": thin,
            "fp_pairs": [(p, composition(panel, p)) for p in dp[NAMED["C-fp"]]]}


# ---- trains (Study M) ----

TRAIN_SPECS = {"t4": (12, 4.0), "t12": (10, 12.0)}  # name -> (probes, spacing ms)
TRAIN_L, TRAIN_PAGES, TRAIN_PF0, TRAIN_STEP = 1_000, 1, 160, 140


def train(spec, increasing):
    n, _ = TRAIN_SPECS[spec]
    pfs = [TRAIN_PF0 + TRAIN_STEP * i for i in range(n)]
    if not increasing:
        pfs.reverse()
    return [make(TRAIN_L, pf, TRAIN_PAGES) for pf in pfs]


NULL_PROBE = (1_000, 1_000, 1)  # K-null: six identical probes (L, pf, pages)


# ---- per-window randomisation (OS randomness, logged per window) ----

_sys = secrets.SystemRandom()


def draw_panel_window(panel_names, arm_weights=(("K-main", 0.75), ("K-null", 0.10), ("K-free", 0.15))):
    arm = _sys.choices([a for a, _ in arm_weights], [w for _, w in arm_weights])[0]
    order = list(LABELS)
    _sys.shuffle(order)          # send order
    payers = list(range(6))
    _sys.shuffle(payers)         # payer slot for each label, in LABELS order
    return {"study": "K", "arm": arm, "panel": _sys.choice(panel_names),
            "send_order": order, "payer_slots": payers,
            "offset_ms": round(_sys.uniform(-600, -200), 3)}


def draw_train_window():
    spec = _sys.choice(list(TRAIN_SPECS))
    inc = _sys.random() < 0.8
    payers = list(range(TRAIN_SPECS[spec][0]))
    _sys.shuffle(payers)
    return {"study": "M", "arm": "M-inc" if inc else "M-dec", "train": spec, "payer_slots": payers,
            "phase_ms": round(_sys.uniform(30, 70), 3)}


def build_design(seed):
    rng = random.Random(seed)
    panels = {"P1": search_panel(rng, "L"), "P2": search_panel(rng, "D")}
    return panels


def panel_json(panel):
    return {lab: {"L": q.L, "p": q.p, "D": q.D, "pf": q.pf, "cost": q.cost, "fee": q.fee}
            for lab, q in sorted(panel.items())}


def panels_from_json(d):
    return {name: {lab: Probe(v["L"], v["p"], v["D"]) for lab, v in pr.items()} for name, pr in d.items()}


def prediction_table_md(panels):
    lines = ["# Prediction table", "",
             "Generated by `itb design`. Larger key value = scheduled earlier. `{XY}` = tie.", ""]
    for name, panel in panels.items():
        lines += [f"## Panel {name}", "", "| Probe | L | p (µL/CU) | D (bytes) | pf | cost | fee |",
                  "|---|---|---|---|---|---|---|"]
        for lab, q in sorted(panel.items()):
            lines.append(f"| {lab} | {q.L} | {q.p} | {q.D} | {q.pf} | {q.cost} | {q.fee} |")
        lines += ["", "| Key | Predicted order |", "|---|---|"]
        for k in ECONOMIC_KEYS:
            grp = predicted_order(k, panel)
            lines.append(f"| `{k}` | " + " ".join(g[0] if len(g) == 1 else "{" + "".join(g) + "}" for g in grp) + " |")
        dp = decisive_pairs(panel)
        lines += ["", "| Contrast | Keys | Decisive probe pairs (composition) |", "|---|---|---|"]
        for cname, kp in NAMED.items():
            pairs = ", ".join(f"{x}{y} ({composition(panel, (x, y))})" for x, y in dp[kp])
            lines.append(f"| {cname} | `{kp[0]}` vs `{kp[1]}` | {pairs or '—'} |")
        lines.append("")
    return "\n".join(lines)


def write_design(seed, out_dir):
    import pathlib
    panels = build_design(seed)
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "panels.json").write_text(json.dumps({"seed": seed, "panels": {n: panel_json(p) for n, p in panels.items()}}, indent=1))
    (out / "prediction_table.md").write_text(prediction_table_md(panels))
    return panels
