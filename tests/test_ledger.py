"""The fee cap holds: up to the cap, across restarts, and against unexplained balance drops."""
import multiprocessing
import os

import pytest

from itb.ledger import CAP_LAMPORTS, CapExceeded, Halted, Ledger

W = ["burner", "p1"]


def tx(i, fee=6_000, last_valid=100):
    return {"sig": f"s{i}", "run_id": "r", "kind": "probe", "payer": "p1", "max_fee": fee,
            "last_valid": last_valid, "raw": b"\x01" * 10}


def fresh(tmp_path):
    led = Ledger(tmp_path / "l.sqlite")
    led.init_baseline(W, {"burner": 50_000_000, "p1": 0}, slot=1)
    return led


def test_reserve_up_to_cap_then_abort(tmp_path):
    led = fresh(tmp_path)
    fee = 1_000_000
    for i in range(CAP_LAMPORTS // fee):
        led.reserve([tx(i, fee)])
    assert led.remaining() == 0
    with pytest.raises(CapExceeded):
        led.reserve([tx("x", 1)])
    # a batch is all-or-nothing
    assert led.db.execute("SELECT COUNT(*) FROM txs").fetchone()[0] == 50


def test_run_limit(tmp_path):
    led = fresh(tmp_path)
    led.reserve([tx(1, 400)])
    with pytest.raises(CapExceeded):
        led.reserve([tx(2, 700)], run_limit=1_000)
    led.reserve([tx(3, 600)], run_limit=1_000)


def _child(path, n):
    led = Ledger(path)
    for i in range(n):
        led.reserve([tx(f"c{i}", 10_000)])
        if i == n // 2:
            os._exit(9)  # killed mid-burst, no cleanup


def test_crash_restart_keeps_reservations(tmp_path):
    led = fresh(tmp_path)
    p = multiprocessing.get_context("fork").Process(target=_child, args=(str(tmp_path / "l.sqlite"), 40))
    p.start()
    p.join()
    assert p.exitcode == 9
    again = Ledger(tmp_path / "l.sqlite")
    assert again.reserved() == 21 * 10_000          # all reservations made before the kill survive
    assert again.remaining() == CAP_LAMPORTS - 210_000


def test_reconcile_releases_only_expired(tmp_path):
    led = fresh(tmp_path)
    led.reserve([tx(1, 6_000, last_valid=100), tx(2, 7_000, last_valid=300)])
    # tx 1 landed (fee 6,000 charged), tx 2 still alive; funding move burner -> p1 is internal
    bal = {"burner": 50_000_000 - 1_006_000, "p1": 1_000_000}
    r = led.reconcile(bal, height=200, slot=2)
    assert not r["halted"] and r["spent"] == 6_000 and r["released"] == 1
    assert led.reserved() == 7_000 and led.committed() == 13_000


def test_reconcile_halts_on_unexplained_drop(tmp_path):
    led = fresh(tmp_path)
    led.reserve([tx(1, 6_000)])
    r = led.reconcile({"burner": 50_000_000 - 20_000, "p1": 0}, height=200, slot=2)
    assert r["halted"] and r["unexplained"] == 14_000
    with pytest.raises(Halted):
        led.reserve([tx(2)])


def test_reconcile_halts_on_unlogged_inflow_and_accepts_logged(tmp_path):
    led = fresh(tmp_path)
    r = led.reconcile({"burner": 60_000_000, "p1": 0}, height=10, slot=2)
    assert r["halted"]
    led.unhalt("test")
    led.record_flow("in", "topup", 10_000_000, "owner top-up")
    r = led.reconcile({"burner": 60_000_000, "p1": 0}, height=10, slot=3)
    assert not r["halted"] and r["spent"] == 0
