"""Who leads when, which client they run, and where their TPU traffic goes."""
import collections
import json
import time

import httpx

from .chain import UA

KOBE_URL = "https://kobe.mainnet.jito.network/api/v1/validators"
VAPP_URL = "https://www.validators.app/api/v1/validators/mainnet.json"
RELAYER_PORT = 11228
BAM_PORT = 5010
WINDOW = 4


def split_addr(addr):
    if not addr:
        return None, None
    host, _, port = addr.rpartition(":")
    return host, int(port)


def compact_nodes(nodes):
    """pubkey -> the fields we keep, plus how many identities share each TPU IP."""
    shared = collections.Counter(split_addr(n.get("tpuQuic"))[0] for n in nodes if n.get("tpuQuic"))
    out = {}
    for n in nodes:
        ip, port = split_addr(n.get("tpuQuic"))
        gip, _ = split_addr(n.get("gossip"))
        out[n["pubkey"]] = {"client": n.get("clientId"), "version": n.get("version"), "tpuQuic": n.get("tpuQuic"),
                            "gossip_ip": gip, "ingress": ingress_kind(n.get("clientId"), ip, port, gip),
                            "tpu_shared": shared.get(ip, 0)}
    return out


def ingress_kind(client, ip, port, gossip_ip):
    if ip is None:
        return "none"
    if ip == gossip_ip:
        return "relayer_port" if port == RELAYER_PORT else "own"
    if port == BAM_PORT:
        return "bam"
    if (client or "").startswith("Harmonic"):
        return "harmonic"
    return "remote"


def leader_type(node):
    return f"{node['client']}/{node['ingress']}" if node else "unknown/none"


async def nodes_snapshot(rpc, keep=None):
    nodes = compact_nodes(await rpc.cluster_nodes())
    snap = {"t_ns": time.time_ns(), "slot": await rpc.slot("confirmed")}
    snap["nodes"] = {k: v for k, v in nodes.items() if keep is None or k in keep}
    return snap


SLOTS_PER_EPOCH = 432_000   # mainnet: no warmup, epoch e starts at e * 432,000


async def epoch_schedule(rpc, first_slot=None, last_slot=None):
    """Leader schedule as {absolute_slot: leader} for every epoch overlapping [first_slot, last_slot]."""
    ei = await rpc.epoch_info()
    cur_start = ei["absoluteSlot"] - ei["slotIndex"]
    assert cur_start == ei["epoch"] * SLOTS_PER_EPOCH, "unexpected epoch layout"
    first_slot = first_slot or ei["absoluteSlot"]
    last_slot = last_slot or first_slot
    by_slot, epochs = {}, []
    for e in range(first_slot // SLOTS_PER_EPOCH, last_slot // SLOTS_PER_EPOCH + 1):
        start = e * SLOTS_PER_EPOCH
        sched = await rpc.call("getLeaderSchedule", start)
        if not sched:
            raise RuntimeError(f"leader schedule for epoch {e} not available yet")
        for leader, idxs in sched.items():
            for i in idxs:
                by_slot[start + i] = leader
        epochs.append(e)
    start = epochs[0] * SLOTS_PER_EPOCH
    return {"epoch": epochs[0], "epochs": epochs, "start": start, "slots": SLOTS_PER_EPOCH * len(epochs),
            "by_slot": by_slot}


def windows(schedule, identity, after_slot=0):
    """Start slots of `identity`'s 4-slot leader windows after `after_slot`."""
    out = []
    for s in sorted(k for k, v in schedule["by_slot"].items() if v == identity and k > after_slot):
        if (s - schedule["start"]) % WINDOW == 0:
            out.append(s)
    return out


def previous_leader(schedule, window_start):
    return schedule["by_slot"].get(window_start - 1)


def builder_window_ok(nodes, target, prev):
    """For shared-ingress targets, skip windows whose previous leader uses the same TPU IP."""
    t, p = nodes.get(target), nodes.get(prev)
    if not t or t["ingress"] in ("own", "relayer_port") or not p:
        return True
    return split_addr(t["tpuQuic"])[0] != split_addr(p["tpuQuic"])[0]


def save_schedule(schedule, path):
    d = dict(schedule)
    d["by_slot"] = {str(k): v for k, v in schedule["by_slot"].items()}
    path.write_text(json.dumps(d))


def load_schedule(path):
    d = json.loads(path.read_text())
    d["by_slot"] = {int(k): v for k, v in d["by_slot"].items()}
    return d


async def kobe_snapshot():
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": UA}) as http:
        r = await http.get(KOBE_URL)
        r.raise_for_status()
    keep = ("running_jito", "running_bam", "bam_connection_rate", "active_stake")
    return {"t_ns": time.time_ns(),
            "validators": {v["identity_account"]: {k: v.get(k) for k in keep} for v in r.json()["validators"]}}


def validators_app_token():
    """Token from the environment or ../.env.rpc (outside the repo); never logged."""
    import os
    import pathlib
    name = "VALIDATORS_APP_TOKEN"
    tok = os.environ.get(name)
    env = pathlib.Path(__file__).resolve().parents[2] / ".env.rpc"
    if not tok and env.exists():
        for line in env.read_text().splitlines():
            k, _, v = line.strip().partition("=")
            if k == name:
                tok = v.strip().strip('"')
    return tok or None


async def validators_app_snapshot(token, identities):
    """Client labels from validators.app (needs a free API token)."""
    async with httpx.AsyncClient(timeout=60, headers={"User-Agent": UA, "Token": token}) as http:
        r = await http.get(VAPP_URL, params={"limit": 9999})
        r.raise_for_status()
    rows = {v.get("account"): v for v in r.json()}
    keep = ("software_client", "software_client_id", "software_version", "jito", "name")
    return {"t_ns": time.time_ns(),
            "validators": {i: {k: rows[i].get(k) for k in keep} for i in identities if i in rows}}
