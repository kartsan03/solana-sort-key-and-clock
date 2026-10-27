"""Block parsing on real mainnet transactions (legacy, v0, v1) captured 2026-10-27."""
import json
import pathlib

from itb.collect import b58decode, block_leader, excerpt, tx_context

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures_block_txs.json").read_text())


def test_versions_present():
    assert set(FIX) == {"legacy", "0", "1"}


def test_context_fields_match_meta():
    for ver, t in FIX.items():
        c = tx_context(t)
        assert c[0] == t["transaction"]["signatures"][0][:12]
        assert str(c[1]) == ver
        assert c[2] == t["meta"]["fee"] and c[3] == t["meta"]["costUnits"]
        assert c[7] == t["transaction"]["message"]["header"]["numRequiredSignatures"]
        assert c[9] == sum(len(b58decode(ix["data"])) for ix in t["transaction"]["message"]["instructions"])


def test_v1_reads_transaction_config():
    t = FIX["1"]
    cfg = t["transaction"]["message"]["transactionConfig"]
    c = tx_context(t)
    assert (c[4], c[5], c[6]) == (cfg["computeUnitLimit"], cfg["priorityFee"], cfg["loadedAccountsDataSizeLimit"])


def test_excerpt_and_leader():
    block = {"blockhash": "h", "parentSlot": 9, "blockTime": 1, "blockHeight": 2,
             "rewards": [{"rewardType": "Fee", "pubkey": "L"}], "transactions": [FIX[v] for v in ("legacy", "0", "1")]}
    sig = FIX["0"]["transaction"]["signatures"][0]
    ex = excerpt(10, block, {sig})
    assert block_leader(block) == "L" and ex["n_tx"] == 3 and ex["ours"][sig]["index"] == 1
    assert len(ex["ctx"]) == 3 and "sig12" not in ex
    assert excerpt(10, block, set(), full=False)["sig12"][2] == FIX["1"]["transaction"]["signatures"][0][:12]


def test_b58():
    assert b58decode("1") == b"\0" and b58decode("2") == b"\x01"
