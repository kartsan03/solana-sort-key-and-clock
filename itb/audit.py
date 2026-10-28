"""Three-way cost check, read-only: ledger spend = fees our transactions paid on chain = change in wallet
balances. Also lists every transaction touching our wallets that the ledger does not know (e.g. a stranger's
deposit, which would otherwise hide spend). Writes data/audit/audit-<UTC>.json."""
import json
import time
from collections import defaultdict

from .cli import ROOT


async def history(rpc, wallet, since_slot):
    """All signatures touching `wallet` from `since_slot` on (paginated past 1,000)."""
    out, before = [], None
    while True:
        page = await rpc.call("getSignaturesForAddress", wallet, {"limit": 1000, **({"before": before} if before else {})})
        out += [s["signature"] for s in page if s["slot"] >= since_slot]
        if len(page) < 1000 or page[-1]["slot"] < since_slot:
            return out
        before = page[-1]["signature"]


async def audit(rpc, led):
    from .analyze import load
    wallets, base = led.get("wallets"), led.get("baseline")
    txs = {t["sig"]: t for t in led.txs()}
    flow_sigs = {r[0] for r in led.db.execute("SELECT sig FROM flows")}
    raw_fee = {p["sig"]: p["fee_charged"] for w in load() for p in w["probes"] if p.get("fee_charged")}
    st = await rpc.signature_statuses(list(txs))
    runs = defaultdict(lambda: {"txs": 0, "landed": 0, "fees": 0})
    fees = 0
    for sig, t in txs.items():
        r = runs[t["run_id"]]
        r["txs"] += 1
        s = st.get(sig)
        if not (s and s.get("confirmationStatus") == "finalized"):
            continue
        fee = raw_fee.get(sig)
        if fee is None:   # ops transactions, or a probe that landed outside the collected blocks
            fee = (await rpc.transaction(sig))["meta"]["fee"]
        r["landed"] += 1
        r["fees"] += fee
        fees += fee
    unknown = []
    ws = set(wallets)
    for w in wallets:
        for sig in await history(rpc, w, base["slot"]):
            if sig in txs or sig in flow_sigs or any(u["sig"] == sig for u in unknown):
                continue
            t = await rpc.transaction(sig)
            keys = t["transaction"]["message"]["accountKeys"]
            m = t["meta"]
            unknown.append({"sig": sig, "slot": t["slot"], "fee_payer": keys[0],
                            "deltas": {k: b - a for k, a, b in zip(keys, m["preBalances"], m["postBalances"])
                                       if k in ws and a != b}})
    bal, slot = await rpc.balances(wallets, "finalized")
    total = sum(bal[w] for w in wallets)
    out = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "slot": slot,
           "ledger_spent": led.spent(), "ledger_reserved": led.reserved(), "fees_on_chain": fees,
           "balance_spent": base["total"] + led.flows_total() - total, "balance_total": total,
           "unknown_transactions": unknown, "runs": dict(sorted(runs.items()))}
    out["consistent"] = out["ledger_spent"] == out["fees_on_chain"] == out["balance_spent"] and not unknown
    path = ROOT / "data" / "audit" / f"audit-{out['utc'].replace(':', '')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1))
    return out, path
