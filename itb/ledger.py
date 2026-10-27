"""Campaign-wide spend ledger with a compiled fee cap.

Rules:
- Before any send, the worst-case fee of every transaction is reserved here and its
  signed bytes are stored (one fsync'd SQLite transaction). Only then may it be sent.
- A reservation is never released because a transaction "seems" not to have landed.
  Reservations are released only by balance reconciliation, after their blockhash
  has expired: spent = baseline + inflows - outflows - (sum of all our balances).
- Spending that reservations cannot explain, or an unlogged inflow, halts all sends.
"""
import contextlib
import fcntl
import json
import sqlite3
import time

CAP_LAMPORTS = 50_000_000  # 0.05 SOL: total fees over the whole campaign, all commands

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS txs (
  sig TEXT PRIMARY KEY, run_id TEXT, kind TEXT, payer TEXT, max_fee INTEGER NOT NULL,
  last_valid INTEGER NOT NULL, raw BLOB NOT NULL, info TEXT, created_ns INTEGER,
  sent_ns INTEGER, send_result TEXT, released INTEGER);
CREATE TABLE IF NOT EXISTS flows (
  id INTEGER PRIMARY KEY, kind TEXT CHECK (kind IN ('in','out')), sig TEXT UNIQUE,
  amount INTEGER NOT NULL, note TEXT, t_ns INTEGER);
CREATE TABLE IF NOT EXISTS recon (
  id INTEGER PRIMARY KEY, t_ns INTEGER, slot INTEGER, height INTEGER, total INTEGER,
  spent INTEGER, released_n INTEGER, released_fee INTEGER, open_fee INTEGER,
  unexplained INTEGER, note TEXT);
