"""Golden vectors for cost, fee and priority (Agave v4.3.2 / Firedancer v26.10.4 constants)."""
from fractions import Fraction

from solders.hash import Hash
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from itb.probe import (BASE_COST, KEYS, Probe, decode_budget, general_cost, predicted_order, priority_fee,
                       probe_tx)


def test_constants_match_both_clients():
    # 720 per signature + 300 per write lock x2 + 31 data bytes // 4
    assert BASE_COST == 720 + 600 + 7 == 1327
    assert general_cost(1, 2, 31, 700, 32768) == Probe(700, 0, 32768).cost == 2035
    # default 64 MiB loaded-data limit adds 16,384 (Agave block_cost_limits, fd_pack_cost.h)
    assert Probe(700, 0, 64 * 1024 * 1024).cost == 1327 + 700 + 16384


def test_priority_fee_units():
    # p is micro-lamports per CU; pf is lamports, rounded up
    assert priority_fee(700, 2_000_000) == 1400
    assert priority_fee(1, 1) == 1          # ceil(1e-6) = 1 lamport
    assert priority_fee(1_000, 999) == 1    # ceil(0.999)
    assert priority_fee(1_000, 1_000) == 1
    assert priority_fee(1_000, 1_001) == 2
    assert priority_fee(2700, 909_260) == 2456  # ceil(2455.002)
    assert Probe(700, 2_000_000, 32768).fee == 6400  # matches simulateTransaction fee on mainnet, 2026-10-27


def test_example_panel_orders():
    P = {"A": Probe(700, 0, 32768), "B": Probe(700, 2_000_000, 32768), "C": Probe(1400, 1_500_000, 32768),
         "D": Probe(700, 3_000_000, 64 * 1024 * 1024), "E": Probe(3000, 600_000, 32768), "F": Probe(2700, 909_260, 32768)}
    flat = lambda k: " ".join("".join(g) if len(g) == 1 else "{" + "".join(g) + "}" for g in predicted_order(k, P))
    assert flat("agave_int") == "B C F A E D"
    assert flat("fd_exact") == "B C A F E D"       # the A/F fingerprint
    assert flat("fee_per_cost") == "B C A F E D"   # same as fd_exact on this panel (Sol's point)
    assert flat("pf_per_cost") == "C B F E D A"
    assert flat("cu_price") == "D B C F E A"
    assert flat("total_fee") == "F {CD} E B A"
    assert flat("fee_per_cu") == "D B A C F E"
    assert flat("cheapest") == "{AB} C F E D"
    # exact values behind the A/F flip
    assert KEYS["agave_int"](P["A"]) == 2500 * 10**6 // 2036 == 1227897
    assert KEYS["agave_int"](P["F"]) == 4956 * 10**6 // 4036 == 1227948
    assert KEYS["fd_exact"](P["A"]) == Fraction(2500, 2035) > Fraction(4956, 4035) == KEYS["fd_exact"](P["F"])


def test_wire_format_roundtrip():
    kp = Keypair.from_seed(bytes(32))
    lock = Pubkey.from_bytes(bytes([7]) * 32)
    q = Probe(1500, 226_667, 32768)
    tx = probe_tx(kp, lock, q, Hash.default())
    m = tx.message
    assert m.header.num_required_signatures == 1 and m.header.num_readonly_unsigned_accounts == 2
    keys = [str(k) for k in m.account_keys]
    assert keys[:2] == [str(kp.pubkey()), str(lock)]
    assert sum(len(ix.data) for ix in m.instructions) == 31
    assert decode_budget(keys, [(ix.program_id_index, bytes(ix.data)) for ix in m.instructions]) == {
        "L": 1500, "p": 226_667, "D": 32768}
    assert len(bytes(tx)) == 275
