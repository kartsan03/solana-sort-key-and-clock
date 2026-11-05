# Solana: which sort key each validator uses, and how strictly in time

I sent my own small transactions straight to the leaders of 16 Solana mainnet validators (8 client types)
after the Alpenglow switch and read where they landed in each block. For each validator I ask which *key*
(sorting rule) orders my competing transactions in its block, and how strictly that holds in time. In short:
Agave and Firedancer use two different exact rules, FireBAM follows Agave's, one Jito validator sorted by
total fee on its one measured day, and Harmonic fits a formula outside the usual list.

## Findings

Measured 2026-10-29 to 11-01 (UTC), across all hours, plus an exploratory Harmonic test on 11-02.
A *panel* is six probes sent together. A *full window* means all six landed in one block of the target's
4-slot leader window. The exact-order column counts matches / full windows. The *overtaking horizon* is
the largest send gap at which a later, richer probe lands first in at least half of pairs; each rests on
one to seven trains per day, and 44 ms is the longest gap my 4 ms trains can show.

| Client | Key that orders queued transactions | Full windows, exact order | Overtaking horizon (uncontrolled) |
|---|---|---|---|
| Agave | Agave's integer priority `agave_int` | 89 / 89 | 0 ms |
| Jito, `E1r4Psq8` | `agave_int` | 69 / 69 | 0 ms |
| Jito, `C8Bey3LK` | total fee (5,000 + priority fee); one day, exploratory | 14 / 15 | not measured |
| AgaveBam | `agave_int` | 75 / 75 | 16 ms |
| FireBAM | `agave_int`, not Firedancer's rule | 80 / 80 | 24 to ≥44 ms |
| Rakurai | `agave_int` | 100 / 100 | 0 ms on two days of three |
| Firedancer | Firedancer's exact ratio `fd_exact` | 71 / 77 | 0 ms |
| Harmonic (Agave and Firedancer) | none of my eight keys; soft-capped formula fits (exploratory) | 108 / 108 days B–D (48 / 48 on P1, the panel that tells it from `agave_int`); 49 / 51 on discovery day A | 12–24 ms |

