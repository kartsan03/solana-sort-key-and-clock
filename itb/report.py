"""Tables, CLAIMS.md and figures generated from results.json (deterministic text; figures redrawn)."""
import json
import pathlib
import sys

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
           "| Validator | Client | Trains (evaluable) | Horizon ms [95% CI] | Decreasing-arm scramble rate |", "|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: r["family"]):
        inc, dec = r["increasing"], r["decreasing"]
        ci = inc["horizon_ci"]
        scr = [x for x in dec["rate"] if x == x]
        out.append(f"| `{short(r['validator'])}` | {r['family']} | {r['trains']} ({r['evaluable']}) | "
                   f"{fmt(inc['horizon_ms'], 0)} [{fmt(ci[0], 0) if ci else '—'}, {fmt(ci[1], 0) if ci else '—'}] | "
                   f"{fmt(sum(scr) / len(scr)) if scr else '—'} |")
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
        out += [f"| {g} | {v['full_windows']} | {rng(v['matches_at_best'])} |" for g, v in j["groups"].items()]
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


def tables_md(res):
    lines = ["# Results tables", "", "Generated by `itb analyze` from `data/raw`. Do not edit by hand.", ""]
    for ph in ("dayA", "dayB", "dayC", "dayD", "calibration"):
        lines += calls_table(res, ph) + contrast_table(res, ph) + order_table(res, ph) + train_table(res, ph)
    lines += exact_table(res) + load_table(res) + capsweep_table(res) + inclusion_table(res) + route_table(res) + spend_table(res) + runs_table()
    return "\n".join(lines)


def claims_md(res, evidence):
    lines = ["# Claims and their evidence", "",
             "Each row: what we claim, for which validator, on which windows, and how to re-check it.",
             "`docker compose up` recomputes every number offline; `docker compose run --rm verify` "
             "re-fetches the blocks from a public RPC (`VERIFY_ALL=1` for all).", "",
             "| # | Claim | Validator | Phase | Windows (informative) | Example slot:index / signature | Counterexample windows |",
             "|---|---|---|---|---|---|---|"]
    n = 0
    for ph in ("dayA", "dayB", "dayC", "dayD"):
        for v, r in sorted(res["calls"].get(ph, {}).items()):
            if not r.get("identified"):
                continue
            n += 1
            ev = evidence.get((v, ph), {})
            lines.append(f"| {n} | `{short(v)}` orders queued probes by `{r['key']}` ({r['verdict']}; min win rate "
                         f"{fmt(r['min_rate'])}) | `{v}` | {ph} | {ev.get('windows', 0)} ({r['min_n']}+) | "
                         f"{ev.get('example', '—')} | {', '.join(ev.get('counter', [])[:5]) or 'none'} |")
    if n == 0:
        lines.append("| — | No confirmatory claims yet (calibration data only). | | | | | |")
    return "\n".join(lines) + "\n"


def evidence_from_raw():
    """Window IDs, an example landing and counterexample windows for each (validator, phase) call."""
    from . import analyze
    from .design import panels_from_json
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
                    p = next(p for p in w["probes"] if p.get("index") is not None)
                    example = f"{p['slot']}:{p['index']} `{p['sig'][:16]}…`"
            out[(v, ph)] = {"windows": len(ws), "counter": counter, "example": example}
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