"""


class CapExceeded(Exception):
    pass


class Halted(Exception):
    pass


class Ledger:
    def __init__(self, path):
        self.path = str(path)
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(SCHEMA)

    # ---- meta ----
    def get(self, k, default=None):
        row = self.db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, k, v):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, json.dumps(v)))

    def init_baseline(self, wallets, balances, slot):
        if self.get("baseline") is not None:
            return False
        self.put("wallets", list(wallets))
        self.put("baseline", {"total": sum(balances[w] for w in wallets), "slot": slot, "t_ns": time.time_ns()})
        self.put("spent", 0)
        self.put("halt", None)
        return True

    # ---- accounting ----
    def spent(self):
        return self.get("spent", 0)

    def reserved(self):
        return self.db.execute("SELECT COALESCE(SUM(max_fee),0) FROM txs WHERE released IS NULL").fetchone()[0]

    def committed(self):
        return self.spent() + self.reserved()

    def remaining(self):
        return CAP_LAMPORTS - self.committed()

    def check_not_halted(self):
        h = self.get("halt")
        if h:
            raise Halted(f"ledger halted: {h}")

    def reserve(self, txs, run_limit=None):
        """Atomically reserve worst-case fees and store signed bytes for `txs` (list of dicts)."""
        need = sum(t["max_fee"] for t in txs)
        cur = self.db.cursor()
        cur.execute("BEGIN IMMEDIATE")
        try:
            self.check_not_halted()
            committed = self.committed()
            if committed + need > CAP_LAMPORTS:
                raise CapExceeded(f"cap: committed {committed} + {need} > {CAP_LAMPORTS}")
            if run_limit is not None and committed + need > run_limit:
                raise CapExceeded(f"run limit: committed {committed} + {need} > {run_limit}")
            now = time.time_ns()
            cur.executemany(
                "INSERT INTO txs (sig, run_id, kind, payer, max_fee, last_valid, raw, info, created_ns) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                [(t["sig"], t["run_id"], t["kind"], t["payer"], t["max_fee"], t["last_valid"], t["raw"],
                  json.dumps(t.get("info", {})), now) for t in txs])
            cur.execute("COMMIT")
        except BaseException:
            cur.execute("ROLLBACK")
            raise

    def mark_sent(self, sig, sent_ns, result):
        self.db.execute("UPDATE txs SET sent_ns=?, send_result=? WHERE sig=?", (sent_ns, result, sig))

    def record_flow(self, kind, sig, amount, note=""):
        self.db.execute("INSERT INTO flows (kind, sig, amount, note, t_ns) VALUES (?,?,?,?,?)",
                        (kind, sig, amount, note, time.time_ns()))

    def flows_total(self):
        row = self.db.execute("SELECT COALESCE(SUM(CASE kind WHEN 'in' THEN amount ELSE -amount END),0) FROM flows").fetchone()
        return row[0]

    def reconcile(self, balances, height, slot, note=""):
        """Release expired reservations against the on-chain balance total. Halts on anything unexplained."""
        wallets = self.get("wallets")
        base = self.get("baseline")
        if base is None:
            raise RuntimeError("ledger has no baseline")
        total = sum(balances[w] for w in wallets)
        spent_now = base["total"] + self.flows_total() - total
        spent_prev = self.spent()
        cur = self.db.cursor()
        cur.execute("BEGIN IMMEDIATE")
        try:
            exp_n, exp_fee = cur.execute(
                "SELECT COUNT(*), COALESCE(SUM(max_fee),0) FROM txs WHERE released IS NULL AND last_valid < ?",
                (height,)).fetchone()
            open_fee = cur.execute(
                "SELECT COALESCE(SUM(max_fee),0) FROM txs WHERE released IS NULL AND last_valid >= ?",
                (height,)).fetchone()[0]
            unexplained = max(0, spent_now - (spent_prev + exp_fee + open_fee))
            inflow = spent_now < spent_prev
            cur.execute("INSERT INTO recon (t_ns, slot, height, total, spent, released_n, released_fee, open_fee, "
                        "unexplained, note) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (time.time_ns(), slot, height, total, spent_now, exp_n, exp_fee, open_fee,
                         unexplained, note))
            rid = cur.lastrowid
            if unexplained or inflow:
                why = (f"unexplained spend {unexplained}" if unexplained
                       else f"unlogged inflow {spent_prev - spent_now}") + f" at recon {rid}"
                cur.execute("INSERT OR REPLACE INTO meta VALUES ('halt', ?)", (json.dumps(why),))
            else:
                cur.execute("UPDATE txs SET released=? WHERE released IS NULL AND last_valid < ?", (rid, height))
                cur.execute("INSERT OR REPLACE INTO meta VALUES ('spent', ?)", (json.dumps(spent_now),))
            cur.execute("COMMIT")
        except BaseException:
            cur.execute("ROLLBACK")
            raise
        return {"recon": rid, "total": total, "spent": spent_now, "released": exp_n, "released_fee": exp_fee,
                "open_fee": open_fee, "unexplained": unexplained, "halted": bool(unexplained or inflow)}

    def unhalt(self, reason):
        self.put("halt", None)
        self.put("unhalt_" + str(time.time_ns()), reason)

    def txs(self, where="1=1", args=()):
        cols = ("sig", "run_id", "kind", "payer", "max_fee", "last_valid", "raw", "info", "created_ns",
                "sent_ns", "send_result", "released")
        return [dict(zip(cols, r)) for r in self.db.execute(f"SELECT {', '.join(cols)} FROM txs WHERE {where}", args)]

    def summary(self):
        return {"cap": CAP_LAMPORTS, "spent": self.spent(), "reserved": self.reserved(),
                "remaining": self.remaining(), "halt": self.get("halt"),
                "n_txs": self.db.execute("SELECT COUNT(*) FROM txs").fetchone()[0]}


@contextlib.contextmanager
def single_process(lock_path):
    """Only one live/ops process at a time."""
    f = open(lock_path, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(f"another live/ops process holds {lock_path}")
    try:
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()
