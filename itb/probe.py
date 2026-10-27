"""The probe transaction and the candidate sort keys.

Every probe has the same shape: a legacy transaction with one signature and two
writable accounts (fee payer and a never-funded "lock" address), carrying
SetComputeUnitLimit(L), SetComputeUnitPrice(p), SetLoadedAccountsDataSizeLimit(D)
and a 0-lamport System transfer payer -> lock. Only L, p and D change.

Cost and fee rules follow Agave v4.3.2 (cost-model/, compute-budget/,
runtime/src/bank/fee_distribution.rs) and Firedancer v26.10.4
(src/disco/pack/fd_pack_cost.h, fd_pack.c); both give the same cost for this shape.
"""
from dataclasses import dataclass
from fractions import Fraction
import struct

from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

LAMPORTS_PER_SIGNATURE = 5_000
BURN_PCT = 50
SIGNATURE_COST = 720
WRITE_LOCK_COST = 300
DATA_BYTES_PER_COST = 4
PAGE_BYTES = 32 * 1024
PAGE_COST = 8
MAX_LOADED_DATA = 64 * 1024 * 1024
MAX_CU_LIMIT = 1_400_000

COMPUTE_BUDGET = Pubkey.from_string("ComputeBudget111111111111111111111111111111")
SYSTEM = Pubkey.from_string("11111111111111111111111111111111")
MEMO = Pubkey.from_string("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr")

# 5 (CU limit) + 9 (CU price) + 5 (loaded data limit) + 12 (transfer) bytes
PROBE_DATA_BYTES = 31
BASE_COST = SIGNATURE_COST + 2 * WRITE_LOCK_COST + PROBE_DATA_BYTES // DATA_BYTES_PER_COST  # 1,327
BASE_REWARD = LAMPORTS_PER_SIGNATURE * (100 - BURN_PCT) // 100  # 2,500 to the leader


def pages(D: int) -> int:
    return -(-D // PAGE_BYTES)


def priority_fee(L: int, p: int) -> int:
    """Lamports: ceil(L * p / 1e6), p in micro-lamports per CU."""
    return -(-L * p // 1_000_000)


@dataclass(frozen=True)
class Probe:
    L: int  # requested compute-unit limit
    p: int  # compute-unit price, micro-lamports
    D: int  # requested loaded-accounts data size limit, bytes

    @property
    def pf(self) -> int:
        return priority_fee(self.L, self.p)

    @property
    def cost(self) -> int:
        return BASE_COST + self.L + PAGE_COST * pages(self.D)

    @property
    def fee(self) -> int:
        """Total lamports charged if it lands (also the worst case we reserve)."""
        return LAMPORTS_PER_SIGNATURE + self.pf


# Candidate sort keys: larger value = scheduled earlier. Exact arithmetic only.
KEYS = {
    "agave_int": lambda q: (q.pf + BASE_REWARD) * 1_000_000 // (q.cost + 1),
    "fd_exact": lambda q: Fraction(q.pf + BASE_REWARD, q.cost),
    "pf_per_cost": lambda q: Fraction(q.pf, q.cost),
    "fee_per_cost": lambda q: Fraction(q.pf + LAMPORTS_PER_SIGNATURE, q.cost),
    "cu_price": lambda q: q.p,
    "fee_per_cu": lambda q: Fraction(q.pf + BASE_REWARD, q.L),
    "total_fee": lambda q: q.fee,
    "cheapest": lambda q: -q.cost,
}
ECONOMIC_KEYS = tuple(KEYS)


def predicts(key: str, a: Probe, b: Probe) -> int:
    """+1 if `key` puts a before b, -1 if after, 0 if tied."""
    ka, kb = KEYS[key](a), KEYS[key](b)
    return (ka > kb) - (ka < kb)


def predicted_order(key: str, probes: dict) -> list:
    """Probe labels grouped by rank: [["B"], ["C", "D"], ...]."""
    vals = {lab: KEYS[key](q) for lab, q in probes.items()}
    out = []
    for lab in sorted(vals, key=lambda x: vals[x], reverse=True):
        if out and vals[out[-1][0]] == vals[lab]:
            out[-1].append(lab)
        else:
            out.append([lab])
    return out


# ---- wire format ----

def compute_budget_ixs(L: int, p: int, D: int) -> list:
    return [
        Instruction(COMPUTE_BUDGET, bytes([2]) + struct.pack("<I", L), []),
        Instruction(COMPUTE_BUDGET, bytes([3]) + struct.pack("<Q", p), []),
        Instruction(COMPUTE_BUDGET, bytes([4]) + struct.pack("<I", D), []),
    ]


def transfer_ix(src: Pubkey, dst: Pubkey, lamports: int) -> Instruction:
    data = struct.pack("<IQ", 2, lamports)
    return Instruction(SYSTEM, data, [AccountMeta(src, True, True), AccountMeta(dst, False, True)])


def memo_ix(text: str, signer: Pubkey) -> Instruction:
    return Instruction(MEMO, text.encode(), [AccountMeta(signer, True, False)])


def probe_message(payer: Pubkey, lock: Pubkey, q: Probe, blockhash: Hash) -> Message:
    ixs = compute_budget_ixs(q.L, q.p, q.D) + [transfer_ix(payer, lock, 0)]
    return Message.new_with_blockhash(ixs, payer, blockhash)


def probe_tx(payer: Keypair, lock: Pubkey, q: Probe, blockhash: Hash) -> Transaction:
    return Transaction([payer], probe_message(payer.pubkey(), lock, q, blockhash), blockhash)


def plain_tx(payer: Keypair, ixs: list, blockhash: Hash, L: int = 1_000, p: int = 0) -> Transaction:
    """Ops transaction (funding transfer, memo, sweep) with a small fixed budget."""
    pre = [Instruction(COMPUTE_BUDGET, bytes([2]) + struct.pack("<I", L), [])]
    if p:
        pre.append(Instruction(COMPUTE_BUDGET, bytes([3]) + struct.pack("<Q", p), []))
    msg = Message.new_with_blockhash(pre + ixs, payer.pubkey(), blockhash)
    return Transaction([payer], msg, blockhash)


def decode_budget(account_keys: list, instructions: list) -> dict:
    """Read L, p, D back from a landed transaction's compute-budget instructions.

    `instructions` are (program_id_index, data_bytes) pairs.
    """
    out = {}
    for prog_idx, data in instructions:
        if account_keys[prog_idx] != str(COMPUTE_BUDGET) or not data:
            continue
        tag, body = data[0], data[1:]
        if tag == 2:
            out["L"] = struct.unpack("<I", body[:4])[0]
        elif tag == 3:
            out["p"] = struct.unpack("<Q", body[:8])[0]
        elif tag == 4:
            out["D"] = struct.unpack("<I", body[:4])[0]
    return out


def general_cost(sigs: int, writable: int, data_bytes: int, L: int, D: int) -> int:
    """Agave/Firedancer requested-cost for any legacy transaction with explicit limits."""
    return (SIGNATURE_COST * sigs + WRITE_LOCK_COST * writable + data_bytes // DATA_BYTES_PER_COST
            + min(L, MAX_CU_LIMIT) + PAGE_COST * pages(min(D, MAX_LOADED_DATA)))
