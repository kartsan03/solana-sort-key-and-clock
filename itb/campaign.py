"""Collection-day driver (six 4-hour blocks) and the design freeze."""
import argparse
import asyncio
import json
import pathlib
import sys
import time

from .cli import ROOT, STATE, cmd_plan, cmd_run, ledger, payers, pubkeys


async def cmd_campaign(a):
    """One collection day as N blocks of equal length: plan -> top up payers -> live run -> collect, per block."""
    import secrets
    from . import ops
    from .chain import Rpc
    from .ledger import single_process
    quotas = json.loads(pathlib.Path(a.quotas).read_text())
    rng = secrets.SystemRandom()
    t_day = time.mktime(time.strptime(a.date + "T00:00:00Z", "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
    block_h = 24 / a.blocks
    # split each daily quota over the blocks; remainders go to random blocks (logged in each plan)
    split = {}
    for v, q in quotas.items():
        split[v] = {}
        for st in ("K", "M"):
            n = q.get(st, 0)
            base, extra = divmod(n, a.blocks)
            bonus = set(rng.sample(range(a.blocks), extra))
            split[v][st] = [base + (b in bonus) for b in range(a.blocks)]
    for b in range(a.first_block, min(a.blocks, (a.last_block if a.last_block is not None else a.blocks - 1) + 1)):
        start = t_day + b * block_h * 3600
        if time.time() > start + block_h * 3600 - 900:
            print(f"block {b}: already over, skipped")
            continue
        run_id = f"{a.phase}-{a.date[5:7]}{a.date[8:10]}-b{b}"
        tfile = STATE / "plans" / f"{run_id}.targets.json"
        tfile.parent.mkdir(parents=True, exist_ok=True)
        tfile.write_text(json.dumps({v: dict(quotas[v], K=split[v]["K"][b], M=split[v]["M"][b]) for v in quotas}, indent=1))
        while time.time() < start - 150:
            await asyncio.sleep(10)
        lead_min = max(1.0, (start - time.time()) / 60)
        hours = (start + block_h * 3600 - 600 - time.time()) / 3600 - lead_min / 60
        await cmd_plan(argparse.Namespace(targets=str(tfile), run_id=run_id, hours=hours, start_in_min=lead_min,
                                          start_utc=None, ms_per_slot=213.0))
        rpc = Rpc()
        with single_process(STATE / "live.lock"):
            r, _ = await ops.reconcile(rpc, ledger(), pubkeys(), f"pre-fund {run_id}")
            if r["halted"]:
                sys.exit(f"campaign stopped: {ledger().get('halt')}")
            await ops.fund_payers(rpc, ledger(), payers(), a.float_lamports, f"ops-{run_id}")
        await rpc.close()
        await cmd_run(argparse.Namespace(plan=str(STATE / "plans" / f"{run_id}.json"), live=True,
                                         max_spend_sol=a.block_max_sol, lambda_ms=a.lambda_ms))
        print(f"block {b} done: {ledger().summary()}")


def cmd_freeze(a):
    """Write design/design.json (everything fixed before the campaign) and print memo #1."""
    import hashlib
    import subprocess
    from . import analyze, clock, design, run
    sha = lambda path: hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
    camp = json.loads((ROOT / "design" / "campaign.json").read_text())
    d = {"created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
         "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
         "files": {f: sha(ROOT / f) for f in ("design/panels.json", "design/candidates.json",
                                              "design/prediction_table.md", "design/campaign.json")},
         "campaign": camp,
         "randomisation": {"k_arms": {"K-main": 0.75, "K-null": 0.10, "K-free": 0.15}, "panel_offset_ms": [-600, -200],
                           "train_specs": {k: {"probes": n, "spacing_ms": sp} for k, (n, sp) in design.TRAIN_SPECS.items()},
                           "train_increasing_share": 0.8, "train_phase_ms": [30, 70], "source": "OS randomness, logged"},
         "timing": {"lambda_ms": 60.0, "short_fuse_blocks": list(clock.SHORT_FUSE), "min_gap_s": run.MIN_GAP_S},
         "analysis": {"theta_identification": analyze.THETA_ID, "strict_lower_bound": analyze.STRICT,
                      "alpha": analyze.ALPHA, "null_permutations": analyze.NULL_PERMS, "seed": analyze.SEED,
                      "evaluable_panel_min_probes": 4, "evaluable_train_min": {"t4": 8, "t12": 7},
                      "documented_keys": analyze.DOCUMENTED}}
    out = ROOT / "design" / "design.json"
    out.write_text(json.dumps(d, indent=1))
    print(f"wrote {out}")
    print("after committing PREREG.md + design/design.json, memo #1 =")
    print(f"itb-prereg <commit> {sha(ROOT / 'PREREG.md')} {sha(out)}")

