# Pre-registration

Written before the first campaign probe. The commit that adds this file, its SHA-256 and the SHA-256 of
`design/design.json` are written on chain in a memo from the study wallet (memo #1). Nothing in this file
or in `design/` changes after that commit; any deviation is listed in REPORT.md with its reason.

## Questions

For each validator, while it is leader on Solana mainnet (Alpenglow, slots ≥ 459,653,000):

1. **Key.** Which sort key orders transactions that are already waiting when its window starts?
   Candidates: `agave_int` ⌊(pf+2500)·10⁶/(cost+1)⌋, `fd_exact` (pf+2500)/cost, `pf_per_cost` pf/cost,
   `fee_per_cost` (pf+5000)/cost, `cu_price` p, `fee_per_cu` (pf+2500)/L, `total_fee` 5000+pf,
   `cheapest` −cost, plus send order (FIFO) and no rule. pf = ⌈L·p/10⁶⌉; cost uses the requested limits.
2. **Clock.** For transactions arriving during the window, how far apart in send time can a later,
   higher-fee transaction still be placed ahead of an earlier one (the overtaking horizon)?
3. **Inclusion.** Does the fee change whether a probe lands in the target window at all?

## Probes

One shape everywhere: legacy transaction, 1 signature, fee payer + one never-funded "lock" account,
`SetComputeUnitLimit(L)`, `SetComputeUnitPrice(p)`, `SetLoadedAccountsDataSizeLimit(D)` and a
0-lamport transfer payer → lock (600 CU used, 235 bytes loaded). Only L, p and D change. Sent unstaked
over QUIC directly to the leader's advertised TPU (for BAM and Harmonic validators that address is the
builder endpoint), one transaction per stream, from 12 fee payers derived from one wallet.

## Study K — queued panels

Six probes from distinct payers, sent together 200–600 ms (uniform) before the estimated window start.
Two fixed panels (`design/panels.json`, `design/prediction_table.md`) were chosen so that every pair of
candidate keys orders at least two probe pairs in opposite ways ("decisive pairs"); P1 separates
`agave_int` from `fd_exact` through L, P2 through D. Per window, drawn from OS randomness and logged:
panel, send order, payer per probe, offset, and arm:

- **K-main (75%)**: one shared lock, so the six must be serialised.
- **K-null (10%)**: six identical probes; measures tie-breaking (send order vs other).
- **K-free (15%)**: each probe its own lock (no contention); compared with K-main.

## Study M — trains

Probes with equal L and D, sent one by one: 12 at 4 ms or 10 at 12 ms, starting 30–70 ms after the
estimated start of the window's second slot. 80% of trains raise the fee along the send order (every key
predicts reverse order, FIFO predicts send order), 20% lower it (every model predicts send order; this
measures scrambling by jitter).

## Outcomes

Every signed probe is coded once: `target_block`, `later_window_same_leader`, `other_leader`,
`expired`, `send_failed`. Order is compared only inside one block, between our own probes.

## Analysis (unit = window or train, never the probe pair)

**Window outcome.** For a K-main window and a key pair (k, k′), the window is informative if at least one
decisive pair for (k, k′) landed in the same target block; k wins the window if it predicts the majority
of those pairs correctly (an exact tie is not informative).

