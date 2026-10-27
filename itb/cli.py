"""Command line: design, plan, run (dry by default), collect, ops, analyze, verify, sim."""
import argparse
import asyncio
import gzip
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
RAW = ROOT / "data" / "raw"
LAMPORTS_PER_SOL = 1_000_000_000


def jl(path):
    op = gzip.open if str(path).endswith(".gz") else open
    with op(path, "rt") as f:
        return [json.loads(x) for x in f if x.strip()]


def ledger():
    from .ledger import Ledger
    STATE.mkdir(exist_ok=True)
    return Ledger(STATE / "ledger.sqlite")


def payers():
    from .wallet import derive_payers, load_burner
    return derive_payers(load_burner())


def pubkeys():
    return json.loads((ROOT / "design" / "wallets.json").read_text())["pubkeys"]


async def cmd_plan(a):
    from . import cluster, run
    from .chain import Rpc
    from .design import panels_from_json
    rpc = Rpc()
    targets = json.loads(pathlib.Path(a.targets).read_text())
    panels = panels_from_json(json.loads((ROOT / "design" / "panels.json").read_text())["panels"])
    nodes = cluster.compact_nodes(await rpc.cluster_nodes())
    cur = await rpc.slot("confirmed")
    if a.start_utc:
        t0 = time.mktime(time.strptime(a.start_utc, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
        start = cur + int((t0 - time.time()) * 1000 / a.ms_per_slot)
    else:
        start = cur + int(a.start_in_min * 60 / a.ms_per_slot * 1000)
    end = start + int(a.hours * 3600 / a.ms_per_slot * 1000)
    sched = await cluster.epoch_schedule(rpc, start, end)
    quotas = {k: {"K": v.get("K", 0), "M": v.get("M", 0)} for k, v in targets.items()}
    plan = run.sample_windows(sched, nodes, quotas, start, end, a.ms_per_slot, cur)
    k_index = 0
    specs_used = {}
    for i, w in enumerate(plan):
        w["run_id"] = a.run_id
        w["window_id"] = f"{a.run_id}-{i:04d}"
        w["epoch_start"] = sched["start"]
        t = targets[w["target"]]
        spec = None
        if w["study"] == "M" and t.get("train_specs"):
            used = specs_used.setdefault(w["target"], [])
            spec = t["train_specs"][len(used) % len(t["train_specs"])]
            used.append(spec)
        run.plan_probes(w, panels, k_index, force_arm=t.get("force_arm"), train_spec=spec)
        k_index += w["study"] == "K"
    out = {"run_id": a.run_id, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "epoch": sched["epoch"], "epoch_start": sched["start"], "slot_range": [start, end],
           "targets": targets, "windows": plan}
    (STATE / "plans").mkdir(parents=True, exist_ok=True)
    path = STATE / "plans" / f"{a.run_id}.json"
    path.write_text(json.dumps(out, indent=1))
    n_tx = sum(len(w["probes"]) for w in plan)
    spend = sum(w["max_spend"] for w in plan)
    per = {}
    for w in plan:
        per.setdefault(w["target"][:8], []).append(w["study"])
    print(f"plan {path}: {len(plan)} windows, {n_tx} transactions, at most {spend:,} lamports "
          f"({spend / LAMPORTS_PER_SOL:.6f} SOL)")
    for t, s in per.items():
        print(f"  {t}: K={s.count('K')} M={s.count('M')} ({cluster.leader_type(nodes.get(next(k for k in targets if k.startswith(t)))) })")
    if plan:
        print(f"  first window ~{plan[0]['eta_utc']} UTC, last ~{plan[-1]['eta_utc']} UTC")
    await rpc.close()


async def cmd_run(a):
    from . import ops, run
    from .chain import Rpc
    from .ledger import single_process
    plan = json.loads(pathlib.Path(a.plan).read_text())
    run_id = plan["run_id"]
    windows = plan["windows"]
    spend = sum(w["max_spend"] for w in windows)
    n_tx = sum(len(w["probes"]) for w in windows)
    print(f"This plan sends {n_tx} transactions to {len({w['target'] for w in windows})} leaders "
          f"in {len(windows)} windows and spends at most {spend:,} lamports ({spend / LAMPORTS_PER_SOL:.6f} SOL).")
    rpc = Rpc()
    led = ledger()
    if a.live:
        if os.environ.get("ITB_LIVE") != "1":
            sys.exit("live run refused: set ITB_LIVE=1 as well as --live")
        if not a.max_spend_sol or a.max_spend_sol <= 0:
            sys.exit("live run refused: a positive --max-spend-sol is required")
        max_l = int(round(a.max_spend_sol * LAMPORTS_PER_SOL))
        if max_l > led.remaining():
            sys.exit(f"live run refused: max spend {max_l} > remaining cap {led.remaining()}")
        info = await rpc.alpenglow_check()
        cur = await rpc.slot("confirmed")
        if min(w["slot0"] for w in windows) < 459_653_000 or cur < 459_653_000:
            sys.exit("refused: slots before Alpenglow consensus")
        r, _ = await ops.reconcile(rpc, led, pubkeys(), f"pre-run {run_id}")
        if r["halted"]:
            sys.exit(f"live run refused: reconciliation halted: {led.get('halt')}")
        run_limit = led.committed() + max_l
        ps = payers()
        print(f"LIVE: run limit {max_l:,} lamports; ledger {led.summary()}")
    else:
        info, run_limit, ps = {"dry_run": True}, None, None
        from solders.keypair import Keypair
        ps = [Keypair() for _ in range(12)]   # throwaway keys: dry runs never touch the real ones
        print("DRY RUN: nothing will be sent or spent.")
    run_dir = RAW / run_id if a.live else STATE / "dry" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    meta = {"run_id": run_id, "live": a.live, "plan": plan, "chain": info, "lambda_ms": a.lambda_ms,
            "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "max_spend_lamports": run_limit and max_l}
    (run_dir / "run.json").write_text(json.dumps(meta, indent=1))
    keep = {w["target"] for w in windows} | {w["prev_leader"] for w in windows if w["prev_leader"]}
    with single_process(STATE / ("live.lock" if a.live else "dry.lock")):
        runner = run.Runner(rpc, led, ps, run_dir, a.live, run_limit, a.lambda_ms)
        last_valid = await runner.execute(windows, None, plan["epoch_start"], keep)
        if a.live:
            print("waiting for every blockhash to expire before reconciling ...")
            while await rpc.block_height("finalized") <= last_valid + 2:
                await asyncio.sleep(5)
            r, _ = await ops.reconcile(rpc, led, pubkeys(), f"post-run {run_id}")
            print(f"reconciled: {r}")
            await do_collect(rpc, run_dir)
    await rpc.close()


async def do_collect(rpc, run_dir):
    from . import collect, run
    run_dir = pathlib.Path(run_dir)
    pick = lambda n: run_dir / f"{n}.jsonl" if (run_dir / f"{n}.jsonl").exists() else run_dir / f"{n}.jsonl.gz"
    windows, probes = jl(pick("windows")), jl(pick("probes"))
    height = await rpc.block_height("finalized")
    outcomes, blocks = await collect.collect_run(rpc, windows, probes, height)
    for name, rows in (("outcomes", outcomes), ("blocks", blocks)):
        with open(run_dir / f"{name}.jsonl", "w") as f:
            for r in rows:
                f.write(json.dumps(r, separators=(",", ":")) + "\n")
    counts = {}
    for o in outcomes:
        counts[o["outcome"]] = counts.get(o["outcome"], 0) + 1
    print(f"collected {len(outcomes)} probes: {counts}")
    run.finalize(run_dir)


async def cmd_collect(a):
    from .chain import Rpc
    rpc = Rpc()
    await do_collect(rpc, RAW / a.run_id)
    await rpc.close()


async def cmd_ops(a):
    from . import ops
    from .chain import Rpc
    from .wallet import public_info
    rpc = Rpc()
    led = ledger()
    pks = pubkeys()
    if a.op == "keyinfo":
        info = public_info(payers())
        print(json.dumps(info, indent=1))
    elif a.op == "status":
        bal, slot = await ops.balances(rpc, pks)
        print(f"slot {slot}; balances (finalized):")
        for pk in pks:
            print(f"  {pk}  {bal[pk]:>12,}")
        print(f"  total {sum(bal.values()):,}")
        print(json.dumps(led.summary()))
    elif a.op == "init":
        bal, slot = await ops.balances(rpc, pks)
        print("baseline set" if led.init_baseline(pks, bal, slot) else "baseline already set", sum(bal.values()))
    elif a.op == "reconcile":
        r, _ = await ops.reconcile(rpc, led, pks, a.arg or "manual")
        print(json.dumps(r))
    elif a.op == "labels":
        from . import cluster
        tok = cluster.validators_app_token()
        if not tok:
            sys.exit("no validators.app token")
        ids = list(json.loads((ROOT / "design" / "candidates.json").read_text()))
        snap = await cluster.validators_app_snapshot(tok, ids)
        snap["gossip"] = (await cluster.nodes_snapshot(rpc, set(ids)))["nodes"]
        snap["kobe"] = {k: v for k, v in (await cluster.kobe_snapshot())["validators"].items() if k in ids}
        out = RAW / "labels" / time.strftime("%Y%m%dT%H%M%SZ.json", time.gmtime())
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(snap, indent=1, sort_keys=True))
        print(f"wrote {out}: {len(snap['validators'])} validators.app labels")
    elif a.op == "unhalt":
        led.unhalt(a.arg or "")
        print("unhalted")
    else:
        from .ledger import single_process
        with single_process(STATE / "live.lock"):
            r, _ = await ops.reconcile(rpc, led, pks, f"pre-{a.op}")
            if r["halted"]:
                sys.exit(f"refused: {led.get('halt')}")
            if a.op == "fund":
                await ops.fund_payers(rpc, led, payers(), int(a.arg), f"ops-{int(time.time())}")
            elif a.op == "memo":
                await ops.memo(rpc, led, payers()[0], a.arg, f"ops-{int(time.time())}")
            elif a.op == "inflow":
                amt = await ops.inflow(rpc, led, a.arg, set(pks), a.note or "")
                print(f"recorded inflow {amt}")
            elif a.op == "sweep":
                if os.environ.get("ITB_LIVE") != "1":
                    sys.exit("sweep refused: set ITB_LIVE=1")
                bal, _ = await ops.sweep(rpc, led, payers(), f"ops-sweep-{int(time.time())}")
                print("after sweep:", bal)
    await rpc.close()


def main(argv=None):
    p = argparse.ArgumentParser(prog="itb")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("design")
    s.add_argument("--seed", type=int, default=20261027)
    s = sub.add_parser("plan")
    s.add_argument("--targets", required=True)
    s.add_argument("--run-id", required=True)
    s.add_argument("--hours", type=float, default=1.0)
    s.add_argument("--start-in-min", type=float, default=2.0)
    s.add_argument("--start-utc", help="e.g. 2026-10-29T00:00:00Z (overrides --start-in-min)")
    s.add_argument("--ms-per-slot", type=float, default=213.0)
    s = sub.add_parser("run")
    s.add_argument("--plan", required=True)
    s.add_argument("--live", action="store_true")
    s.add_argument("--max-spend-sol", type=float)
    s.add_argument("--lambda-ms", type=float, default=60.0)
    s = sub.add_parser("campaign")
    s.add_argument("--phase", required=True, choices=["A", "B", "C", "D", "pilot"])
    s.add_argument("--date", required=True, help="UTC day, e.g. 2026-10-29")
    s.add_argument("--quotas", required=True)
    s.add_argument("--blocks", type=int, default=6)
    s.add_argument("--first-block", type=int, default=0)
    s.add_argument("--last-block", type=int)
    s.add_argument("--block-max-sol", type=float)
    s.add_argument("--dry", action="store_true", help="plan and rehearse every block; no funding, no sends")
    s.add_argument("--float-lamports", type=int, default=600_000)
    s.add_argument("--lambda-ms", type=float, default=60.0)
    sub.add_parser("freeze")
    s = sub.add_parser("collect")
    s.add_argument("--run-id", required=True)
    s = sub.add_parser("ops")
    s.add_argument("op", choices=["keyinfo", "status", "init", "reconcile", "fund", "memo", "inflow", "sweep", "unhalt", "labels"])
    s.add_argument("arg", nargs="?")
    s.add_argument("--note")
    s = sub.add_parser("analyze")
    s.add_argument("--no-check", action="store_true")
    s = sub.add_parser("verify")
    s.add_argument("--all", action="store_true")
    s.add_argument("--sample", type=int, default=40)
    s = sub.add_parser("sim")
    s.add_argument("--reps", type=int, default=200)
    a = p.parse_args(argv)
    if a.cmd == "design":
        from .design import panel_report, write_design
        panels = write_design(a.seed, ROOT / "design")
        for n, pnl in panels.items():
            print(n, panel_report(pnl))
    elif a.cmd == "plan":
        asyncio.run(cmd_plan(a))
    elif a.cmd == "run":
        asyncio.run(cmd_run(a))
    elif a.cmd == "freeze":
        from .campaign import cmd_freeze
        cmd_freeze(a)
    elif a.cmd == "collect":
        asyncio.run(cmd_collect(a))
    elif a.cmd == "campaign":
        if not a.dry and (os.environ.get("ITB_LIVE") != "1" or not a.block_max_sol):
            sys.exit("live campaign refused: set ITB_LIVE=1 and a positive --block-max-sol (or use --dry)")
        from .campaign import cmd_campaign
        asyncio.run(cmd_campaign(a))
    elif a.cmd == "ops":
        asyncio.run(cmd_ops(a))
    elif a.cmd == "analyze":
        from .analyze import main as analyze_main
        sys.exit(analyze_main(check=not a.no_check))
    elif a.cmd == "verify":
        from .verify import main as verify_main
        sys.exit(asyncio.run(verify_main(sample=None if a.all else a.sample)))
    elif a.cmd == "sim":
        from .sim import main as sim_main
        sim_main(a.reps)


if __name__ == "__main__":
    main()
