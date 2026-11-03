"""Descriptive exact-order counts (not a registered test): in how many fully landed K-main windows did the whole
block order of the six probes agree with each candidate key? Ties in a key may come in either order.

Also counts the exploratory Harmonic order fixed in design/predictions-dayB.json before day B (memo #2): Agave
integer priority with the compute-unit limit counted only up to a cap X, 1660 <= X <= 4098."""
import json
from collections import Counter
from fractions import Fraction

from .probe import KEYS

ECONOMIC = [k for k in KEYS if k not in ("fifo", "random")]


def full_order(w):
    got = [p for p in w["probes"] if p.get("outcome") == "target_block" and p.get("index") is not None]
    if len(got) == 6 and len({p["slot"] for p in got}) == 1:
        return sorted(got, key=lambda p: p["index"])
    return None


def exact_orders(windows, root):
    pred = json.loads((root / "design" / "predictions-dayB.json").read_text())["exploratory"]["predicted_order"]
    out = {}
    for w in windows:
        if w.get("study") != "K" or w.get("arm") != "K-main" or w.get("status") != "stable" or w["phase"] == "capsweep":
            continue
        r = out.setdefault(f"{w['target']}|{w['phase']}", {"full": 0, "incomplete": 0, "keys": Counter(),
                                                           "harmonic_capped": 0, "orders": Counter()})
        ps = full_order(w)
        if ps is None:
            r["incomplete"] += 1
            continue
        obs = "".join(p["label"] for p in ps)
        r["full"] += 1
        r["orders"][f"{w['panel']}:{obs}"] += 1
        r["harmonic_capped"] += obs == pred.get(w["panel"])
        r.setdefault("harmonic_capped_by_panel", Counter())[w["panel"]] += obs == pred.get(w["panel"])
        for k in ECONOMIC:
            v = [Fraction(p["keys"][k]) for p in ps]
            r["keys"][k] += all(v[i] >= v[j] for i in range(6) for j in range(i + 1, 6))
    return {k: {**v, "keys": {x: v["keys"][x] for x in ECONOMIC}, "orders": dict(sorted(v["orders"].items())),
                **({"harmonic_capped_by_panel": dict(sorted(v["harmonic_capped_by_panel"].items()))}
                   if "harmonic_capped_by_panel" in v else {})}
            for k, v in sorted(out.items())}


def key_order(panel, key):
    """Labels from first to last under `key` (higher value first; ties by label)."""
    return "".join(sorted(panel, key=lambda lab: (-KEYS[key](panel[lab]), lab)))


def harmonic_panels(root):
    """Per fixed panel: the exploratory Harmonic order (memo #2), the agave_int order computed from the panel,
    and whether they coincide (a panel where they do cannot tell the formula from plain agave_int)."""
    from .design import panels_from_json
    pred = json.loads((root / "design" / "predictions-dayB.json").read_text())["exploratory"]["predicted_order"]
    panels = panels_from_json(json.loads((root / "design" / "panels.json").read_text())["panels"])
    out = {}
    for name, pnl in sorted(panels.items()):
        ai = key_order(pnl, "agave_int")
        out[name] = {"harmonic_capped": pred.get(name), "agave_int": ai, "same_as_agave_int": pred.get(name) == ai}
    return out


def is_harmonic(w):
    return str(w.get("client", "")).startswith("Harmonic")


def non_exact(windows, best, root):
    """Every fully landed, stable K-main window of days A-D whose block order is not exactly its validator-day's
    best key (Harmonic validators: the exploratory capped order). Ties in a key may come either way."""
    pred = json.loads((root / "design" / "predictions-dayB.json").read_text())["exploratory"]["predicted_order"]
    out = []
    for w in sorted(windows, key=lambda w: w["window_id"]):
        if w.get("study") != "K" or w.get("arm") != "K-main" or w.get("status") != "stable" \
                or w["phase"] not in ("dayA", "dayB", "dayC", "dayD"):
            continue
        ps = full_order(w)
        if ps is None:
            continue
        obs = "".join(p["label"] for p in ps)
        if is_harmonic(w):
            ref, want = "Harmonic capped", pred.get(w["panel"])
            ok = obs == want
        else:
            ref = best.get(f"{w['target']}|{w['phase']}")
            if ref is None:
                continue
            v = [Fraction(p["keys"][ref]) for p in ps]
            ok = all(v[i] >= v[j] for i in range(6) for j in range(i + 1, 6))
            want = "".join(p["label"] for p in sorted(ps, key=lambda p: (-Fraction(p["keys"][ref]), p["label"])))
        if not ok:
            out.append({"window": w["window_id"], "validator": w["target"], "client": w.get("client"),
                        "phase": w["phase"], "slot": ps[0]["slot"], "panel": w["panel"], "reference": ref,
                        "observed": obs, "predicted": want})
    return out


def versions_seen(windows):
    """Per validator and phase: each client version seen in the snapshots around its windows (first and last
    window), and windows whose snapshots before and after the send show different versions."""
    out = {}
    for w in sorted(windows, key=lambda w: w["window_id"]):
        r = out.setdefault(w["target"], {}).setdefault(w["phase"], {"versions": {}, "changed_between_snapshots": []})
        for ver in dict.fromkeys(x for x in w.get("versions", []) if x):
            e = r["versions"].setdefault(ver, {"windows": 0, "first": w["window_id"], "last": w["window_id"]})
            e["windows"] += 1
            e["last"] = w["window_id"]
        b, a = (w.get("versions") or [None, None])
        if b and a and b != a:
            r["changed_between_snapshots"].append(w["window_id"])
    return {v: dict(sorted(ph.items())) for v, ph in sorted(out.items())}


def by_route(windows):
    """Per ingress kind (own IP, BAM node, Harmonic endpoint), days A-D: windows whose probes were all
    acknowledged, windows where the endpoint closed our connection ("closed:<code>:<reason>"), windows with
    another send problem (error, no answer), and windows with at least one probe in the target block."""
    out = {}
    for w in windows:
        if w["phase"] not in ("dayA", "dayB", "dayC", "dayD"):
            continue
        acks = [str(p.get("ack")) for p in w["probes"]]
        r = out.setdefault(w.get("ingress") or "unknown", Counter())
        r["windows"] += 1
        if any(a.startswith("closed") for a in acks):
            r["closed_by_endpoint"] += 1
        elif all(a == "acked" for a in acks):
            r["all_acked"] += 1
        else:
            r["other_send_problem"] += 1
        r["any_probe_landed"] += any(p.get("outcome") == "target_block" for p in w["probes"])
        for p, a in zip(w["probes"], acks):
            if a.startswith("closed"):                      # a closed stream can still have delivered the probe
                r["probes_on_closed_connection"] += 1
                r["of_which_landed"] += p.get("outcome") == "target_block"
                r["fees_of_those_landed"] += p.get("fee_charged") or 0
    return {k: dict(v) for k, v in sorted(out.items())}
