"""Online re-check of the raw data against the chain (any RPC; public by default).

For each checked probe that landed: the block at its slot still holds our signature at
the recorded index, with the recorded fee payer, fee, leader (the block's fee-reward recipient)
and decoded L/p/D. For each checked window: the leader schedule (getSlotLeaders) assigns all
four slots to the target, every slot of the window is re-fetched, and no other probe of ours
appears in it unrecorded.
"""
import json
import os
import random

from . import analyze
from .chain import Rpc
from .collect import block_leader
from .probe import decode_budget


async def main(sample=40):
    windows = analyze.load()                       # every phase: calibration, days A-D, the cap sweep
    if os.environ.get("VERIFY_ALL") == "1":
        sample = None
    rng = random.Random(7)
    pick = windows if sample is None or sample >= len(windows) else rng.sample(windows, sample)
    rpc = Rpc()
    bad, checked, slots_checked = [], 0, 0
    cache = {}

    async def block(slot):
        if slot not in cache:
            cache[slot] = await rpc.block(slot)
        return cache[slot]

    for w in pick:
        cache.clear()                                    # full blocks are large: keep only this window's
        ours = {p["sig"]: p for p in w["probes"]}
        for p in w["probes"]:
            if p.get("index") is None:
                continue
            b = await block(p["slot"])
            checked += 1
            if b is None:
                bad.append((p["sig"], "block missing"))
                continue
            t = b["transactions"][p["index"]]
            msg = t["transaction"]["message"]
            keys = msg["accountKeys"]
            budget = decode_budget(keys, [(ix["programIdIndex"], analyze_b58(ix["data"])) for ix in msg["instructions"]])
            probs = []
            if t["transaction"]["signatures"][0] != p["sig"]:
                probs.append("signature/index")
            if keys[0] != p["payer"]:
                probs.append("payer")
            if t["meta"]["fee"] != p["fee"]:
                probs.append(f"fee {t['meta']['fee']} != {p['fee']}")
            if budget != {"L": p["L"], "p": p["p"], "D": p["D"]}:
                probs.append(f"budget {budget}")
            if block_leader(b) != p.get("leader"):
                probs.append("leader")
            if probs:
                bad.append((p["sig"], ", ".join(probs)))
        sched = await rpc.call("getSlotLeaders", w["slot0"], 4)
        if set(sched) != {w["target"]}:
            bad.append((w["window_id"], f"leader schedule gives {sorted(set(sched))}, not the target"))
        for s in range(w["slot0"], w["slot0"] + 4):
            b = await block(s)
            slots_checked += 1
            if b is None:
                continue
            for i, t in enumerate(b["transactions"]):
                sig = t["transaction"]["signatures"][0]
                if sig in ours and (ours[sig].get("slot"), ours[sig].get("index")) != (s, i):
                    bad.append((sig, f"unrecorded landing at {s}:{i}"))
    await rpc.close()
    print(json.dumps({"windows": len(pick), "probes_checked": checked, "window_slots_checked": slots_checked,
                      "problems": bad[:50], "n_problems": len(bad)}, indent=1))
    return 1 if bad else 0


def analyze_b58(s):
    from .collect import b58decode
    return b58decode(s) if s else b""
