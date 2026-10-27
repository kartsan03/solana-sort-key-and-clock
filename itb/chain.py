"""JSON-RPC and slot-stream access with polite rate limits.

The public endpoint allows 100 requests / 10 s per IP and 40 per method, and some
endpoints reject non-browser user agents, so every call goes through one limiter.
"""
import asyncio
import base64
import json
import os
import random
import time
from collections import defaultdict, deque

import httpx

PUBLIC_RPC = "https://api.mainnet-beta.solana.com"
UA = "Mozilla/5.0 (X11; Linux x86_64) itb-research/0.1"
MAINNET_GENESIS = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
ALPENGLOW_FEATURE = "A1pengvuM6JEcyNuTnMqepBKhwHE3N6PmUrdATGawhJS"
FIRST_ALPENGLOW_SLOT = 459_653_000


class RpcError(Exception):
    pass


class Limiter:
    """Sliding-window limiter: global and per-method caps over `window` seconds."""

    def __init__(self, total=80, per_method=32, window=10.0):
        self.total, self.per_method, self.window = total, per_method, window
        self.all = deque()
        self.by = defaultdict(deque)
        self.lock = asyncio.Lock()

    async def wait(self, method):
        async with self.lock:
            while True:
                now = time.monotonic()
                for q in (self.all, self.by[method]):
                    while q and now - q[0] > self.window:
                        q.popleft()
                if len(self.all) < self.total and len(self.by[method]) < self.per_method:
                    self.all.append(now)
                    self.by[method].append(now)
                    return
                oldest = min(q[0] for q in (self.all, self.by[method]) if q)
                await asyncio.sleep(max(0.01, self.window - (now - oldest)))