**Identification.** Key k is identified for a validator if, against every rival k′, the hypothesis
"k wins at most half of the informative windows" is rejected by an exact one-sided binomial test
(intersection–union: the call's p-value is the largest of the seven). Across the Tier-1 validators the
calls are corrected with Holm at α = 0.05; Tier-2 calls use α = 0.05 and are labelled replication.

**Strictness.** Reported for every validator: each rival's win rate with a 95% Clopper–Pearson interval.
An identified key is "strict" if the weakest rival's lower bound is ≥ 0.75, otherwise "loose".

**No rule.** If no key is identified, a randomisation test (landing order permuted inside each block,
2,000 draws, fixed seed) decides between "order, no single key" (p ≤ 0.05 for the best key's agreement)
and "no rule detected".

**Send order.** Share of same-block pairs in send order, per arm. K-null gives the tie-break.

**Horizon (primary for Study M).** For increasing trains with at least 8 (of 12) or 7 (of 10) probes in
one target block: the share of pairs in which the later, higher-fee probe came first, by send gap; the
horizon is the largest gap where that share is ≥ ½; 95% interval by bootstrap over trains. No round
length is claimed. Documented builder periods (BAM 20 ms, Harmonic 50 ms) are compared descriptively.

**Inclusion.** Landing rate per probe and outcome category, by leader type. In trains (equal L and D,
fee rising by 140 lamports per step) the landing rate is reported by fee rank; descriptive only.

**Sensitivity (secondary, descriptive).** The best key's agreement is repeated within thirds of block load
(transactions per block, cut points per day) and compared between ingress kinds.

Windows whose gossip snapshots either side of the send (≤ 60 s) show a change of client, ingress or TPU
address are coded "transition" and excluded from per-client calls (counted in REPORT).

## Days and hold-out

- **Day A (2026-10-29, UTC).** Documented clients (Agave, JitoLabs → `agave_int`; Firedancer →
  `fd_exact`) are tested against their source-code key. For the others, day A picks the key and the
  horizon. These picks go into `design/predictions-dayB.json`, whose SHA-256 is written on chain in
  memo #2 before day B starts.
- **Day B (2026-10-30).** Held-out test: each validator's predicted key must pass the identification
  test above (Holm across Tier 1) using day-B windows only; where a horizon was predicted, it must fall
  inside the day-B 95% interval.
- **Day C (2026-10-31).** Second held-out day with the same predictions, reported separately.
- **Day D (conditional).** Run only if, after day C, a Tier-1 validator is short of its informative-window
  target because of low supply or transitions, and the remaining fee budget covers it. Same predictions;
  reported separately.

Each day runs as six 4-hour blocks so that windows cover all UTC hours.

## Validators and stopping

Full identities are in `design/candidates.json`; per-day quotas in `design/campaign.json`. Tier 1 is one
validator per client and forms the confirmatory set (Holm across these eight); Tier 2 is replication.

| Tier | Validator | Client (gossip) | Ingress | Day A K/M | Day B K/M | Day C K/M |
|---|---|---|---|---|---|---|
| 1 | `7QQGNm3p` | Agave | own | 45/4 | 36/0 | 36/0 |
| 1 | `Fc6NNdS2` | AgaveBam | BAM node | 38/8 | 30/4 | 30/4 |
| 1 | `SSmBEooM` | FireBAM | BAM node | 38/4 | 30/2 | 30/2 |
| 1 | `JD549Hsb` | Firedancer | own | 38/8 | 30/4 | 30/4 |
| 1 | `EkvdKhUL` | HarmonicAgave | Harmonic | 38/8 | 30/4 | 30/4 |
| 1 | `87CcUxpy` | HarmonicFiredancer | Harmonic | 38/8 | 30/4 | 30/4 |
| 1 | `E1r4Psq8` | JitoLabs | own | 38/4 | 30/0 | 30/0 |
| 1 | `ana2y2Yv` | Rakurai | own | 56/8 | 44/4 | 44/4 |
| 2 | `5Us18hLZ` | Agave | own | – | – | 16/0 |
| 2 | `5EhGYUyQ` | AgaveBam | BAM node | – | – | 24/0 |
| 2 | `PRGNnb8D` | FireBAM | BAM node | – | – | 16/0 |
| 2 | `DNVZMSqe` | Firedancer | own | – | – | 16/0 |
| 2 | `BtsmiEEv` | HarmonicAgave | Harmonic | – | – | 16/0 |
| 2 | `CQdLgwkm` | HarmonicFiredancer | Harmonic | – | – | 16/0 |
| 2 | `C8Bey3LK` | JitoLabs | own | – | – | 24/0 |
| 2 | `E3mDbFMr` | Rakurai | own | – | – | 16/0 |

K = K windows (panels, all arms), M = trains. A day's quota is split evenly over its six blocks. Quotas come from
the pilot: K windows = ⌈target / (0.75 · r)⌉, where r is the share of a validator's pilot K-main windows that were
informative (floor 0.67) and the target is 28 informative K-main windows on day A and 22 on days B and C (Tier 2:
12 on day C). Expected fees: day A 15.2M, day B 10.8M, day C 15.8M lamports;
3.88M were spent on the smoke test and pilots, and the rest of the 50M cap is the reserve (day D, overruns).

Changes made at the pilot, by the pilot rules: both FireBAM candidates landed under 70% of their probes (their
BAM nodes closed our connection with code 1 "dropped", an evicted unstaked connection), so FireBAM's Tier-1
validator is SSmBEooM, the best of four validators tested behind other BAM nodes; the Rakurai replication
validator had no leader slots in the next epoch and was replaced. Trains go only to endpoints that accepted
pilot trains (plus a few exploratory ones for SSmBEooM).

Window quotas per validator and day are fixed in advance (table above); no window is added or dropped
because of an order outcome, and day D is decided on informative-window counts only. A validator is
reported as "insufficient data" for a day if it has fewer than 15 evaluable K-main panels (a block
holding at least four of the six probes) or fewer than 5 informative windows against some rival. Total fees over the whole study are capped in code at
0.05 SOL; if the cap would be reached, Tier-2 windows are dropped first, then the K-free arm, then trains.

## What this design does not separate

Arrival time at the leader (we log send times only); a validator's own scheduler vs an upstream builder
with the same comparator; keys outside the candidate list that rank every panel identically; private
operator settings; staked or SWQoS paths; behaviour at high fees or in full blocks; execution order of
non-conflicting transactions; family-wide generalisation from two validators; validators behind one
shared builder endpoint (reported as one group); bundles and tips.
