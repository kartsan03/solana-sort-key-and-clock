"""Unstaked QUIC sender to a leader's advertised TPU, one transaction per unidirectional stream.

Agave requires a client certificate (any self-signed ed25519 cert; ours maps to no stake),
ALPN "solana-tpu", idles out after 30 s and admits 8 new connections per IP per minute,
so connections are opened once per endpoint and kept alive with pings.
"""
import asyncio
import contextlib
import datetime
import os
import ssl
import tempfile
import time

from aioquic.asyncio.client import connect
from aioquic.quic.configuration import QuicConfiguration
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.x509.oid import NameOID

ALPN = "solana-tpu"


def _client_cert():
    key = ed25519.Ed25519PrivateKey.generate()
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Solana node")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30)).sign(key, None))
    return cert, key


class TpuPool:
    def __init__(self, connect_timeout=2.5):
        cert, key = _client_cert()
        self._pem = tempfile.NamedTemporaryFile("wb", suffix=".pem", delete=False)
        self._pem.write(cert.public_bytes(serialization.Encoding.PEM))
        self._pem.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
        self._pem.close()
        self.timeout = connect_timeout
        self.conns = {}
        self.stacks = {}
        self.keepalive = {}

    def _config(self):
        cfg = QuicConfiguration(is_client=True, alpn_protocols=[ALPN], verify_mode=ssl.CERT_NONE,
                                idle_timeout=25.0, server_name="localhost")
        cfg.load_cert_chain(self._pem.name)
        return cfg

    def alive(self, addr):
        c = self.conns.get(addr)
        return c is not None and not c._closed.is_set()

    async def get(self, addr):
        """Open (or reuse) a connection; returns (protocol, handshake_ms) or raises."""
        if self.alive(addr):
            return self.conns[addr], 0.0
        await self.drop(addr)
        host, _, port = addr.rpartition(":")
        stack = contextlib.AsyncExitStack()
        t0 = time.monotonic()
        try:
            proto = await asyncio.wait_for(
                stack.enter_async_context(connect(host, int(port), configuration=self._config(), wait_connected=True)),
                self.timeout)
        except BaseException:
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(stack.aclose(), 1)
            raise
        self.conns[addr], self.stacks[addr] = proto, stack
        self.keepalive[addr] = asyncio.create_task(self._ping(addr, proto))
        return proto, (time.monotonic() - t0) * 1000

    async def _ping(self, addr, proto):
        with contextlib.suppress(Exception):
            while not proto._closed.is_set():
                await asyncio.sleep(5)
                await asyncio.wait_for(proto.ping(), 5)

    def send(self, addr, data):
        """Write one transaction on a fresh uni stream and flush. Returns (stream_id, t_wall_ns, t_mono_ns)."""
        proto = self.conns[addr]
        q = proto._quic
        sid = q.get_next_available_stream_id(is_unidirectional=True)
        q.send_stream_data(sid, data, end_stream=True)
        t_wall, t_mono = time.time_ns(), time.monotonic_ns()
        proto.transmit()
        return sid, t_wall, t_mono

    def acked(self, addr, sid):
        """'acked' if the peer acknowledged the whole stream, 'pending' if not yet, 'closed' if the connection died."""
        proto = self.conns.get(addr)
        if proto is None or proto._closed.is_set():
            return "closed"
        st = proto._quic._streams.get(sid)
        if st is None:
            return "acked"  # fully acked streams are discarded by aioquic
        return "acked" if st.sender.is_finished else "pending"

    async def drop(self, addr):
        task = self.keepalive.pop(addr, None)
        if task:
            task.cancel()
        stack = self.stacks.pop(addr, None)
        self.conns.pop(addr, None)
        if stack:
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(stack.aclose(), 1)

    async def close(self):
        for addr in list(self.conns):
            await self.drop(addr)
        with contextlib.suppress(OSError):
            os.unlink(self._pem.name)


async def sleep_until_mono(t_ns):
    """Sleep until monotonic time t_ns; the last ~2 ms are spun for sub-ms precision."""
    while True:
        left = t_ns - time.monotonic_ns()
        if left <= 0:
            return
        if left > 2_500_000:
            await asyncio.sleep((left - 2_000_000) / 1e9)
        else:
            while time.monotonic_ns() < t_ns:
                pass
            return