class Rpc:
    def __init__(self, url=None, limiter=None, timeout=30.0):
        self.url = url or os.environ.get("ITB_RPC_URL") or PUBLIC_RPC
        public = self.url.startswith(PUBLIC_RPC)
        self.limiter = limiter or (Limiter() if public else Limiter(total=90, per_method=90))
        self.http = httpx.AsyncClient(timeout=timeout, headers={"User-Agent": UA})
        self.calls = 0

    async def close(self):
        await self.http.aclose()

    async def call(self, method, *params, retries=6):
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": list(params)}
        delay = 0.5
        for attempt in range(retries):
            await self.limiter.wait(method)
            self.calls += 1
            try:
                r = await self.http.post(self.url, json=body)
                if r.status_code == 429 or r.status_code >= 500:
                    raise RpcError(f"HTTP {r.status_code}")
                out = r.json()
            except (httpx.HTTPError, RpcError, json.JSONDecodeError) as e:
                if attempt == retries - 1:
                    raise RpcError(f"{method}: {e}") from e
                await asyncio.sleep(delay + random.random() * delay)
                delay = min(delay * 2, 8)
                continue
            if "error" in out:
                err = out["error"]
                # -32004/-32007/-32009: block not available / skipped / missing; caller decides
                raise RpcError(f"{method}: {err.get('code')} {err.get('message')}")
            return out["result"]

    # ---- thin wrappers ----
    async def slot(self, commitment="processed"):
        return await self.call("getSlot", {"commitment": commitment})

    async def block_height(self, commitment="processed"):
        return await self.call("getBlockHeight", {"commitment": commitment})

    async def epoch_info(self):
        return await self.call("getEpochInfo", {"commitment": "confirmed"})

    async def genesis_hash(self):
        return await self.call("getGenesisHash")

    async def latest_blockhash(self, commitment="confirmed"):
        r = await self.call("getLatestBlockhash", {"commitment": commitment})
        return r["value"]["blockhash"], r["value"]["lastValidBlockHeight"], r["context"]["slot"]

    async def balances(self, pubkeys, commitment="confirmed"):
        """Lamports for each pubkey (0 if the account does not exist), plus the context slot."""
        out, slot = {}, None
        for i in range(0, len(pubkeys), 100):
            chunk = pubkeys[i:i + 100]
            r = await self.call("getMultipleAccounts", chunk,
                                {"commitment": commitment, "encoding": "base64", "dataSlice": {"offset": 0, "length": 0}})
            slot = r["context"]["slot"]
            for pk, acc in zip(chunk, r["value"]):
                out[pk] = acc["lamports"] if acc else 0
        return out, slot

    async def account(self, pubkey):
        r = await self.call("getAccountInfo", pubkey, {"encoding": "base64", "commitment": "confirmed"})
        return r["value"]

    async def leader_schedule(self, slot, identity):
        r = await self.call("getLeaderSchedule", slot, {"identity": identity})
        return (r or {}).get(identity, [])

    async def cluster_nodes(self):
        return await self.call("getClusterNodes")

    async def vote_accounts(self):
        return await self.call("getVoteAccounts", {"commitment": "confirmed"})

    async def block(self, slot, details="full"):
        """Full block with v1 support, or None if the slot was skipped / not available."""
        try:
            return await self.call("getBlock", slot, {
                "encoding": "json", "transactionDetails": details, "rewards": True,
                "maxSupportedTransactionVersion": 1, "commitment": "confirmed"})
        except RpcError as e:
            msg = str(e)
            if any(c in msg for c in ("-32004", "-32007", "-32009", "-32001")):
                return None
            raise

    async def signature_statuses(self, sigs):
        out = {}
        for i in range(0, len(sigs), 32):
            chunk = sigs[i:i + 32]
            r = await self.call("getSignatureStatuses", chunk, {"searchTransactionHistory": True})
            out.update(zip(chunk, r["value"]))
        return out

    async def transaction(self, sig):
        return await self.call("getTransaction", sig, {
            "encoding": "json", "maxSupportedTransactionVersion": 1, "commitment": "confirmed"})

    async def simulate(self, tx_bytes, sig_verify=False):
        return await self.call("simulateTransaction", base64.b64encode(tx_bytes).decode(), {
            "encoding": "base64", "sigVerify": sig_verify, "replaceRecentBlockhash": not sig_verify,
            "commitment": "processed"})

    async def blocks(self, start, end):
        return await self.call("getBlocks", start, end, {"commitment": "confirmed"})

    async def rent_exempt(self, size=0):
        return await self.call("getMinimumBalanceForRentExemption", size)

    async def alpenglow_check(self):
        """Raise unless we are on mainnet with Alpenglow consensus active."""
        gh = await self.genesis_hash()
        if gh != MAINNET_GENESIS:
            raise RpcError(f"not mainnet: genesis {gh}")
        acc = await self.account(ALPENGLOW_FEATURE)
        if not acc:
            raise RpcError("Alpenglow feature account missing")
        cert = await self.call("getAgGenesisCert")
        return {"genesis": gh, "ag_genesis_cert": cert}


async def slot_stream(ws_url, on_slot, stop):
    """Call on_slot(slot, t_ns_wall, t_ns_mono) for each slotSubscribe update; reconnect on drop."""
    import websockets
    sub = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "slotSubscribe"})
    while not stop.is_set():
        try:
            async with websockets.connect(ws_url, user_agent_header=UA, ping_interval=15,
                                          open_timeout=10, max_size=2**20) as ws:
                await ws.send(sub)
                async for raw in ws:
                    t_wall, t_mono = time.time_ns(), time.monotonic_ns()
                    msg = json.loads(raw)
                    res = msg.get("params", {}).get("result")
                    if res and "slot" in res:
                        on_slot(res["slot"], t_wall, t_mono)
                    if stop.is_set():
                        return
        except Exception:
            await asyncio.sleep(0.5)


def ws_url_for(http_url):
    if http_url.startswith(PUBLIC_RPC):
        return "wss://api.mainnet-beta.solana.com"
    return http_url.replace("https://", "wss://").replace("http://", "ws://")
