import asyncio

from itb import verify


class FakeRpc:
    def __init__(self, leaders):
        self.leaders = leaders

    async def call(self, method, slot, n):
        assert method == "getSlotLeaders"
        return self.leaders[:n]

    async def block(self, slot):
        return {"transactions": []}

    async def close(self):
        pass


def run(monkeypatch, leaders):
    w = {"window_id": "W-1", "phase": "dayC", "target": "T", "slot0": 100, "probes": []}
    monkeypatch.setattr(verify.analyze, "load", lambda: [w])
    monkeypatch.setattr(verify, "Rpc", lambda: FakeRpc(leaders))
    return asyncio.run(verify.main(sample=None))


def test_verify_checks_the_leader_schedule(monkeypatch):
    assert run(monkeypatch, ["T"] * 4) == 0
    assert run(monkeypatch, ["T", "T", "X", "X"]) == 1
