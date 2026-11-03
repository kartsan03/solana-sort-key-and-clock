import asyncio

from itb import verify
from itb.chain import BlockUnavailable


class FakeRpc:
    def __init__(self, leaders, blocks=None):
        self.leaders, self.blocks = leaders, blocks or {}

    async def call(self, method, slot, n):
        assert method == "getSlotLeaders"
        return self.leaders[:n]

    async def block(self, slot, strict=False):
        b = self.blocks.get(slot, {"transactions": []})
        if b == "unavailable":
            assert strict
            raise BlockUnavailable(f"-32004 Block not available for slot {slot}")
        return b

    async def close(self):
        pass


def run(monkeypatch, leaders, blocks=None):
    w = {"window_id": "W-1", "phase": "dayC", "target": "T", "slot0": 100, "probes": []}
    monkeypatch.setattr(verify.analyze, "load", lambda: [w])
    monkeypatch.setattr(verify, "Rpc", lambda: FakeRpc(leaders, blocks))
    return asyncio.run(verify.main(sample=None))


def test_verify_checks_the_leader_schedule(monkeypatch):
    assert run(monkeypatch, ["T"] * 4) == 0
    assert run(monkeypatch, ["T", "T", "X", "X"]) == 1


def test_verify_fails_on_an_unavailable_block_but_not_a_skipped_slot(monkeypatch, capsys):
    assert run(monkeypatch, ["T"] * 4, {101: None}) == 0                  # skipped slot
    assert run(monkeypatch, ["T"] * 4, {101: "unavailable"}) == 1         # the RPC cannot serve it
    assert "block 101 unavailable" in capsys.readouterr().out
