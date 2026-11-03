"""Wallet operations: status, reconciliation, payer funding, memos, inflows, sweep.

Ops transactions go through RPC sendTransaction (they are not measurements) and are
reserved in the ledger like every probe.
"""
import asyncio
import base64
import hashlib
import time

from solders.hash import Hash
from solders.pubkey import Pubkey

from .cluster import local_setting
from .probe import LAMPORTS_PER_SIGNATURE, memo_ix, plain_tx, transfer_ix

# The sweep destination (the owner's wallet) is kept out of the repo: it comes from ITB_SWEEP_TO and must
# match the SHA-256 pinned here; addresses we must never pay are pinned the same way.
SWEEP_TARGET_SHA256 = "fc9df4d73104f1113cb6dc720e5b226eecfe6eec955c5ba56bdad7279cbdb404"
NEVER_SEND_SHA256 = {"764de3c7b86218e55781a548f2a2c0a3c7a96578fddec37abfbbb2b837989345"}
RENT_0 = 650_240


async def balances(rpc, pubkeys, commitment="finalized"):
    bal, slot = await rpc.balances(pubkeys, commitment)
    return bal, slot


async def reconcile(rpc, ledger, pubkeys, note=""):
    """Height first, then balances: every reservation released below that height is inside the snapshot.
    Landed fees of the reservations about to be released are counted from the chain as well, so a deposit
    that arrives with them cannot hide spend (the ledger halts instead)."""
    height = await rpc.block_height("finalized")
    bal, slot = await balances(rpc, pubkeys)
    due = ledger.txs("released IS NULL AND last_valid < ?", (height,))
    landed = 0
    if due:
        st = await rpc.signature_statuses([t["sig"] for t in due])
        landed = sum(t["max_fee"] for t in due if st.get(t["sig"]))   # a landed transaction pays its fee, error or not
    return ledger.reconcile(bal, height, slot, note, landed_fee=landed), bal


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


def sweep_target():
    dest = local_setting("ITB_SWEEP_TO") or ""
    h = hashlib.sha256(dest.encode()).hexdigest()
    if h in NEVER_SEND_SHA256 or h != SWEEP_TARGET_SHA256:
        raise SystemExit("sweep refused: ITB_SWEEP_TO is missing or not the pinned destination")
    return dest


def sweep_steps(bal, wallets, fee=LAMPORTS_PER_SIGNATURE, rent=RENT_0):
    """Plan the sweep: [(wallet, fee_wallet, amount)], smallest balance first. A fee payer must stay
    rent-exempt after paying the fee (or end at exactly 0 lamports), so a wallet holding less than
    rent + fee cannot pay its own way out: a richer wallet that is swept later pays its fee instead.
    Wallets that cannot be emptied either way come back as (wallet, None, shortfall)."""
    bal = dict(bal)
    todo = sorted((w for w in wallets if bal[w] > 0), key=lambda w: bal[w])
    out = []
    while todo:
        w = todo.pop(0)
        helpers = [h for h in todo if bal[h] >= rent + 2 * fee]
        if bal[w] - fee >= rent:
            out.append((w, w, bal[w] - fee))
        elif helpers:
            h = max(helpers, key=lambda x: bal[x])
            bal[h] -= 2 * fee
            out.append((w, h, bal[w]))
        else:
            out.append((w, None, rent + fee - bal[w]))
    return out


async def sweep(rpc, ledger, payers, run_id, log=print):
    """Move everything to the owner's main wallet (see sweep_steps for the order and who pays each fee)."""
    dest = sweep_target()
    to = Pubkey.from_string(dest)
    kp = {str(k.pubkey()): k for k in payers}
    pks = list(kp)
    bal, _ = await balances(rpc, pks, "confirmed")
    for w, f, amount in sweep_steps(bal, pks):
        if f is None:
            log(f"sweep {w[:8]}: holds {bal[w]} lamports, under rent + fee; send it at least {amount} lamports, "
                f"record that with `itb ops inflow <sig>`, then sweep again")
            continue
        bh, lv = await fresh_blockhash(rpc)
        tx = plain_tx(kp[f], [transfer_ix(kp[w].pubkey(), to, amount)], bh, L=450,
                      signers=() if f == w else (kp[w],))
        sig, ok = await submit(rpc, ledger, tx, "sweep", run_id, {"amount": amount, "to": dest, "_last_valid": lv},
                               log=log)
        if ok:
            ledger.record_flow("out", sig, amount, f"sweep {w} -> {dest}")
        log(f"sweep {w[:8]} -> {dest[:8]} {amount} lamports (fee paid by {f[:8]}): {sig} ok={ok}")
    return await balances(rpc, pks, "finalized")
