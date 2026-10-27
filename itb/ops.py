"""Wallet operations: status, reconciliation, payer funding, memos, inflows, sweep.

Ops transactions go through RPC sendTransaction (they are not measurements) and are
reserved in the ledger like every probe.
"""
import asyncio
import base64
import time

from solders.hash import Hash
from solders.pubkey import Pubkey

from .probe import LAMPORTS_PER_SIGNATURE, memo_ix, plain_tx, transfer_ix

SWEEP_TARGET = "kept-out-of-the-repo"     # owner's main wallet
NEVER_SEND_TO = {"kept-out-of-the-repo"}   # exchange deposit that funded the burner
RENT_0 = 650_240


async def balances(rpc, pubkeys, commitment="finalized"):
    bal, slot = await rpc.balances(pubkeys, commitment)
    return bal, slot


async def reconcile(rpc, ledger, pubkeys, note=""):
    bal, slot = await balances(rpc, pubkeys)
    height = await rpc.block_height("finalized")
    return ledger.reconcile(bal, height, slot, note), bal


async def submit(rpc, ledger, tx, kind, run_id, info=None, run_limit=None, log=print):
    """Reserve, send via RPC, and wait until finalized or expired. Returns (sig, landed)."""
    raw = bytes(tx)
    sig = str(tx.signatures[0])
    nsig = len(tx.signatures)
    lv = info.pop("_last_valid")
    ledger.reserve([{"sig": sig, "run_id": run_id, "kind": kind, "payer": str(tx.message.account_keys[0]),
                     "max_fee": LAMPORTS_PER_SIGNATURE * nsig, "last_valid": lv, "raw": raw, "info": info or {}}],
                   run_limit=run_limit)
    await rpc.call("sendTransaction", base64.b64encode(raw).decode(),
                   {"encoding": "base64", "preflightCommitment": "confirmed", "maxRetries": 10})
    ledger.mark_sent(sig, time.time_ns(), "rpc")
    while True:
        await asyncio.sleep(2)
        st = (await rpc.signature_statuses([sig]))[sig]
        if st and st.get("confirmationStatus") == "finalized":
            if st.get("err"):
                log(f"{kind} {sig} landed with error {st['err']}")
            return sig, st.get("err") is None
        if await rpc.block_height("finalized") > lv:
            log(f"{kind} {sig} expired")
            return sig, False


async def fresh_blockhash(rpc):
    bh, lv, _ = await rpc.latest_blockhash("confirmed")
    return Hash.from_string(bh), lv


async def fund_payers(rpc, ledger, payers, float_lamports, run_id, log=print):
    """Top payers 1..11 up to rent + float from the burner, in one transaction."""
    burner = payers[0]
    pks = [str(k.pubkey()) for k in payers]
    bal, _ = await balances(rpc, pks, "confirmed")
    target = RENT_0 + float_lamports
    ixs = [transfer_ix(burner.pubkey(), k.pubkey(), target - bal[str(k.pubkey())])
           for k in payers[1:] if bal[str(k.pubkey())] < target - 50_000]
    if not ixs:
        log("all payers already funded")
        return None
    bh, lv = await fresh_blockhash(rpc)
    tx = plain_tx(burner, ixs, bh, L=150 * len(ixs) + 300)
    sig, ok = await submit(rpc, ledger, tx, "fund", run_id, {"n": len(ixs), "target": target, "_last_valid": lv}, log=log)
    log(f"fund {len(ixs)} payers to {target}: {sig} ok={ok}")
    return sig


async def memo(rpc, ledger, burner, text, run_id, log=print):
    bh, lv = await fresh_blockhash(rpc)
    tx = plain_tx(burner, [memo_ix(text, burner.pubkey())], bh, L=100_000)
    sig, ok = await submit(rpc, ledger, tx, "memo", run_id, {"text": text, "_last_valid": lv}, log=log)
    log(f"memo {sig} ok={ok}: {text}")
    return sig, ok


async def inflow(rpc, ledger, sig, pubkeys, note):
    """Record an external deposit into one of our wallets (verified on chain)."""
    t = await rpc.transaction(sig)
    keys = t["transaction"]["message"]["accountKeys"]
    if keys[0] in pubkeys:
        raise SystemExit("fee payer is one of our wallets: not an external inflow")
    pre, post = t["meta"]["preBalances"], t["meta"]["postBalances"]
    amount = sum(post[i] - pre[i] for i, k in enumerate(keys) if k in pubkeys)
    if amount <= 0:
        raise SystemExit("no lamports arrived in our wallets")
    ledger.record_flow("in", sig, amount, note)
    return amount


async def sweep(rpc, ledger, payers, run_id, dest=SWEEP_TARGET, log=print):
    """Move everything to the owner's main wallet: each payer pays its own fee and ends at 0."""
    if dest in NEVER_SEND_TO or dest != SWEEP_TARGET:
        raise SystemExit(f"refusing to sweep to {dest}")
    to = Pubkey.from_string(dest)
    pks = [str(k.pubkey()) for k in payers]
    order = payers[1:] + payers[:1]        # burner last
    for kp in order:
        bal, _ = await balances(rpc, [str(kp.pubkey())], "confirmed")
        amount = bal[str(kp.pubkey())] - LAMPORTS_PER_SIGNATURE
        if amount <= 0:
            continue
        bh, lv = await fresh_blockhash(rpc)
        tx = plain_tx(kp, [transfer_ix(kp.pubkey(), to, amount)], bh, L=450)
        sig, ok = await submit(rpc, ledger, tx, "sweep", run_id, {"amount": amount, "to": dest, "_last_valid": lv},
                               log=log)
        if ok:
            ledger.record_flow("out", sig, amount, f"sweep {kp.pubkey()} -> {dest}")
        log(f"sweep {str(kp.pubkey())[:8]} -> {dest[:8]} {amount} lamports: {sig} ok={ok}")
    return await balances(rpc, pks, "finalized")
