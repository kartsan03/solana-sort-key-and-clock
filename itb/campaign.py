"""Collection-day driver (six 4-hour blocks), the design freeze and the day-B predictions."""
import asyncio
import json
import pathlib
import sys
import time

from .cli import ROOT, STATE, build_parser, cmd_plan, cmd_run, ledger, live_pubkeys, payers


def block_targets(quotas, split, b):
    """One block's target file. Campaign trains draw spacing and direction per window (PREREG), so fixed
    train_specs in a quota file (a calibration setting) are dropped here."""
    return {v: {**{k: x for k, x in q.items() if k != "train_specs"}, "K": split[v]["K"][b], "M": split[v]["M"][b]}
            for v, q in quotas.items()}


def plan_args(targets, run_id, hours, lead_min):
    """cmd_plan arguments, parsed like the command line so no option can go missing."""
    return build_parser().parse_args(["plan", "--targets", str(targets), "--run-id", run_id,
                                      "--hours", str(hours), "--start-in-min", str(lead_min)])


def run_args(plan, lambda_ms, max_spend_sol=None):
    """cmd_run arguments; live when a spend limit is given."""
    extra = ["--live", "--max-spend-sol", str(max_spend_sol)] if max_spend_sol else []
    return build_parser().parse_args(["run", "--plan", str(plan), "--lambda-ms", str(lambda_ms), *extra])


async def cmd_campaign(a):
    """One collection day as N blocks of equal length: plan -> top up payers -> live run -> collect, per block."""
    import secrets
    from . import ops
    from .chain import Rpc
    from .ledger import single_process
    quotas = json.loads(pathlib.Path(a.quotas).read_text())
    quotas = quotas["days"][a.phase] if "days" in quotas else quotas    # design/campaign.json or a plain map
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
        run_id = ("dry-" if a.dry else "") + f"{a.phase}-{a.date[5:7]}{a.date[8:10]}-b{b}"
        tfile = STATE / "plans" / f"{run_id}.targets.json"
        tfile.parent.mkdir(parents=True, exist_ok=True)
        tfile.write_text(json.dumps(block_targets(quotas, split, b), indent=1))
        while time.time() < start - 150:
            await asyncio.sleep(10)
        lead_min = max(1.0, (start - time.time()) / 60)
        hours = (start + block_h * 3600 - 600 - time.time()) / 3600 - lead_min / 60
        await cmd_plan(plan_args(tfile, run_id, hours, lead_min))
        if a.dry:
            await cmd_run(run_args(STATE / "plans" / f"{run_id}.json", a.lambda_ms))
            continue
        rpc = Rpc()
        with single_process(STATE / "live.lock"):
            led = ledger()
            r, _ = await ops.reconcile(rpc, led, live_pubkeys(led), f"pre-fund {run_id}")
            if r["halted"]:
                sys.exit(f"campaign stopped: {ledger().get('halt')}")
            await ops.fund_payers(rpc, ledger(), payers(), a.float_lamports, f"ops-{run_id}")
        await rpc.close()
        await cmd_run(run_args(STATE / "plans" / f"{run_id}.json", a.lambda_ms, a.block_max_sol))
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
                      "evaluable_panel_min_probes": 4, "min_evaluable_panels": analyze.MIN_EVALUABLE, "evaluable_train_min": {"t4": 8, "t12": 7},
                      "documented_keys": analyze.DOCUMENTED}}
    out = ROOT / "design" / "design.json"
    out.write_text(json.dumps(d, indent=1))
    print(f"wrote {out}")
    print("after committing PREREG.md + design/design.json, memo #1 =")
    print(f"itb-prereg <commit> {sha(ROOT / 'PREREG.md')} {sha(out)}")



def cmd_predict(a):
    """Write design/predictions-dayB.json from day A by the pre-registered rule and print memo #2.

    Agave, JitoLabs and Firedancer keep their source-code key; every other Tier-1 validator gets its
    day-A best key, plus its day-A overtaking horizon where it had trains. Tier 2 (replication, day C)
    gets the Tier-1 pick for the same client. Reads data/derived/results.json (run `itb analyze --no-check` first).
    """
    import hashlib
    from .analyze import DOCUMENTED
    res = json.loads((ROOT / "data" / "derived" / "results.json").read_text())
    cands = json.loads((ROOT / "design" / "candidates.json").read_text())
    day_a, m = res["calls"]["dayA"], res["study_m"]
    if not day_a:
        sys.exit("no day-A results in data/derived/results.json")
    picks = {}
    for v, c in cands.items():
        r = day_a.get(v) or {}
        doc = DOCUMENTED.get(c["family"])
        if c.get("tier") != 1 or not (doc or r.get("key")):
            continue
        picks[v] = {"family": c["family"], "tier": 1, "key": doc or r["key"],
                    "basis": "source code" if doc else "day A best key",
                    "horizon_ms": m.get(f"{v}|dayA", {}).get("increasing", {}).get("horizon_ms"),
                    "dayA_best": r.get("key"), "dayA_verdict": r.get("verdict")}
    by_family = {p["family"]: p["key"] for p in picks.values()}
    for v, c in cands.items():
        if c.get("tier") == 2 and c["family"] in by_family:
            picks[v] = {"family": c["family"], "tier": 2, "key": by_family[c["family"]],
                        "basis": "Tier-1 pick for the same client", "horizon_ms": None}
    sha = lambda b: hashlib.sha256(b).hexdigest()
    out = ROOT / "design" / "predictions-dayB.json"
    ex = ROOT / "design" / "exploratory-dayB.json"   # hypotheses formed on day A, outside the registered rule
    out.write_text(json.dumps({"created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                               "results_sha256": sha((ROOT / "data" / "derived" / "results.json").read_bytes()),
                               "validators": picks,
                               **({"exploratory": json.loads(ex.read_text())} if ex.exists() else {})},
                              indent=1, sort_keys=True))
    print(f"wrote {out} ({len(picks)} validators)")
    print(f"after committing it, memo #2 = itb-predictions <commit> {sha(out.read_bytes())}")
