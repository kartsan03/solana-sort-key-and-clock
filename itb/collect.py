"""Find where every probe landed, and keep block excerpts that let anyone re-check it offline.

Outcome per probe (exactly one):
  target_block              landed in one of the target leader's window slots
  later_window_same_leader  landed later, in another window of the same leader
  other_leader              landed in a block led by someone else
  expired                   not found and its blockhash has expired
  send_failed               not found, and the QUIC stream was never acknowledged
"""
import struct

from .probe import COMPUTE_BUDGET

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_IDX = {c: i for i, c in enumerate(B58)}
CB = str(COMPUTE_BUDGET)


def b58decode(s):
    n = 0
    for ch in s:
        n = n * 58 + _IDX[ch]
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\0" * (len(s) - len(s.lstrip("1"))) + raw


def tx_context(t):
    """Raw inputs for priority/cost of one block transaction (never a computed priority).

    [sig12, version, fee, costUnits, cu_limit, price_or_pf, loaded_limit, n_sig, n_writable, data_bytes, failed]
    price_or_pf is the CU price in micro-lamports for legacy/v0 and the priority fee in lamports for v1.
    """
    msg, meta = t["transaction"]["message"], t["meta"] or {}
    ver = t.get("version", "legacy")
    keys = msg["accountKeys"]
    h = msg["header"]
    nsig = h["numRequiredSignatures"]
    loaded = meta.get("loadedAddresses") or {}
    nwr = (nsig - h["numReadonlySignedAccounts"]) + (len(keys) - nsig - h["numReadonlyUnsignedAccounts"]) \
        + len(loaded.get("writable", []))
    data_bytes, L, price, D = 0, None, None, None
    for ix in msg["instructions"]:
        data = b58decode(ix["data"]) if ix["data"] else b""
        data_bytes += len(data)
        if ver != 1 and keys[ix["programIdIndex"]] == CB and data:
            if data[0] == 2 and len(data) >= 5:
                L = struct.unpack("<I", data[1:5])[0]
            elif data[0] == 3 and len(data) >= 9:
                price = struct.unpack("<Q", data[1:9])[0]
            elif data[0] == 4 and len(data) >= 5:
                D = struct.unpack("<I", data[1:5])[0]
    if ver == 1:
        cfg = msg.get("transactionConfig") or {}
        L, price, D = cfg.get("computeUnitLimit"), cfg.get("priorityFee"), cfg.get("loadedAccountsDataSizeLimit")
    return [t["transaction"]["signatures"][0][:12], ver, meta.get("fee"), meta.get("costUnits"), L, price, D,
            nsig, nwr, data_bytes, meta.get("err") is not None]


def block_leader(block):
    for r in block.get("rewards") or []:
        if r.get("rewardType") == "Fee":
            return r["pubkey"]
    return None


def excerpt(slot, block, our_sigs, full=True):
    """Compact, verifiable record of one block. `our_sigs` = signatures of our probes to keep in full."""
    txs = block["transactions"]
    out = {"slot": slot, "blockhash": block["blockhash"], "parent": block["parentSlot"],
           "blockTime": block.get("blockTime"), "blockHeight": block.get("blockHeight"),
           "leader": block_leader(block), "n_tx": len(txs),
           "sum_cost": sum((t["meta"] or {}).get("costUnits") or 0 for t in txs)}
    if full:
        out["ctx"] = [tx_context(t) for t in txs]
    else:
        out["sig12"] = [t["transaction"]["signatures"][0][:12] for t in txs]
    ours = {}
    for i, t in enumerate(txs):
        sig = t["transaction"]["signatures"][0]
        if sig in our_sigs:
            ours[sig] = {"index": i, "tx": t}
    out["ours"] = ours
    return out


async def collect_run(rpc, windows, probes, height_now, log=print):
    """Return (outcomes, blocks) for one run. windows/probes are the run's raw records."""
    sigs = [p["sig"] for p in probes]
    statuses = await rpc.signature_statuses(sigs)
    by_window = {w["window_id"]: w for w in windows}
    landed_slots = {s["slot"] for s in statuses.values() if s}
    window_slots = {w["slot0"] + i for w in windows for i in range(4)}
    want = sorted(landed_slots | window_slots)
    our = set(sigs)
    blocks = {}
    for slot in want:
        b = await rpc.block(slot)
        if b is None:
            blocks[slot] = {"slot": slot, "skipped": True}
            continue
        blocks[slot] = excerpt(slot, b, our, full=slot in landed_slots)
    outcomes = []
    for p in probes:
        w = by_window[p["window_id"]]
        st = statuses.get(p["sig"])
        o = {"sig": p["sig"], "window_id": p["window_id"], "label": p["label"]}
        if st:
            slot = st["slot"]
            blk = blocks.get(slot, {})
            hit = blk.get("ours", {}).get(p["sig"])
            o.update(slot=slot, index=hit["index"] if hit else None, err=st.get("err"),
                     leader=blk.get("leader"))
            if hit:
                meta = hit["tx"]["meta"] or {}
                o.update(fee_charged=meta.get("fee"), cost_units=meta.get("costUnits"),
                         cu_consumed=meta.get("computeUnitsConsumed"))
            if w["slot0"] <= slot < w["slot0"] + 4:
                o["outcome"] = "target_block"
            elif blk.get("leader") == w["target"]:
                o["outcome"] = "later_window_same_leader"
            else:
                o["outcome"] = "other_leader"
        elif height_now > p["last_valid"]:
            ack = (p.get("ack") or "").split(":")[0]
            o["outcome"] = "send_failed" if ack in ("closed", "error", "not_sent") else "expired"
        else:
            o["outcome"] = "pending"
        outcomes.append(o)
    return outcomes, list(blocks.values())
