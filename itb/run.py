"""Plan and execute probe windows. Dry run (no sends, no spend) unless --live.

Timing: the slot clock uses the RPC node's `firstShredReceived` timestamps
(slotsUpdatesSubscribe). A new leader's first slot shows up late and the next one
early (first-shred gaps run ~255/150/200/200 ms), so slots are extrapolated with a
median gap per position in the 4-slot window. Send times are corrected by half the
measured QUIC round trip to the target.
"""
import asyncio
import base64
import gzip
import hashlib
import json
import pathlib
import secrets
import statistics
import time
from collections import defaultdict, deque

from solders.hash import Hash
from solders.keypair import Keypair

from . import cluster
from .chain import UA, ws_url_for
from .design import LABELS, NULL_PROBE, TRAIN_SPECS, make, panels_from_json, train
from .probe import KEYS, Probe, probe_tx
from .quic import TpuPool, sleep_until_mono

SHORT_FUSE = (80, 110)      # blocks of validity left when a probe is signed (~16-22 s)
MIN_GAP_S = 26              # windows at least this far apart, so payers' previous probes have expired
LAMBDA_MS = 60              # assumed delay from leader slot start to the RPC node's first shred


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


# ---------------- planning ----------------

def sample_windows(schedule, nodes, targets, start_slot, end_slot, ms_per_slot, cur_slot=None):
    """Stratified random windows: each target's quota spread evenly over the time range."""
    rng = secrets.SystemRandom()
    t0 = time.time()
    cur = cur_slot or start_slot
    picks = []
    for ident, quota in targets.items():
        ws = [s for s in cluster.windows(schedule, ident, start_slot) if s + 4 <= end_slot]
        ws = [s for s in ws if cluster.builder_window_ok(nodes, ident, cluster.previous_leader(schedule, s))]
        n = quota.get("K", 0) + quota.get("M", 0)
        if not ws or not n:
            continue
        n = min(n, len(ws))
        bins = [ws[i * len(ws) // n:(i + 1) * len(ws) // n] for i in range(n)]
        studies = ["K"] * quota.get("K", 0) + ["M"] * quota.get("M", 0)
        rng.shuffle(studies)
        for b, st in zip(bins, studies):
            picks.append((rng.choice(b), ident, st))
    picks.sort()
    plan, last = [], -10**9
    for s, ident, st in picks:   # drop windows too close to the previous one
        if (s - last) * ms_per_slot / 1000 < MIN_GAP_S:
            continue
        last = s
        plan.append({"slot0": s, "target": ident, "study": st,
                     "prev_leader": cluster.previous_leader(schedule, s),
                     "eta_utc": time.strftime("%H:%M:%S", time.gmtime(t0 + (s - cur) * ms_per_slot / 1000))})
    return plan


def plan_probes(w, panels, k_index, force_arm=None, train_spec=None):
    """Draw this window's randomisation (OS randomness, logged) and fix its probes and payers.

    force_arm / train_spec are used only for calibration runs (pilot), never in the campaign."""
    from . import design
    rng = secrets.SystemRandom()
    if w["study"] == "K":
        r = design.draw_panel_window(sorted(panels))
        if force_arm:
            r["arm"] = force_arm
        qs = [(lab, make(*NULL_PROBE)) for lab in LABELS] if r["arm"] == "K-null" else sorted(panels[r["panel"]].items())
        group = 6 * (k_index % 2)                     # alternate payer groups 0-5 / 6-11
        payers = [group + r["payer_slots"][i] for i in range(6)]
    else:
        r = design.draw_train_window()
        if train_spec:
            r.update(train=train_spec, arm="M-inc")
            r["payer_slots"] = rng.sample(range(TRAIN_SPECS[train_spec][0]), TRAIN_SPECS[train_spec][0])
        qs = [(f"T{i:02d}", q) for i, q in enumerate(train(r["train"], r["arm"] == "M-inc"))]
        payers = rng.sample(range(12), len(qs))
    w.update(r)
    w["probes"] = [[lab, q.L, q.p, q.D] for lab, q in qs]
    w["payers"] = payers
    w["max_spend"] = sum(q.fee for _, q in qs)
    return w


# ---------------- execution ----------------

class Runner:
    def __init__(self, rpc, ledger, payers, run_dir, live, run_limit, lambda_ms=LAMBDA_MS, log=print):
        self.rpc, self.ledger, self.payers = rpc, ledger, payers
        self.dir = pathlib.Path(run_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.live, self.run_limit, self.lambda_ms, self.log = live, run_limit, lambda_ms, log
        self.pool = TpuPool()
        self.files = {n: open(self.dir / f"{n}.jsonl", "a") for n in ("windows", "probes", "snapshots", "logs")}
        self.payer_free_at = {}    # payer index -> last_valid height of its newest probe

    def write(self, name, rec):
        self.files[name].write(json.dumps(rec, separators=(",", ":")) + "\n")
        self.files[name].flush()

    def note(self, msg, **kw):
        self.write("logs", {"t_ns": time.time_ns(), "msg": msg, **kw})
        self.log(msg)

    async def snapshot_loop(self, keep, stop, every=30):
        while not stop.is_set():
            try:
                snap = await cluster.nodes_snapshot(self.rpc, keep)
                self.nodes.update(snap["nodes"])
                self.write("snapshots", {"kind": "gossip", **snap})
            except Exception as e:
                self.note(f"snapshot failed: {e}")
            await asyncio.sleep(every)

    async def kobe_loop(self, stop):
        while not stop.is_set():
            try:
                k = await cluster.kobe_snapshot()
                self.write("snapshots", {"kind": "kobe", **k})
            except Exception as e:
                self.note(f"kobe failed: {e}")
            await asyncio.sleep(3600)

    async def window(self, w, panels, clock, chain):
        wid = w["window_id"]
        node = self.nodes.get(w["target"])
        if not node or not node.get("tpuQuic"):
            self.note(f"{wid}: target not in gossip, skipped")
            return
        addr = node["tpuQuic"]
        t_fs0 = clock.predict_ms(w["slot0"]) * 1_000_000
        await sleep_until_mono(wall_to_mono_ns(t_fs0 - 6_000_000_000))
        rec = {**w, "addr": addr, "ingress": node["ingress"], "client": node["client"], "live": self.live}
        try:
            _, hs = await self.pool.get(addr)
            rtts = []
            for _ in range(3):
                t = time.monotonic()
                await asyncio.wait_for(self.pool.conns[addr].ping(), 2)
                rtts.append((time.monotonic() - t) * 1000)
            rec.update(handshake_ms=round(hs, 2), rtt_ms=[round(x, 2) for x in rtts])
        except Exception as e:
            rec.update(connect_error=f"{type(e).__name__}: {e}")
            self.write("windows", rec)
            self.note(f"{wid}: connect failed to {addr}: {e}")
            await self.pool.drop(addr)
            return
        owl_ms = statistics.median(rtts) / 2
        await sleep_until_mono(wall_to_mono_ns(clock.predict_ms(w["slot0"]) * 1_000_000 - 2_500_000_000))
        # build and sign
        qs = [(lab, Probe(L, p, D)) for lab, L, p, D in w["probes"]]
        payer_idx = w["payers"]
        if any(chain.height_now() <= self.payer_free_at.get(i, -1) for i in payer_idx):
            self.note(f"{wid}: payers still busy, skipped")
            return
        bh, last_valid = chain.short_fuse()
        shared_lock = Keypair().pubkey()
        txs, probes = [], []
        for (label, q), pi in zip(qs, payer_idx):
            lock = Keypair().pubkey() if w["arm"] == "K-free" else shared_lock
            tx = probe_tx(self.payers[pi], lock, q, Hash.from_string(bh))
            raw = bytes(tx)
            sig = str(tx.signatures[0])
            probes.append({"sig": sig, "window_id": wid, "run_id": w["run_id"], "label": label,
                           "payer": str(self.payers[pi].pubkey()), "payer_idx": pi, "lock": str(lock),
                           "L": q.L, "p": q.p, "D": q.D, "pf": q.pf, "cost": q.cost, "fee": q.fee,
                           "keys": {k: str(KEYS[k](q)) for k in KEYS}, "blockhash": bh, "last_valid": last_valid,
                           "raw_b64": base64.b64encode(raw).decode()})
            txs.append({"sig": sig, "run_id": w["run_id"], "kind": "probe", "payer": probes[-1]["payer"],
                        "max_fee": q.fee, "last_valid": last_valid, "raw": raw, "info": {"window": wid, "label": label}})
        if self.live:
            self.ledger.reserve(txs, run_limit=self.run_limit)    # raises before anything is sent
        for pi in payer_idx:
            self.payer_free_at[pi] = last_valid
        # send times (wall ns), re-predicted just before the first send
        if w["study"] == "K":
            order = w["send_order"]
            by_label = {p["label"]: p for p in probes}
            seq = [by_label[lab] for lab in order]

            def plan_times():
                t = clock.predict_ms(w["slot0"]) - self.lambda_ms - owl_ms + w["offset_ms"]
                return [int(t * 1e6)] * len(seq)
        else:
            seq = probes
            spacing = TRAIN_SPECS[w["train"]][1]

            def plan_times():
                t = clock.predict_ms(w["slot0"] + 1) - self.lambda_ms - owl_ms + w["phase_ms"]
                return [int((t + i * spacing) * 1e6) for i in range(len(seq))]
        first = plan_times()[0]
        await sleep_until_mono(wall_to_mono_ns(first) - 120_000_000)
        planned = plan_times()
        rec.update(clock=clock.state(), owl_ms=round(owl_ms, 3), blockhash=bh, last_valid=last_valid,
                   lock=str(shared_lock), planned_ns=planned, height_at_sign=chain.height_now())
        offset = time.time_ns() - time.monotonic_ns()
        for p, t_plan in zip(seq, planned):
            await sleep_until_mono(t_plan - offset)
            if self.live:
                try:
                    sid, tw, tm = self.pool.send(addr, base64.b64decode(p["raw_b64"]))
                    p.update(stream=sid, sent_ns=tw, sent_mono=tm)
                except Exception as e:
                    p.update(ack="error", send_error=str(e), sent_ns=time.time_ns())
            else:
                p.update(sent_ns=time.time_ns(), sent_mono=time.monotonic_ns(), dry=True)
            p["planned_ns"] = t_plan
        rec["slot_at_send"] = clock.last
        await asyncio.sleep(1.0)
        for p in probes:
            if self.live and "stream" in p:
                p["ack"] = self.pool.acked(addr, p["stream"])
                self.ledger.mark_sent(p["sig"], p["sent_ns"], p["ack"])
            elif not self.live:
                p["ack"] = "not_sent"
            self.write("probes", p)
        self.write("windows", rec)
        errs = [(p["sent_ns"] - p["planned_ns"]) / 1e6 for p in probes]
        self.note(f"{wid}: {w['study']}/{w['arm']} -> {w['target'][:8]} slot {w['slot0']} "
                  f"sent {len(probes)} (send err med {statistics.median(errs):+.2f} ms) "
                  f"acks {sum(p.get('ack') == 'acked' for p in probes)}/{len(probes)}")

    async def execute(self, plan, panels, epoch_start, keep):
        stop = asyncio.Event()
        clock = SlotClock(epoch_start)
        chain = Chainstate(self.rpc)
        self.nodes = {}
        bg = [asyncio.create_task(slot_updates(ws_url_for(self.rpc.url), clock, stop)),
              asyncio.create_task(chain.poll(stop)),
              asyncio.create_task(self.snapshot_loop(keep, stop)),
              asyncio.create_task(self.kobe_loop(stop))]
        for _ in range(100):
            if clock.last and chain.hashes and self.nodes and len(clock.fs) > 40:
                break
            await asyncio.sleep(0.2)
        try:
            for w in plan:
                lead = (w["slot0"] - clock.last) * sum(clock.gap(i) for i in range(4)) / 4000
                if lead < 8:
                    self.note(f"{w['window_id']}: too close ({lead:.1f}s), skipped")
                    continue
                try:
                    await self.window(w, panels, clock, chain)
                except Exception as e:
                    self.note(f"{w['window_id']}: error {type(e).__name__}: {e}")
                    if type(e).__name__ in ("CapExceeded", "Halted"):
                        raise
        finally:
            stop.set()
            for t in bg:
                t.cancel()
            await self.pool.close()
            for f in self.files.values():
                f.close()
        return max((v for v in self.payer_free_at.values()), default=0)


def finalize(run_dir):
    """Compress jsonl files and write SHA256SUMS."""
    d = pathlib.Path(run_dir)
    for p in sorted(d.glob("*.jsonl")):
        gz = p.with_suffix(".jsonl.gz")
        with open(p, "rb") as src, gzip.GzipFile(gz, "wb", mtime=0) as dst:
            dst.write(src.read())
        p.unlink()
    sums = []
    for p in sorted(d.iterdir()):
        if p.is_file() and p.name != "SHA256SUMS":
            sums.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}")
    (d / "SHA256SUMS").write_text("\n".join(sums) + "\n")
