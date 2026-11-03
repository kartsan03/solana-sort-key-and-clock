"""Regression tests: train randomisation, campaign arguments, the spend cap's wallets and inflow check,
the strictness bound, the selection-aware randomisation check and table rendering."""
import asyncio
import inspect
import json
import pathlib
import re

import numpy as np
import pytest
from solders.keypair import Keypair

from itb import analyze, campaign, cli, ops, report, run, verdicts
from itb.design import panels_from_json
from itb.ledger import CapExceeded, Halted, Ledger

PANELS = panels_from_json(json.loads((pathlib.Path(__file__).parents[1] / "design" / "panels.json").read_text())["panels"])


def test_train_direction_is_drawn_even_with_a_fixed_spacing():
    arms = set()
    for _ in range(200):
        w = run.plan_probes({"study": "M"}, {}, 0, train_spec="t12")
        assert w["train"] == "t12" and len(w["probes"]) == 10
        arms.add(w["arm"])
    assert arms == {"M-inc", "M-dec"}


def test_campaign_block_files_carry_no_train_specs():
    quotas = {"V": {"family": "AgaveBam", "K": 6, "M": 4, "train_specs": ["t4", "t12"]}}
    out = campaign.block_targets(quotas, {"V": {"K": [3, 3], "M": [2, 2]}}, 1)
    assert out == {"V": {"family": "AgaveBam", "K": 3, "M": 2}}


def test_campaign_passes_every_option_cmd_plan_and_cmd_run_read():
    for fn, ns in ((cli.cmd_plan, campaign.plan_args("t.json", "A-1029-b0", 3.5, 2.0)),
                   (cli.cmd_run, campaign.run_args("p.json", 60.0)),
                   (cli.cmd_run, campaign.run_args("p.json", 60.0, 0.002))):
        used = set(re.findall(r"\ba\.(\w+)", inspect.getsource(fn)))
        assert used and all(hasattr(ns, name) for name in used), used - set(vars(ns))
    assert campaign.run_args("p.json", 60.0, 0.002).live and not campaign.run_args("p.json", 60.0).live


def test_spend_cap_watches_the_loaded_keys(tmp_path, monkeypatch):
    keys = [Keypair() for _ in range(3)]
    monkeypatch.setattr(cli, "payers", lambda: keys)
    led = Ledger(tmp_path / "l.sqlite")
    assert cli.live_pubkeys(led) == [str(k.pubkey()) for k in keys]       # no ledger wallets yet: init uses these
    led.init_baseline(["someone", "else", "entirely"], {"someone": 1, "else": 1, "entirely": 1}, slot=1)
    with pytest.raises(SystemExit):
        cli.live_pubkeys(led)


class FakeRpc:
    def __init__(self, height, balances, landed):
        self.height, self.bal, self.landed, self.calls = height, balances, landed, []

    async def block_height(self, commitment):
        self.calls.append("height")
        return self.height

    async def balances(self, pks, commitment):
        self.calls.append("balances")
        return {p: self.bal[p] for p in pks}, 10

    async def signature_statuses(self, sigs):
        self.calls.append("statuses")
        return {s: ({"slot": 1} if s in self.landed else None) for s in sigs}


def tx(sig, fee, last_valid=100):
    return {"sig": sig, "run_id": "r", "kind": "probe", "payer": "w", "max_fee": fee, "last_valid": last_valid, "raw": b"\x01"}


def test_reconcile_reads_height_first_and_counts_landed_fees(tmp_path):
    led = Ledger(tmp_path / "l.sqlite")
    led.init_baseline(["w"], {"w": 1_000_000}, slot=1)
    led.reserve([tx("a", 6_000), tx("b", 7_000)])
    rpc = FakeRpc(height=200, balances={"w": 994_000}, landed={"a"})
    r, _ = asyncio.run(ops.reconcile(rpc, led, ["w"]))
    assert rpc.calls[:2] == ["height", "balances"] and "statuses" in rpc.calls
    assert not r["halted"] and r["spent"] == 6_000 and led.get("landed_fees") == 6_000


def test_a_deposit_cannot_hide_spend(tmp_path):
    led = Ledger(tmp_path / "l.sqlite")
    led.init_baseline(["w"], {"w": 60_000_000}, slot=1)
    led.reserve([tx(f"s{i}", 1_000_000) for i in range(49)])
    # 49,000,000 in fees landed, and an unlogged 1,000,000 deposit arrived at the same time
    r = led.reconcile({"w": 60_000_000 - 49_000_000 + 1_000_000}, 200, 10, landed_fee=49_000_000)
    assert r["halted"] and r["hidden_by_inflow"] == 1_000_000
    assert led.summary()["reserved"] == 49_000_000            # nothing released: the cap still counts every fee
    with pytest.raises((Halted, CapExceeded)):
        led.reserve([tx("more", 2_000_000)])


def k_row(rivals):
    best = {"p_iut": 1e-4, "min_rate": 1.0, "min_n": min(r["n"] for r in rivals.values()), "rivals": rivals}
    return {"V|dayA": {"phase": "dayA", "validator": "V", "family": "Agave", "best": "agave_int", "evaluable": 30,
                       "null_p_best": 0.001, "keys": {"agave_int": best}}}


def test_strict_needs_every_rivals_lower_bound():
    rivals = {k: {"wins": n, "n": n, "rate": 1.0, "ci": analyze.clopper_pearson(n, n)}
              for k, n in (("fd_exact", 15), ("total_fee", 10))}
    out = verdicts.calls(k_row(rivals), {"V": 1}, "dayA")["V"]
    assert out["verdict"] == "rule (loose)" and out["min_rate_ci"][0] < 0.75   # 10/10 has a lower bound of 0.69


def test_randomisation_check_reselects_the_key():
    rng = np.random.default_rng(1)
    panels = {"P1": PANELS["P1"]}
    order = analyze.ranks(panels["P1"], "agave_int")
    seq = sorted(order, key=lambda lab: -order[lab])
    ws = [{"panel": "P1", "probes": [{"label": lab, "outcome": "target_block", "index": i, "slot": 7}
                                     for i, lab in enumerate(seq)]} for _ in range(12)]
    assert analyze.randomisation_null_select(ws, panels, rng) < 0.01
    noise = [{"panel": "P1", "probes": [{"label": lab, "outcome": "target_block", "index": int(i), "slot": 7}
                                        for i, lab in zip(rng.permutation(6), seq)]} for _ in range(12)]
    assert analyze.randomisation_null_select(noise, panels, rng) > 0.05


def test_joint_fit_table_keeps_its_columns():
    res = {"capsweep": {"windows": 1, "full_windows": 1, "verdict": "x", "panels": {},
                        "models": {"capped (best X, beta)": {"matches": 1, "X": [1500, 1600], "beta": [0.1, 0.2],
                                                             "extra_cu_40000_vs_4400": [1, 2]},
                                   "hard_cap": {"matches": 0, "X": [1500, 1500]}, "no_cap (agave_int)": 0},
                        "joint": {"full_windows": 2, "best_matches": 2, "X": [1500, 1600], "beta": [0.1, 0.2],
                                  "hard_cap": 1, "no_cap (agave_int)": 1,
                                  "groups": {"dayB|P1": {"full_windows": 2, "matches_at_best": [2, 2]}}}}}
    rows = [r for r in report.capsweep_table(res) if r.startswith("| dayB")]
    assert rows == ["| dayB / P1 | 2 | 2 |"]
