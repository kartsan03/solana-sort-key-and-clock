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
        for k in ECONOMIC:
            v = [Fraction(p["keys"][k]) for p in ps]
            r["keys"][k] += all(v[i] >= v[j] for i in range(6) for j in range(i + 1, 6))
    return {k: {**v, "keys": {x: v["keys"][x] for x in ECONOMIC}, "orders": dict(sorted(v["orders"].items()))}
            for k, v in sorted(out.items())}


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
    return {k: dict(v) for k, v in sorted(out.items())}
