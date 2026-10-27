"""Slot clock from the RPC node's first-shred timestamps, and a background poller for blockhashes.

A new leader's first slot shows up late and the next one early (first-shred gaps run ~280/146/200/200 ms),
so slots are extrapolated with a median gap per position in the 4-slot window.
"""
import asyncio
import json
import statistics
import time
from collections import defaultdict, deque

from .chain import UA

SHORT_FUSE = (80, 110)      # blocks of validity left when a probe is signed (~16-22 s)


class SlotClock:
    def __init__(self, epoch_start):
        self.epoch_start = epoch_start
        self.fs = {}                       # slot -> node first-shred time, ms since epoch
        self.gaps = defaultdict(lambda: deque(maxlen=200))
        self.last = None

    def pos(self, slot):
        return (slot - self.epoch_start) % 4

    def on_update(self, r):
        if r.get("type") != "firstShredReceived":
            return
        s, ts = r["slot"], r["timestamp"]
        if s in self.fs:
            return
        self.fs[s] = ts
        if s - 1 in self.fs:
            self.gaps[self.pos(s)].append(ts - self.fs[s - 1])
        if self.last is None or s > self.last:
            self.last = s
        if len(self.fs) > 5000:
            for k in sorted(self.fs)[:1000]:
                del self.fs[k]

    def gap(self, pos):
        g = self.gaps[pos]
        return statistics.median(g) if len(g) >= 5 else 200.0

    def predict_ms(self, slot):
        """Predicted first-shred time (ms, UTC) of `slot`, extrapolated from the newest observation."""
        if self.last is None:
            raise RuntimeError("slot clock has no data yet")
        if slot in self.fs:
            return self.fs[slot]
        base = max(s for s in self.fs if s <= slot) if slot > self.last else self.last
        t = self.fs[base]
        for s in range(base + 1, slot + 1):
            t += self.gap(self.pos(s))
        return t

    def state(self):
        return {"last": self.last, "last_ts": self.fs.get(self.last), "gaps": {p: self.gap(p) for p in range(4)}}


async def slot_updates(ws_url, clock, stop):
    import websockets
    sub = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "slotsUpdatesSubscribe"})
    while not stop.is_set():
        try:
            async with websockets.connect(ws_url, user_agent_header=UA, ping_interval=10, max_size=2**20) as ws:
                await ws.send(sub)
                async for raw in ws:
                    r = json.loads(raw).get("params", {}).get("result")
                    if r:
                        clock.on_update(r)
                    if stop.is_set():
                        return
        except Exception:
            await asyncio.sleep(0.5)


class Chainstate:
    """Recent blockhashes and block height, polled in the background."""

    def __init__(self, rpc):
        self.rpc = rpc
        self.hashes = deque(maxlen=40)     # (blockhash, last_valid)
        self.height = None
        self.height_t = None

    async def poll(self, stop):
        while not stop.is_set():
            try:
                bh, lv, _ = await self.rpc.latest_blockhash("confirmed")
                if not self.hashes or self.hashes[-1][0] != bh:
                    self.hashes.append((bh, lv))
                self.height = await self.rpc.block_height("confirmed")
                self.height_t = time.monotonic()
            except Exception:
                pass
            await asyncio.sleep(1.5)

    def height_now(self):
        return self.height + int((time.monotonic() - self.height_t) / 0.21)

    def short_fuse(self):
        h = self.height_now()
        ok = [(bh, lv) for bh, lv in self.hashes if SHORT_FUSE[0] <= lv - h <= SHORT_FUSE[1]]
        return ok[-1] if ok else self.hashes[-1]


def wall_to_mono_ns(wall_ns):
    return wall_ns - (time.time_ns() - time.monotonic_ns())