1. **Two exact rules.** Agave and four forks or builders divide R by C+1 (R = priority fee + 2,500;
   C = scheduling cost; Agave's code also rounds down, which my panels cannot see). Firedancer uses exact R/C.
   *Fingerprint pairs* are probe pairs these rules rank oppositely, even when priorities differ by only
   0.003%. Every pair went the predicted way in every full window. On equal priority Firedancer takes the
   later-sent probe first (192 of 195 pairs).
2. **Builder and client can differ.** FireBAM runs Firedancer but sorts by Agave's key, consistent with BAM
   ordering transactions upstream as its documentation says. The Jito validators also differ: one follows
   Agave, another sorted by total fee on its only day, on the same client version.
3. **Harmonic: Agave's key with the compute-unit (CU) limit capped.** None of my eight keys fits. Day A's
   orders fit Agave's key with the CU limit counted only up to a cap. Memo #2 fixed that hard-cap formula on
   chain before day B; on days B–D it matched all 108 full windows on four Harmonic validators. On panel P2
   it predicts plain Agave's order, so the test is P1's 48 / 48. Memo #3 then predicted that the limit above
   the cap still counts a little (a soft cap), which neither panel can see; an 11-02 follow-up agrees: a hard
   cap matches 8 of its 27 full windows, plain Agave 19. Fitted to all data: a cap of 1,500–1,963 CU with
   10–25% of the limit above it counted (a fit; other discounts untested). Exploratory throughout.
4. **Waiting versus arriving.** Queued probes sort everywhere. During the window, a richer probe sent
   4 ms later does not pass on Agave, Jito or Firedancer; through BAM and Harmonic it can pass one sent
   12–44 ms earlier. These horizons are rough: few trains, and the registered falling-fee control trains
   were never sent (a planning bug, REPORT §5); of 14 horizon predictions, 3 missed and 1 was inconclusive.
5. **Held out.** Outside Harmonic, days B–D gave 13 passed key predictions, 1 failed (total-fee Jito) and
   7 below the registered data minimum (15 usable panels), whose 76 full windows all matched: descriptive,
   not a pass.

Labels: *registered* = a test fixed before the campaign; *exploratory* = a pattern found in data and
checked later, not confirmed; *descriptive* = a count without a test (including the exact-order column).

Every finding is traced to windows, slots and signatures in [CLAIMS.md](CLAIMS.md); [REPORT.md](REPORT.md)
has the full results, dates, deviations and what went wrong.

### One fingerprint pair, checked on chain

Panel P1's probes A and B: A has R = 3,954 and C = 3,143, B has R = 3,325 and C = 2,643. Agave's R/(C+1)
puts A first (1.257633 against 1.257564); Firedancer's R/C puts B first (1.2580337 against 1.2580401).
This needs only `curl` and `python3`, no clone:

```sh
pos() {  # slot, signature of A, signature of B
  curl -s https://api.mainnet-beta.solana.com -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"getBlock","params":['"$1"',{"transactionDetails":"signatures","rewards":true,"maxSupportedTransactionVersion":1}]}' |
  python3 -c 'import json,sys; r=json.load(sys.stdin)["result"]; s=r["signatures"]; print("A at", s.index(sys.argv[1]), " B at", s.index(sys.argv[2]), " leader", [x["pubkey"] for x in r["rewards"] if x["rewardType"] == "Fee"][0])' "$2" "$3"
}
pos 462730056 53TwDCb9ij9eQFknD3BNttigrBnnjWfwzVie9LSXLivnaQ5ezfQpfQXdCsCFbKoEgwEkp89Tb9T3arPaQX22QC1y 45z3PjzHK5zXJiduQMXZffa2Gcx1W1JNZAjQgzCnm69wSn2j3tYHEsNwG36xstMYACnwbE4w7BCc4A9Lxdjypr7o
# A at 7  B at 8  leader 7QQGNm3p... (Agave)
pos 463836004 63TJRot72LXhFQdMY4woeGv6gUQ9RwUXcoAV14v4Lu2kmbYFTHGRBv6mJijBn4UrQzkAwZxkJGR5c3xCetyaf18q 4cfWX8BTFLQYcBXxn337Uv5c16PcRdf5Wkzm7bmpzwApxsLJTK3SaNZ6Vs2wCLB6MAwXV4apoipPQz2EmCZsSpWH
# A at 13  B at 12  leader DNVZMSqe... (Firedancer)
```

The leader is the block's fee-reward recipient. Each panel's six probes were sent about 0.2 s and 0.4 s
before the window was due (windows `A-1029-b0-0053` and `C-1031-b5-0019`), and in both blocks the probe that
landed first was sent after the other, so send order does not explain either. Send times come from my logs;
when each probe reached the leader is not observed. Any explorer shows each probe's compute-unit limit,
price and loaded-data limit; `verify` decodes them for every window.

![How a probe travels from my sender to a position in the block](figures/diagram.svg)

## How it works

- **Probe.** One legacy transaction shape: fee payer, never-funded "lock" account, three compute-budget
  instructions (CU limit L, CU price p, loaded-data limit D), and a 0-lamport transfer to the lock. Only
  L, p and D change, moving fee and scheduling cost in different directions.
- **Panels.** Six payers share a lock, forcing serial execution so block order reveals scheduler order.
  I send just before the leader window. Two fixed panels make every candidate-key pair disagree on at
  least two probe pairs. Controls use six identical probes for tie-breaking, or separate locks for no
  contention.
- **Trains.** 10–12 probes with equal limits, sent 4 ms or 12 ms apart during the window, with fees rising.
  First-in, first-out (FIFO) keeps send order; sorting allows overtaking.
- **Route.** Unstaked QUIC straight to the TPU address each leader advertises, every send time logged.
  For BAM and Harmonic that address is the block builder, so those results describe the validator *as
  reached through its advertised ingress*. BAM endpoints closed my unstaked connection in 21% of windows.
- **Schedule.** Calibration 10-27 to 10-28; days A–C (10-29 to 10-31) in six 4-hour blocks over all UTC
  hours: day A picks builders' keys and horizons, B and C test them; Agave, Jito and Firedancer face their
  source-code key throughout. Tier 2 adds a second validator per client on day C. Day D (11-01) topped up
  four shortfalls; 11-02 was the Harmonic follow-up.
- **Pre-registration.** [PREREG.md](PREREG.md) and [design/design.json](design/design.json) fix questions,
  keys, decision rules and quotas before campaign probes. On-chain hashes:
  memo #1 [`TywPFLUz…`](https://explorer.solana.com/tx/TywPFLUznyNThfq9hiKp34eikwW8ZHxs3xefwWfABCBsceRaSLJvnAPPk977XyTXSTJWGsMnW6i43cr2NGTwXxd)
  (commit `0bb3ee5`), memo #2 [`mbp3zEGq…`](https://explorer.solana.com/tx/mbp3zEGqTFnkJuLZkRndhWu4yFRkdxvwHJNMKZimE4QzbAeBMrT2RhE2N7ve8Z6F9BWkTV4ECBG1LoqwaCWJaNF)
  (commit `f3f1c52`, the day-A picks, before day B), memo #3 [`4zMGqri3…`](https://explorer.solana.com/tx/4zMGqri3f4ufA5sAFoZsr5VXQM6V4q1YxVpiqHQLgCFwjAtbVLkSTS1yWBK3vRCdXQmgMPP4TynR67CGf41E7HUf)
  (commit `f705581`, the Harmonic follow-up, before its first probe). Each memo names a commit and the SHA-256
  of the files it fixes; REPORT §1 shows how to check them with `git show` and `sha256sum`.

## Why this design

- **Known inputs, designed disagreements.** I know each probe's limits, fees, send time and target, and the
  shared lock makes block order readable. Ordinary fee ladders let keys agree; my panels separate concrete
  rules, including base-fee treatment and the 0.003% Agave/Firedancer difference.
- **Held-out checks.** Day-A picks are fixed on chain before day B and tested on days B–D. Day A chooses
  among eight keys without adjusting for that choice; the fixed-key held-out tests are the confirmatory ones.
- **Horizon.** Batching and stalled queues can look alike; the measurement avoids claiming a mechanism.

## The listing's considerations

| Consideration | How the design handles it |
|---|---|
| Leader schedule and leader types | Windows come from `getLeaderSchedule` per identity. Leader type = gossip client ID × advertised TPU, snapshotted around every window; registered tests drop windows where either changed. `verify` re-checks `getSlotLeaders` for all four slots. |
| Path from my backend to the executing node | One fixed route: unstaked QUIC to the advertised TPU, every send time logged (median 0.0025 ms from plan). Not RPC `sendTransaction`, which hides send time and target, retries and forwards to several leaders. For BAM and Harmonic the TPU is the builder, so results describe the validator as reached through it. |
| My own transactions interacting | Six payers per panel, contending only through the designed shared lock; K-free panels give each probe its own lock as the contrast. |
| Competition inside the block | Order is compared only among my probes within one block. Block load is recorded and the key checked within thirds of load (REPORT §3.1); other traffic is not controlled (item 6 below). |
| Send order | A fresh random send order and payer assignment per panel, so send order cannot imitate a fee key; FIFO is a candidate key. Trains test arrival against fee directly, without the falling-fee control (REPORT §5). |
| Noise versus rule | Window-level exact tests against every rival (within-block pairs are dependent), Holm across the eight main validators, a randomisation null, identical-probe panels, held-out days; "no rule detected" is an allowed outcome. |

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
   from each other (no two of mine shared one).
9. Bundles and tips (out of scope). Block-wide context may contain bundles.
10. Order among probes that did not land. Inclusion is reported separately.

## Reproduce

```sh
docker compose up --build --exit-code-from analyze       # offline: recompute every number, diff with data/derived
docker compose run --rm verify                           # online: re-fetch a sample of claimed blocks (VERIFY_ALL=1 for all)
docker compose run --rm test                             # unit tests
docker compose run --rm dryrun                           # plan the next 15 min of real leader windows, send nothing
```

If any recomputed number differs, `analyze` prints MISMATCH and exits 1, and the first command exits 1 too;
`--build` rebuilds the image from your checkout. `verify` checks signatures at recorded indices, payers, fees,
decoded limits, the block's fee-reward recipient, and `getSlotLeaders` for all four window slots (one
validator, `PRGNnb8D`, sends its fees to another account; the schedule names it). A block the RPC cannot serve
fails the check; a skipped slot does not. A full run on 11-03 found 0 problems in all 1,252 windows
that sent probes (8 more logged windows sent none) ([data/verify/](data/verify/verify-all-2026-11-03.json)). `ITB_RPC_URL` picks the RPC. Send times, intended
targets and client labels depend on logs and snapshots.

