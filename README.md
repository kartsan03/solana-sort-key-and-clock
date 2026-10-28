# Solana: which sort key each validator uses, and how strictly in time

I sent my own small transactions straight to the leaders of 16 Solana mainnet validators (8 client types)
after the Alpenglow switch, and read back where they landed in each block. Two questions per validator:

1. **Which key orders its block?** Not just "higher fee goes first": I separate eight concrete fee rules,
   including Agave's integer priority ⌊R·10⁶/(C+1)⌋ from Firedancer's exact R/C, and a builder that counts
   the base fee from one that ignores it.
2. **How strictly, in time?** If a richer transaction arrives a few milliseconds after a cheaper one, can it
   still go first? The largest send gap at which it does is the validator's *overtaking horizon*.

## Findings

FINDINGS_PLACEHOLDER

Every row is traced to slots and signatures in [CLAIMS.md](CLAIMS.md); [REPORT.md](REPORT.md) has the full
results, dates, deviations and what went wrong.

![How a probe travels from my sender to a position in the block](figures/diagram.svg)

## How it works

- **Probe.** One legacy transaction shape everywhere: fee payer, a never-funded "lock" account, three
  compute-budget instructions (CU limit L, CU price p, loaded-data limit D) and a 0-lamport transfer to
  the lock. Only L, p and D change. They move the fee and the scheduling cost in different directions, so
  each candidate key ranks the same six probes differently.
- **Panels.** Six probes from six payers, all writing the same lock, sent together just before the
  leader's 4-slot window. They wait in the queue, the shared lock forces them to run one by one, and their
  order in the block is the scheduler's order. Two fixed panels make every pair of candidate keys disagree
  on at least two probe pairs. Control arms: six identical probes (tie-breaking), and six probes that
  each write their own lock (no contention).
- **Trains.** 10–12 equal probes sent one by one 4 ms or 12 ms apart inside the window, with the fee
  rising (or, as a control, falling) along the send order. FIFO keeps send order; a sorting scheduler
  lets later, richer probes overtake.
- **Route.** Unstaked QUIC directly to the TPU address each leader advertises, one transaction per
  stream, with every send time logged. For BAM and Harmonic validators that address is the
  block builder, so those results describe the validator *as reached through its advertised ingress*.
- **Schedule.** Calibration on 2026-10-27. Then three collection days in six 4-hour blocks across all UTC
  hours: day A (10-29) picks the key and horizon of each undocumented builder, days B and C (10-30, 10-31)
  test those picks on data they never saw. Agave, Jito and Firedancer are tested against their source code
  from day A.
- **Pre-registered.** Questions, candidate keys, decision rules and quotas were committed in
  [PREREG.md](PREREG.md) and [design/design.json](design/design.json) before the first campaign probe, and
  their hashes written on chain:
  memo #1 [`TywPFLUz…`](https://explorer.solana.com/tx/TywPFLUznyNThfq9hiKp34eikwW8ZHxs3xefwWfABCBsceRaSLJvnAPPk977XyTXSTJWGsMnW6i43cr2NGTwXxd)
  (commit `0bb3ee5`), memo #2 MEMO2_PLACEHOLDER (the day-A picks, before day B).

## Why this design

- **My own probes over other people's transactions.** Only my probes have known limits, fees, send times,
  send order and target, and only a shared lock makes their block order the scheduler's order.
- **Designed disagreements over fee ladders.** On an ordinary ladder of fees, every sensible key agrees,
  so "higher fee lands first" cannot tell the rules apart. The panels put the rules at odds on purpose,
  down to a 0.003% difference between Agave's and Firedancer's priority.
- **Window-level statistics.** Pairs inside one block are not independent. The window is the unit; a key
  is identified when it beats every rival in a majority of windows (exact binomial tests, Holm across the
  eight main validators), and its strictness is reported next to it. "No rule detected" is a valid answer.
- **A held-out day.** A key picked from day A has to pass on days B and C, with the picks fixed on chain
  before day B.
- **Horizon over a round length.** A layered order can come from batching rounds or from a queue that
  stalls; the horizon measures how strictly the key holds in time without claiming a mechanism.
- **Direct QUIC over RPC `sendTransaction`.** RPC hides the send time and the target, retries for you,
  and forwards to more than one leader.

## What this design does NOT separate

1. When a probe *arrived* at the leader or builder. I log send times; network jitter below ~1 ms is noise.
2. The validator's own scheduler from an upstream builder using the same comparator.
3. Keys outside the eight candidates that rank both panels identically (any monotone transform of
   reward/cost, for example).
4. Private operator settings (Firedancer pacing, Harmonic strategy, BAM plugins): I see behaviour, not
   configuration.
5. Staked or stake-weighted paths. I am an unstaked sender.
6. High fees and full blocks. My fees are tiny; block load is recorded, not controlled.
7. Execution order of non-conflicting transactions. Block order is not execution start.
8. A whole client family from one or two validators, or validators behind one shared builder endpoint
   from each other.
9. Bundles and tips (out of scope). Block-wide context may contain bundles.
10. Order among probes that did not land. Inclusion is reported separately.

## Reproduce

```sh
docker compose up                                        # offline: recompute every number from data/raw, diff with data/derived
docker compose run --rm verify                           # online: re-fetch a sample of claimed blocks (VERIFY_ALL=1 for all)
docker compose run --rm test                             # unit tests
docker compose run --rm dryrun                           # plan the next 15 min of real leader windows, send nothing
```

`docker compose up` fails on any difference from the committed numbers. Live sending needs `--live`,
`ITB_LIVE=1`, a `--max-spend-sol` limit and the key directory mounted read-only as a volume. Every send
reserves its worst-case fee in a ledger first, and the code refuses to pass 0.05 SOL in total; spend is
reconciled against on-chain balances after every block.

## Listing requirements → where

| Requirement | Where |
|---|---|
| ≥6 validators, ≥3 clients, own mainnet transactions after Alpenglow | [design/candidates.json](design/candidates.json), `data/raw/*/probes.jsonl.gz` (all slots ≥ 459,653,000, checked in code) |
| Ordering rule, how strictly, or no rule, per validator | Findings above, [REPORT.md](REPORT.md) §3, [data/derived/tables.md](data/derived/tables.md) |
| All raw data: signatures, slots, blocks | `data/raw/<run>/` (probes, outcomes, blocks, windows, snapshots, SHA256SUMS) |
| One-command reproduction | `docker compose up`; CI runs it on amd64 and arm64 |
| Dry run by default, live behind a flag, spend cap in code | `itb run` (dry unless `--live` + `ITB_LIVE=1`), [itb/ledger.py](itb/ledger.py) |
| Keys via env or volume, never in the repo | `ITB_KEYS_DIR` volume, read-only; pre-commit check in [.githooks/](.githooks/) |
| Why this design / what it does NOT separate | the two sections above |
| Date of every measurement, what went wrong | [REPORT.md](REPORT.md) §4–§6, `run.json` in every run folder |

## Cost

COST_PLACEHOLDER

## Repo map

`itb/`: sender, collector and analysis (`itb --help`). `design/`: panels, candidate keys, prediction
table, quotas, pre-registration hashes. `data/raw/`: every probe ever signed and every block it landed in.
`data/derived/`: results and tables recomputed by `docker compose up`. `figures/`: redrawn from the data.
