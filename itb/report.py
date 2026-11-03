"""Tables, CLAIMS.md and figures generated from results.json (deterministic text; figures redrawn)."""
import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
DERIVED, FIG = ROOT / "data" / "derived", ROOT / "figures"
NAMES = json.loads((ROOT / "design" / "candidates.json").read_text())
KEY_ORDER = ["agave_int", "fd_exact", "pf_per_cost", "fee_per_cost", "cu_price", "fee_per_cu", "total_fee", "cheapest"]


def short(v):
    return v[:8]


def fmt(x, nd=2):
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def calls_table(res, phase):
    rows = res["calls"].get(phase, {})
    if not rows:
        return []
    out = [f"### Sort-key calls, {phase}", "",
           "| Validator | Client | Ingress | Tier | Best key | Verdict | Min win rate | Min n | p (IUT) | Source-code key |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    k = res["study_k"]
    for v, r in sorted(rows.items(), key=lambda kv: (kv[1]["tier"] or 9, kv[1]["family"])):
        ing = k.get(f"{v}|{phase}", {}).get("ingress")
        out.append(f"| `{short(v)}` | {r['family']} | {ing} | {r['tier']} | `{r['key']}` | {r['verdict']} | "
                   f"{fmt(r['min_rate'])} | {r['min_n']} | {r['p_iut']:.2g} | {('`' + r['documented_key'] + '`') if r['documented_key'] else '—'} |")
    return out + [""]


def contrast_table(res, phase):
    rows = [r for r in res["study_k"].values() if r["phase"] == phase]
    if not rows:
        return []
    names = list(rows[0]["named"])
    out = [f"### Named contrasts, {phase} (first key's wins / informative windows)", "",
           "| Validator | " + " | ".join(names) + " |", "|---" * (len(names) + 1) + "|"]
    for r in sorted(rows, key=lambda r: r["family"]):
        cells = [f"{r['named'][c]['k1_wins']}/{r['named'][c]['n']}" for c in names]
        out.append(f"| `{short(r['validator'])}` {r['family']} | " + " | ".join(cells) + " |")
    return out + [""]


def order_table(res, phase):
    rows = [r for r in res["study_k"].values() if r["phase"] == phase]
    if not rows:
        return []
    out = [f"### Send order vs block order, {phase} (share of same-block pairs in send order)", "",
           "| Validator | K-main | K-null (equal economics) | K-free (no shared lock) | Best key agreement, K-main / K-free |",
           "|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: r["family"]):
        so = r["send_order"]
        cell = lambda a: f"{fmt(so[a]['rate'])} ({so[a]['pairs']})" if so[a]["pairs"] else "—"
        out.append(f"| `{short(r['validator'])}` {r['family']} | {cell('K-main')} | {cell('K-null')} | {cell('K-free')} | "
                   f"{fmt(r['agreement'][r['best']])} / {fmt(r['k_free_best_agreement'].get(r['best']))} |")
    return out + [""]


def train_table(res, phase):
    rows = [r for r in res["study_m"].values() if r["phase"] == phase]
    if not rows:
        return []
    out = [f"### Trains, {phase}: overtaking horizon (largest send gap at which a later, higher-priority probe "
           "still lands first in at least half of pairs)", "",
           "| Validator | Client | Trains (evaluable) | Horizon ms [95% CI] | Falling-fee trains |", "|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: r["family"]):
        inc, dec = r["increasing"], r["decreasing"]
        ci = inc["horizon_ci"]
        ge = "≥" if inc.get("censored") else ""       # at the longest gap the trains could show
        if inc["trains"] < 2:          # one train: a bootstrap interval says nothing
            h = f"{ge}{fmt(inc['horizon_ms'], 0)} (one train, no interval)" if inc["trains"] else "—"
        else:
            h = f"{ge}{fmt(inc['horizon_ms'], 0)} [{fmt(ci[0], 0)}, {fmt(ci[1], 0)}]"
        out.append(f"| `{short(r['validator'])}` | {r['family']} | {r['trains']} ({r['evaluable']}) | {h} | {dec['trains']} |")
    return out + [""]


def inclusion_table(res):
    out = ["### Where every probe ended up", "",
           "| Validator / phase | target block | later window | other leader | expired | send failed |", "|---|---|---|---|---|---|"]
    for k, c in res["inclusion"].items():
        v, ph = k.split("|")
        out.append(f"| `{short(v)}` {ph} | {c.get('target_block', 0)} | {c.get('later_window_same_leader', 0)} | "
                   f"{c.get('other_leader', 0)} | {c.get('expired', 0)} | {c.get('send_failed', 0)} |")
    return out + [""]


def route_table(res):
    r = res.get("by_route")
    if not r:
        return []
    out = ["### Delivery by route, days A-D (windows)", "",
           "| Ingress | Windows | All probes acknowledged | Endpoint closed the connection | Other send problem | "
           "At least one probe in the target block | Probes on a closed connection: landed / all (fees) |",
           "|---|---|---|---|---|---|---|"]
    for k, c in r.items():
        out.append(f"| {k} | {c['windows']} | {c.get('all_acked', 0)} | {c.get('closed_by_endpoint', 0)} | "
                   f"{c.get('other_send_problem', 0)} | {c.get('any_probe_landed', 0)} | "
                   f"{c.get('of_which_landed', 0)} / {c.get('probes_on_closed_connection', 0)} "
                   f"({c.get('fees_of_those_landed', 0):,}) |")
    return out + [""]


def spend_table(res):
    c = res.get("spend")
    if not c:
        return []
    ops = ", ".join(f"{k} {c['ops_transactions'][k]} tx / {v:,}" for k, v in c["ops_fees"].items())
    d = c["unsolicited_deposits"]
    return ["### Cost check (lamports)", "",
            f"Probe block fees (data/raw): {c['probe_fees']:,}. Operations ({c['audit_file']}): {ops}. "
            f"Total: **{c['total_fees']:,}** of the {c['cap']:,} cap. The audit's on-chain fee total is "
            f"{c['audit_chain_fees']:,}; its balance-based spend is {c['audit_balance_spent']:,} plus {d['count']} "
            f"unsolicited deposits of {d['lamports']:,} = {c['audit_balance_spent'] + d['lamports']:,}. "
            f"All three agree: {'yes' if c['agree'] else 'NO'}. Left in my wallets at the audit: "
            f"{c['left_in_wallets']:,}.", ""]


def runs_table():
    """Date and size of every measurement run, from the raw data."""
    import time
    from . import analyze
    runs = {}
    for w in analyze.load():
        r = runs.setdefault(w["run_id"], {"phase": w["phase"], "windows": 0, "probes": 0, "landed": 0, "fees": 0, "t": []})
        r["windows"] += 1
        for q in w["probes"]:
            r["probes"] += 1
            r["landed"] += q.get("outcome") == "target_block"
            r["fees"] += q.get("fee_charged") or 0
            if q.get("sent_ns"):
                r["t"].append(q["sent_ns"])
    utc = lambda ns: time.strftime("%Y-%m-%d %H:%M", time.gmtime(ns / 1e9))
    out = ["### Runs (UTC)", "", "| Run | Phase | First send | Last send | Windows | Probes | In target block | Fees charged (lamports) |",
           "|---|---|---|---|---|---|---|---|"]
    for rid, r in sorted(runs.items(), key=lambda kv: min(kv[1]["t"] or [0])):
        span = (utc(min(r["t"])), utc(max(r["t"]))) if r["t"] else ("—", "—")
        out.append(f"| {rid} | {r['phase']} | {span[0]} | {span[1]} | {r['windows']} | {r['probes']} | {r['landed']} | {r['fees']:,} |")
    return out + [""]


def rng(a):
    return ("—" if not a else str(a[0]) if a[0] == a[1] else f"{a[0]}–{a[1]}")


def exact_table(res):
    out = ["### Exact block order, fully landed K-main windows (descriptive; tied probes may come either way)", "",
           "| Validator | Client | Phase | Full | `agave_int` | `fd_exact` | `total_fee` | Harmonic capped (exploratory) |",
           "|---|---|---|---|---|---|---|---|"]
    for k, r in res.get("exact_orders", {}).items():
        v, ph = k.split("|")
        if ph != "calibration" and r["full"]:
            out.append(f"| `{short(v)}` | {NAMES.get(v, {}).get('family', '?')} | {ph} | {r['full']} | {r['keys']['agave_int']} "
                       f"| {r['keys']['fd_exact']} | {r['keys']['total_fee']} | {r['harmonic_capped']} |")
    return out + [""]


def capsweep_table(res):
    c = res.get("capsweep")
    if not c or not c["windows"]:
        return []
    m, best = c["models"], c["models"]["capped (best X, beta)"]
    out = ["### Harmonic cap sweep (exploratory, runs S-*)", "",
           f"Verdict: **{c['verdict']}**. Fully landed windows: {c['full_windows']} of {c['windows']}.", "",
           "| Model | Matching full windows | X (CU) | beta | Extra CU, 40,000 vs 4,400 limit |", "|---|---|---|---|---|",
           f"| capped, best (X, beta) | {best['matches']} | {rng(best['X'])} | {rng(best['beta'])} | {rng(best['extra_cu_40000_vs_4400'])} |",
           f"| hard cap (beta = 0) | {m['hard_cap']['matches']} | {rng(m['hard_cap']['X'])} | 0 | 0 |",
           f"| no cap (`agave_int`) | {m['no_cap (agave_int)']} | — | 1 | 35,600 |", "",
           "| Panel | Full windows | Observed orders |", "|---|---|---|"]
    for n, p in c["panels"].items():
        out.append(f"| {n} | {p['full_windows']} | {', '.join(f'{o} ×{k}' for o, k in p['orders'].items()) or '—'} |")
    j = c.get("joint")
    if j and j["full_windows"]:
        out += ["", "Consistency check added after the sweep (a fit, not a test: X and beta are chosen on these same "
                "windows): one (X, beta) for all fully landed Harmonic K-main windows, every phase. Best: "
                f"{j['best_matches']} of {j['full_windows']} at X {rng(j['X'])}, beta {rng(j['beta'])} "
                f"(hard cap {j['hard_cap']}, no cap {j['no_cap (agave_int)']}).", "",
                "| Phase, panel | Full windows | Matching at the best (X, beta) |", "|---|---|---|"]
        out += [f"| {g.replace('|', ' / ')} | {v['full_windows']} | {rng(v['matches_at_best'])} |" for g, v in j["groups"].items()]
    return out + [""]


def load_table(res):
    """Pre-registered sensitivity: the best key's pairwise agreement in K-main windows, within thirds of
    block load (transactions per block, cut points per day), pooled over days A-D per client."""
    agg = {}
    for r in res["study_k"].values():
        if r["phase"] not in ("dayA", "dayB", "dayC", "dayD"):
            continue
        for third, v in r["by_block_load"].items():
            if v["windows"] and v["best_key_agreement"] is not None:
                a = agg.setdefault(r["family"], {}).setdefault(third, [0.0, 0])
                a[0] += v["best_key_agreement"] * v["windows"]
                a[1] += v["windows"]
    out = ["### Best key's agreement by block load, days A-D (pairwise share; K-main windows in brackets)", "",
           "| Client | Light third | Middle third | Heavy third |", "|---|---|---|---|"]
    for f in sorted(agg):
        cells = [f"{agg[f][t][0] / agg[f][t][1]:.2f} ({agg[f][t][1]})" if t in agg[f] else "—"
                 for t in ("low", "mid", "high")]
        out.append(f"| {f} | " + " | ".join(cells) + " |")
    return out + [""]


def harmonic_table(res):
    hp = res.get("harmonic_panels")
    if not hp:
        return []
    hv = sorted({k.split("|")[0] for k in res["exact_orders"]
                 if NAMES.get(k.split("|")[0], {}).get("family", "").startswith("Harmonic")})
    out = ["### Harmonic capped order by panel (exploratory, memo #2): matching / full windows, days B-D", "",
           "A panel whose capped order equals its `agave_int` order cannot tell the formula from plain `agave_int`.", "",
           "| Panel | Capped order | `agave_int` order | Same | " + " | ".join(f"`{short(v)}`" for v in hv) + " | All |",
           "|---" * (5 + len(hv)) + "|"]
    for name, h in hp.items():
        cells, tm, tf = [], 0, 0
        for v in hv:
            m = f = 0
            for ph in ("dayB", "dayC", "dayD"):
                r = res["exact_orders"].get(f"{v}|{ph}")
                if r:
                    m += r.get("harmonic_capped_by_panel", {}).get(name, 0)
                    f += sum(n for o, n in r["orders"].items() if o.startswith(name + ":"))
            cells.append(f"{m} / {f}")
            tm, tf = tm + m, tf + f
        out.append(f"| {name} | {h['harmonic_capped']} | {h['agave_int']} | {'yes' if h['same_as_agave_int'] else 'no'} | "
                   + " | ".join(cells) + f" | {tm} / {tf} |")
    return out + [""]


def non_exact_table(res):
    rows = res.get("non_exact")
    if rows is None:
        return []
    out = ["### Full windows not in exact order, days A-D (best key of the validator-day; Harmonic: capped order)", "",
           "| Window | Validator | Client | Slot | Panel | Reference | Observed | Predicted |", "|---|---|---|---|---|---|---|---|"]
    out += [f"| {r['window']} | `{short(r['validator'])}` | {r['client']} | {r['slot']} | {r['panel']} | {r['reference']} | "
            f"{r['observed']} | {r['predicted']} |" for r in rows]
    return out + ([] if rows else ["| none | | | | | | | |"]) + [""]


def versions_table(res):
    vs = res.get("versions")
    if not vs:
        return []
    out = ["### Client versions seen in the gossip snapshots around each window (descriptive)", "",
           "| Validator | Client | Phase | Version: windows (first – last window) | Windows with a version change between snapshots |",
           "|---|---|---|---|---|"]
    for v, phs in vs.items():
        for ph, r in phs.items():
            cell = "; ".join(f"{ver}: {e['windows']} ({e['first']} – {e['last']})" for ver, e in r["versions"].items()) or "—"
            ch = r["changed_between_snapshots"]
            out.append(f"| `{short(v)}` | {NAMES.get(v, {}).get('family', '?')} | {ph} | {cell} | "
                       f"{len(ch)}{(' (' + ', '.join(ch[:4]) + (' …' if len(ch) > 4 else '') + ')') if ch else ''} |")
    return out + [""]


def inclusion_rank_table(res):
    ir = res.get("inclusion_by_rank")
    if not ir:
        return []
    out = ["### Landing in the target block by fee rank in trains, days A-D (PREREG 'Inclusion', descriptive)", "",
           "Rank 1 is the cheapest probe; cells are landed / sent."]
    for sp, by in ir.items():
        n = max(int(k) for r in by.values() for k in r)
        out += ["", f"{sp} trains:", "", "| Ingress | " + " | ".join(str(i) for i in range(1, n + 1)) + " |",
                "|---" * (n + 1) + "|"]
        for ing, r in by.items():
            out.append(f"| {ing} | " + " | ".join(f"{r[str(i)][0]}/{r[str(i)][1]}" if str(i) in r else "—"
                                                  for i in range(1, n + 1)) + " |")
    sp = res.get("send_precision") or {}
    if sp:
        out += ["", "Send precision (realised minus planned gap between consecutive train sends): " + "; ".join(
            f"{k}: {v['gaps']} gaps in {v['trains']} trains, median |deviation| {v['median_abs_dev_ms']} ms, "
            f"{v['gaps_off_by_more_than_1ms']} gaps off by more than 1 ms (in {v['trains_with_such_a_gap']} trains)"
            for k, v in sp.items()) + "."]
    return out + [""]


def null_select_table(res):
    ns = res.get("null_with_selection")
    if not ns:
        return []
    out = ["### Randomisation test with the key re-chosen in every permutation (check added after review)", "",
           "The registered test (PREREG 'No rule') keeps the best key fixed; this check repeats the choice of key "
           "inside each permutation. It applies where no key was identified.", "",
           "| Validator | Phase | Registered p | p with key re-chosen |", "|---|---|---|---|"]
    out += [f"| `{short(k.split('|')[0])}` | {k.split('|')[1]} | {v['registered_p']:.2g} | "
            f"{fmt(v['p_with_selection'], 4) if v['p_with_selection'] is not None else '—'} |" for k, v in ns.items()]
    return out + [""]


def tables_md(res):
    lines = ["# Results tables", "", "Generated by `itb analyze` from `data/raw`. Do not edit by hand.", ""]
    for ph in ("dayA", "dayB", "dayC", "dayD", "calibration"):
        lines += calls_table(res, ph) + contrast_table(res, ph) + order_table(res, ph) + train_table(res, ph)
    lines += (exact_table(res) + harmonic_table(res) + non_exact_table(res) + load_table(res) + capsweep_table(res)
              + null_select_table(res) + versions_table(res) + inclusion_table(res) + inclusion_rank_table(res)
              + route_table(res) + spend_table(res) + runs_table())
    return "\n".join(lines)


def link(p):
    return f"{p['slot']}:{p['index']} [`{p['sig'][:8]}…`](https://explorer.solana.com/tx/{p['sig']})"


def claims_md(res, evidence):
    lines = ["# Claims and their evidence", "",
             "Each row: a claim, the validator, the windows behind it and one landing to look up. "
             "`docker compose up` recomputes every number offline; `docker compose run --rm verify` re-fetches the "
             "blocks from a public RPC (`VERIFY_ALL=1` for all).", "",
             "Columns: *Windows (informative)* is the number of K-main windows, then the smallest number of informative "
             "windows against any rival key (\"31 (27+)\": 31 windows, at least 27 informative against every rival). "
             "*Not exact* counts fully landed windows whose whole order differs from the key (listed in "
             "[tables](data/derived/tables.md), \"Full windows not in exact order\"). *Counterexamples* are windows where "
             "the key lost a decisive contrast, the registered test's unit. \"Not a call\" marks validator-days below "
             "the registered data minimum (15 evaluable panels and 5 informative windows against every rival).", "",
             "## Sort-key calls", "",
             "| # | Claim | Validator | Phase | Windows (informative) | Not exact | Example slot:index / signature | Counterexamples |",
             "|---|---|---|---|---|---|---|---|"]
    miss = Counter((r["validator"], r["phase"]) for r in res.get("non_exact", []) if r["reference"] != "Harmonic capped")
    n = 0
    for ph in ("dayA", "dayB", "dayC", "dayD"):
        for v, r in sorted(res["calls"].get(ph, {}).items()):
            if not r.get("identified"):
                continue
            n += 1
            ev = evidence.get((v, ph), {})
            claim = (f"`{short(v)}` consistent with `{r['key']}` (insufficient data; not a call)"
                     if r["verdict"] == "insufficient data" else
                     f"`{short(v)}` orders queued probes by `{r['key']}` ({r['verdict']}; min win rate {fmt(r['min_rate'])})")
            hold = res.get("holdout", {}).get(ph, {}).get(v, {})
            if hold.get("status") == "failed":
                claim += f"; exploratory: the registered prediction (`{hold['predicted']}`) failed"
            lines.append(f"| {n} | {claim} | `{v}` | {ph} | {ev.get('windows', 0)} ({r['min_n']}+) | {miss[(v, ph)]} | "
                         f"{ev.get('example', '—')} | {', '.join(ev.get('counter', [])[:5]) or 'none'} |")
    if n == 0:
        lines.append("| — | No confirmatory claims yet (calibration data only). | | | | | | |")
    lines += ["", "## Other findings", "",
              "| # | Claim | Validator | Phase | Evidence | Example slot:index / signature | Exceptions |",
              "|---|---|---|---|---|---|---|"]
    m = 0
    hp = res.get("harmonic_panels", {})
    disc = [k for k, h in hp.items() if not h["same_as_agave_int"]]
    harm = [r for r in res.get("non_exact", []) if r["reference"] == "Harmonic capped" and r["phase"] != "dayA"]
    for v in sorted({k.split("|")[0] for k in res.get("exact_orders", {})
                     if NAMES.get(k.split("|")[0], {}).get("family", "").startswith("Harmonic")}):
        mt = ft = md = fd = 0
        for ph in ("dayB", "dayC", "dayD"):
            r = res["exact_orders"].get(f"{v}|{ph}")
            if not r:
                continue
            mt, ft = mt + r["harmonic_capped"], ft + r["full"]
            md += sum(r.get("harmonic_capped_by_panel", {}).get(k, 0) for k in disc)
            fd += sum(c for o, c in r["orders"].items() if o.split(":")[0] in disc)
        if not ft:
            continue
        m += 1
        ex = [w for w in harm if w["validator"] == v]
        lines.append(f"| H{m} | `{short(v)}` puts queued probes in the capped-Agave order fixed by memo #2 (exploratory) | "
                     f"`{v}` | days B–D | {mt} / {ft} full windows; on {', '.join(disc)} (where the order differs from "
                     f"`agave_int`) {md} / {fd} | {evidence.get(('harmonic', v), '—')} | "
                     f"{', '.join(w['window'] for w in ex[:5]) or 'none'} |")
    c = res.get("capsweep") or {}
    if c.get("full_windows"):
        b, mods = c["models"]["capped (best X, beta)"], c["models"]
        m += 1
        lines.append(f"| H{m} | Harmonic counts the CU limit above a cap X only in part (soft cap; exploratory, memo #3) | "
                     f"four Harmonic validators | 11-02 | {b['matches']} / {c['full_windows']} full windows at X {rng(b['X'])}, "
                     f"beta {rng(b['beta'])}; hard cap {mods['hard_cap']['matches']}, plain `agave_int` "
                     f"{mods['no_cap (agave_int)']} | {evidence.get(('capsweep',), '—')} | "
                     f"{c['full_windows'] - b['matches']} windows |")
    fd_pairs = later = 0
    for r in res["study_k"].values():
        if r["family"] == "Firedancer" and r["phase"] in ("dayA", "dayB", "dayC", "dayD"):
            so = r["send_order"]["K-null"]
            fd_pairs += so["pairs"]
            later += so["pairs"] - so["agree"]
    if fd_pairs:
        m += 1
        ex = evidence.get(("ties",), {})
        lines.append(f"| H{m} | Firedancer puts the later-sent of two identical probes first (K-null, descriptive) | both Firedancer "
                     f"validators | days A–D | {later} / {fd_pairs} same-block pairs | {ex.get('example', '—')} | "
                     f"{', '.join(ex.get('counter', [])[:5]) or 'none'} |")
    for k, r in sorted(res["study_m"].items(), key=lambda kv: (kv[1]["family"], kv[1]["phase"])):
        inc = r["increasing"]
        if r["phase"] == "calibration" or not inc["trains"]:
            continue
        m += 1
        lines.append(f"| H{m} | `{short(r['validator'])}` overtaking horizon {'≥' if inc.get('censored') else ''}"
                     f"{fmt(inc['horizon_ms'], 0)} ms "
                     f"({'one train' if inc['trains'] == 1 else str(inc['trains']) + ' trains'}) | `{r['validator']}` | "
                     f"{r['phase']} | {inc['trains']} evaluable rising-fee train{'s' if inc['trains'] != 1 else ''} | "
                     f"{evidence.get(('train', k), '—')} | — |")
    return "\n".join(lines) + "\n"


def evidence_from_raw():
    """Window IDs, an example landing and counterexample windows for each claim."""
    from . import analyze
    from .design import panels_from_json
    from .orders import full_order
    panels = panels_from_json(json.loads((ROOT / "design" / "panels.json").read_text())["panels"])
    res = json.loads((DERIVED / "results.json").read_text())
    out = {}
    windows = analyze.load()
    for ph in ("dayA", "dayB", "dayC", "dayD"):
        for v, r in res["calls"].get(ph, {}).items():
            ws = [w for w in windows if w["target"] == v and w["phase"] == ph and w["study"] == "K"
                  and w["arm"] == "K-main" and w["status"] != "transition"]
            counter, example = [], None
            for w in ws:
                cs = analyze.window_contrasts(w, panels[w["panel"]])
                lost = [kp for kp, s in cs.items() if r["key"] in kp and (s > 0) != (kp[0] == r["key"])]
                if lost:
                    counter.append(w["window_id"])
                if example is None and cs:
                    example = link(next(p for p in w["probes"] if p.get("index") is not None))
            out[(v, ph)] = {"windows": len(ws), "counter": counter, "example": example}
    ties = {"counter": [], "example": None}
    for w in sorted(windows, key=lambda w: w["window_id"]):
        if w.get("study") != "K" or w.get("status") == "transition":
            continue
        fam = str(w.get("client", ""))
        if fam.startswith("Harmonic") and w["arm"] == "K-main" and w["phase"] in ("dayB", "dayC", "dayD") \
                and ("harmonic", w["target"]) not in out and full_order(w):
            out[("harmonic", w["target"])] = link(full_order(w)[0])
        if w["phase"] == "capsweep" and ("capsweep",) not in out and full_order(w):
            out[("capsweep",)] = link(full_order(w)[0])
        if fam == "Firedancer" and w["arm"] == "K-null" and w["phase"] in ("dayA", "dayB", "dayC", "dayD"):
            rank = {lab: i for i, lab in enumerate(w["send_order"])}
            seqs = analyze.block_orders(w).values()
            if any(rank[s[i]] < rank[s[j]] for s in seqs for i in range(len(s)) for j in range(i + 1, len(s))):
                ties["counter"].append(w["window_id"])
            if ties["example"] is None and any(len(s) >= 2 for s in seqs):
                ties["example"] = link(next(p for p in w["probes"] if p.get("index") is not None))
    out[("ties",)] = ties
    from .trains import evaluable_train
    for w in sorted(windows, key=lambda w: w["window_id"]):
        k = f"{w['target']}|{w['phase']}"
        if w.get("study") == "M" and w["arm"] == "M-inc" and ("train", k) not in out and evaluable_train(w):
            out[("train", k)] = link(next(p for p in sorted(w["probes"], key=lambda p: p["label"])
                                          if p.get("outcome") == "target_block"))
    return out


def figures(res):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    FIG.mkdir(exist_ok=True)
    plt.rcParams.update({"font.size": 9, "svg.hashsalt": "itb", "font.family": "DejaVu Sans"})
    for ph in ("dayA", "calibration"):
        rows = [r for r in res["study_k"].values() if r["phase"] == ph]
        if rows:
            break
    if rows:
        rows.sort(key=lambda r: (r["family"], r["validator"]))
        data = [[r["keys"][k]["min_rate"] if r["keys"][k]["min_rate"] is not None else float("nan") for k in KEY_ORDER]
                for r in rows]
        fig, ax = plt.subplots(figsize=(7.5, 0.35 * len(rows) + 1.6))
        im = ax.imshow(data, vmin=0, vmax=1, cmap="Greys", aspect="auto")
        ax.set_xticks(range(len(KEY_ORDER)), KEY_ORDER, rotation=35, ha="right")
        ax.set_yticks(range(len(rows)), [f"{r['family']} {short(r['validator'])}" for r in rows])
        for i, row in enumerate(data):
            for j, x in enumerate(row):
                if x == x:
                    ax.text(j, i, f"{x:.2f}", ha="center", va="center", color="white" if x > 0.6 else "black", fontsize=7)
        ax.set_title(f"Worst-case win rate of each candidate key against its rivals ({ph})")
        fig.colorbar(im, ax=ax, fraction=0.03)
        fig.tight_layout()
        fig.savefig(FIG / "keys.svg", metadata={"Date": None})
        plt.close(fig)
    mrows = [r for r in res["study_m"].values() if r["increasing"]["gaps"]]
    if mrows:
        fig, ax = plt.subplots(figsize=(6.5, 3.6))
        for r in sorted(mrows, key=lambda r: r["family"]):
            inc = r["increasing"]
            ax.plot(inc["gaps"], inc["rate"], marker="o", ms=3, label=f"{r['family']} {short(r['validator'])} ({r['phase']})")
        ax.axhline(0.5, color="grey", lw=0.8, ls="--")
        ax.set_xlabel("send gap between two train probes (ms)")
        ax.set_ylabel("share where the later, higher-fee probe came first")
        ax.set_ylim(-0.05, 1.05)
        ax.legend(fontsize=6, frameon=False)
        fig.tight_layout()
        fig.savefig(FIG / "overtaking.svg", metadata={"Date": None})
        plt.close(fig)
    block_figure(plt)


def pick_block(windows):
    """One real block to explain: the first K-main window (latest phase first) whose six probes all landed in
    one target block, preferring one ordered exactly as fd_exact and not as agave_int (the fingerprint pair)."""
    from fractions import Fraction
    def order(w, key):
        return sorted("ABCDEF", key=lambda lab: (-Fraction(next(p for p in w["probes"] if p["label"] == lab)["keys"][key]), lab))
    full = []
    for w in sorted(windows, key=lambda w: w["window_id"]):
        ps = w["probes"]
        if w.get("arm") == "K-main" and len(ps) == 6 and all(p.get("outcome") == "target_block" for p in ps) \
                and len({p["slot"] for p in ps}) == 1:
            full.append((w, "".join(p["label"] for p in sorted(ps, key=lambda p: p["index"]))))
    for ph in ("dayB", "dayC", "dayA", "dayD", "calibration"):
        cands = [(w, o) for w, o in full if w["phase"] == ph]
        fp = [(w, o) for w, o in cands if o == "".join(order(w, "fd_exact")) != "".join(order(w, "agave_int"))]
        if fp or cands:
            w, o = (fp or cands)[0]
            return w, o, {k: "".join(order(w, k)) for k in KEY_ORDER}
    return None


def block_figure(plt):
    from . import analyze
    got = pick_block(analyze.load())
    if not got:
        return
    w, observed, preds = got
    ps = sorted(w["probes"], key=lambda p: p["index"])
    rows = [("observed", observed)] + list(preds.items())
    fig, ax = plt.subplots(figsize=(6.4, 3.9))
    ax.axis("off")
    ax.set_xlim(-3.2, 6)
    ax.set_ylim(len(rows) + 1.2, -2.4)
    ax.text(-3.2, -2.2, f"Slot {ps[0]['slot']}, leader {short(w['target'])} ({w['client']}), "
            f"{w.get('block_load') or '?'} transactions", fontsize=9, weight="bold")
    ax.text(-3.2, -1.4, f"My six probes (panel {w['panel']}, sent in order {''.join(w['send_order'])}) sat at "
            f"positions {', '.join(str(p['index']) for p in ps)}.", fontsize=8)
    for j in range(6):
        ax.text(j, -0.6, f"{j + 1}.", ha="center", fontsize=7, color="#707070")
    for i, (name, o) in enumerate(rows):
        ax.text(-0.6, i, name, ha="right", va="center", fontsize=8, weight="bold" if i == 0 else "normal")
        for j, lab in enumerate(o):
            hit = i == 0 or lab == observed[j]
            ax.text(j, i, lab, ha="center", va="center", fontsize=9, color="black" if hit else "#b8b8b8",
                    weight="bold" if hit else "normal")
    ax.text(-3.2, len(rows) + 0.6, f"Window {w['window_id']}. Grey letters: the key predicts a different probe "
            "at that position.", fontsize=7, color="#707070")
    fig.tight_layout()
    fig.savefig(FIG / "block.svg", metadata={"Date": None})
    plt.close(fig)

def write_outputs(res, check=True):
    tables = tables_md(res)
    claims = claims_md(res, evidence_from_raw())
    targets = {DERIVED / "tables.md": tables, ROOT / "CLAIMS.md": claims}
    bad = []
    for path, text in targets.items():
        if check and path.exists():
            if path.read_text() != text:
                bad.append(str(path.relative_to(ROOT)))
        else:
            path.write_text(text)
    figures(res)
    if bad:
        print("MISMATCH in generated text: " + ", ".join(bad), file=sys.stderr)
        raise SystemExit(1)
