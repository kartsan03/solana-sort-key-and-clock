"""Burner keypair and the fee payers derived from it. Never prints or stores secrets."""
import hashlib
import json
import os
import pathlib

from solders.keypair import Keypair

N_PAYERS = 12  # payer 0 is the burner itself; 1..11 are derived
ROOT = pathlib.Path(__file__).resolve().parents[1]


def keypair_path():
    env = os.environ.get("ITB_KEYPAIR")
    if env:
        return pathlib.Path(env)
    d = os.environ.get("ITB_KEYS_DIR") or str(ROOT.parent / "keys")
    return pathlib.Path(d) / "burner.json"


def load_burner():
    p = keypair_path()
    if not p.exists():
        raise SystemExit(f"keypair not found (set ITB_KEYPAIR or mount the keys folder): {p.parent}")
    return Keypair.from_bytes(bytes(json.loads(p.read_text())))


def derive_payers(burner):
    seed = bytes(burner)[:32]
    out = [burner]
    for i in range(1, N_PAYERS):
        out.append(Keypair.from_seed(hashlib.sha256(b"itb-payer-v1" + seed + bytes([i])).digest()))
    return out


def public_info(payers):
    return {"burner": str(payers[0].pubkey()), "pubkeys": [str(k.pubkey()) for k in payers]}