Live sending needs `--live`, `ITB_LIVE=1`, `--max-spend-sol` and the key directory (mounted read-only);
funding, memo and sweep need `ITB_LIVE=1` too. The sweep sends only to the address whose SHA-256 is
`SWEEP_TARGET_SHA256` in [itb/ops.py](itb/ops.py) (my funding wallet); change it to sweep elsewhere. Each
send reserves its worst-case fee; the code caps total spend at 0.05 SOL and releases reservations only after
checking the loaded key's wallet balances and the chain's landed fees.

## Listing requirements → where

| Requirement | Where |
|---|---|
| ≥6 validators, ≥3 clients, own mainnet transactions after Alpenglow | [design/candidates.json](design/candidates.json), `data/raw/*/probes.jsonl.gz` (all slots ≥ 459,653,000, checked in code) |
| Ordering rule, how strictly, or no rule, per validator | Findings above, [REPORT.md](REPORT.md) §3, [data/derived/tables.md](data/derived/tables.md) |
| All raw data: signatures, slots, blocks | `data/raw/<run>/` (probes, outcomes, blocks, windows, snapshots, SHA256SUMS) |
| One-command reproduction | `docker compose up --build --exit-code-from analyze`; CI runs it on amd64 and arm64 |
| Dry run by default, live behind a flag, spend cap in code | `itb run` (dry unless `--live` + `ITB_LIVE=1`), [itb/ledger.py](itb/ledger.py) |
| Keys via env or volume, never in the repo | `ITB_KEYS_DIR` volume, read-only; pre-commit check in [.githooks/](.githooks/) |
| Why this design / each consideration / what it does NOT separate | the three sections above |
| Date of every measurement, what went wrong | [REPORT.md](REPORT.md) §4–§6, `run.json` in every run folder |

## Cost

0.048173 SOL in fees out of the 0.05 SOL cap, everything included (probes 0.047973, 40 operations
transactions 0.0002); `docker compose up` checks the total against the on-chain fees and the wallet
balances ([REPORT.md](REPORT.md) §6). 0.011237 SOL went back to the funding wallet; 0.00065 SOL stays in the
main wallet (§4).

## Repo map

`itb/` sender, collector and analysis (`itb --help`); `design/` panels, keys, quotas, predictions;
`data/raw/` every probe signed and every block it landed in; `data/derived/` and `figures/` recomputed.
