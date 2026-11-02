# Report

Full write-up behind the README. Numbers in this file come from `data/derived/results.json`; every claim
is traced to windows, slots and signatures in `CLAIMS.md`.

## 1. Method in one page

**Probe.** One legacy transaction shape: 1 signature, fee payer + one never-funded "lock" account,
`SetComputeUnitLimit(L)`, `SetComputeUnitPrice(p)`, `SetLoadedAccountsDataSizeLimit(D)`, and a 0-lamport
transfer to the lock. It always uses 600 CU and loads 235 bytes, so its executed cost is 1,935 and its fee
is 5,000 + ⌈L·p/10⁶⌉ lamports; both were checked on every landed probe. Only L, p and D change, and they
move the probe's priority under each candidate key in different directions.

**Panels (Study K).** Six probes from six payers, all writing the same lock, sent together 200–600 ms
before the leader's window. They are already waiting when the window opens, and the shared lock forces the
scheduler to run them one by one, so their order in the block is the scheduler's order. Two fixed panels
put every pair of candidate keys in disagreement on at least two probe pairs. The sharpest pairs separate
Agave's integer priority ⌊R·10⁶/(C+1)⌋ from Firedancer's exact R/C (a 0.003% difference): panel P1 does it
through the compute-unit limit, panel P2 through the loaded-data limit.

**Trains (Study M).** 10–12 probes with equal L and D, sent one by one 4 ms or 12 ms apart inside the
window, with the fee rising (80%) or falling (20%) along the send order. If the later, richer probe lands
first, it overtook; the largest send gap at which that still happens in at least half of pairs is the
overtaking horizon.

**Route.** Unstaked QUIC directly to the TPU address each leader advertises in gossip, one transaction per
stream, with a fresh connection per leader opened 3.5 s before its window. For BAM and Harmonic validators
that address is the builder endpoint, so the result reads "this validator as reached through its
advertised ingress".

**Timing.** The slot clock uses the RPC node's `firstShredReceived` timestamps
(`slotsUpdatesSubscribe`), extrapolated with a median gap per position in the 4-slot window (a new
leader's first slot shows up ~280 ms after the previous slot, the next one ~146 ms later, then 200, 200).
Send times are corrected by half the QUIC round trip to the target.

**Randomisation.** Per window, from OS randomness and logged: panel, send order, payer per probe, send
offset, arm (K-main / K-null / K-free) or train spacing and direction. Analysis randomness uses a fixed
seed so `docker compose up` is exact.

**How much data is enough.** `itb sim` runs the whole decision procedure on simulated schedulers
([design/power.json](design/power.json), 100 repetitions per cell, 85% of probes landing). With 22
informative windows per validator-day, the true key is called in at least 99% of runs when 10% of windows
are scrambled at random, and in 73% when 25% are; with 28 windows, in at least 93% even at 25%. A random or
FIFO scheduler was called a key rule in at most 1% of runs. The day quotas aim at 28 informative windows on
day A and 22 on days B and C. For trains, simulated rounds of 20 ms and 50 ms give horizons of about 8 ms
and 24 ms (roughly half the round), and FIFO gives 0, which is why I report the horizon and not a round length.

## 2. Design decisions

- **My own probes over mining other people's transactions.** Only my probes have known L, p, D, send
  time, send order and target, and only a shared lock makes their order the scheduler's order.
- **Fingerprint pairs over a single fee ranking.** Most candidate keys agree on ordinary fee ladders;
  only designed pairs make them disagree, including the +1/floor difference between Agave and Firedancer.
- **Direct QUIC over RPC `sendTransaction`.** RPC hides the send time and the target, retries, and
  forwards to two leaders.
- **Window-level statistics over pair counts.** Pairs inside one block are not independent; the window is
  the unit, and a window counts once per key pair.
- **Identification and strictness reported separately.** A first rule that required every rival to lose in
  more than 75% of windows failed in simulation as soon as 10% of windows were scrambled; the rule now asks
  which key beats every rival in a majority of windows, and reports how strictly it holds next to it.
- **Overtaking horizon over a round length.** A layered order can come from rounds or from a stalled
  queue; the horizon measures how strictly the key holds in time without claiming a mechanism.
- **Three collection days.** Day A picks keys for undocumented builders, days B and C test those picks on
  data the picks never saw; documented clients are tested against their source code from day A.
- **Python only.** One language for sending, collecting and analysis; wheels exist for amd64 and arm64.

## 3. Results

Dates are UTC. "Full window" = a K-main panel whose six probes all landed in one block of the target's window.
Windows where gossip did not show the target on both sides of the send within 60 s are left out of client
claims (7 full windows on days A–C). Tables: [data/derived/tables.md](data/derived/tables.md).

### 3.1 Which key orders queued probes

| Client | Validators | Key | Full windows in exact key order, days A–C | Held out (days B–D) |
|---|---|---|---|---|
| Agave | `7QQGNm3p`, `5Us18hLZ` | `agave_int` | 89 / 89 | 2 passed, 1 too few panels (source-code key) |
| JitoLabs | `E1r4Psq8` | `agave_int` | 47 / 47 | 2 passed, 1 too few panels (source-code key) |
| JitoLabs | `C8Bey3LK` | `total_fee` | 14 / 15 (day C only) | failed: predicted `agave_int` from source |
| AgaveBam | `Fc6NNdS2`, `5EhGYUyQ` | `agave_int` | 58 / 58 | 2 passed, 2 too few panels |
| FireBAM | `SSmBEooM`, `PRGNnb8D` | `agave_int` | 61 / 61 | 3 passed, 1 too few panels |
| Rakurai | `ana2y2Yv`, `E3mDbFMr` | `agave_int` | 100 / 100 | 2 passed, 1 too few panels |
| Firedancer | `JD549Hsb`, `DNVZMSqe` | `fd_exact` | 71 / 77 | 2 passed, 1 too few panels (source-code key) |
| HarmonicAgave | `EkvdKhUL`, `BtsmiEEv` | none of the eight | no single key fits | 2 failed, 1 too few panels |
| HarmonicFiredancer | `87CcUxpy`, `CQdLgwkm` | none of the eight | no single key fits | 3 failed, 1 too few panels |

What the table says:

- **Agave's integer key, exactly, on five client types.** 355 of 355 full windows on Agave, Jito
  (`E1r4Psq8`), AgaveBam, FireBAM and Rakurai came out in the exact `agave_int` order, including every
  fingerprint pair (two in P1, three in P2), where Firedancer's exact ratio predicts the opposite.
- **Firedancer uses its own exact ratio.** All five fingerprint pairs went Firedancer's way in every full
  Firedancer window. The 6 of 77 windows that broke the full order were swaps among the cheapest probes at
  the end of the block order (for example `BAECFD` instead of `BAECDF`), not fingerprint flips.
- **The BAM node decides, not the client.** FireBAM runs Firedancer, yet both FireBAM validators sort by
  Agave's key: their transactions come pre-ordered from the BAM node, as BAM's documentation says.
- **Jito is not one rule.** `E1r4Psq8` follows Agave's key; `C8Bey3LK` sorts by total fee (5,000 + priority
  fee): 14 of 15 full windows in exact `total_fee` order (and both of its calibration windows), against 0
  for `agave_int`.
- **Harmonic fits none of the eight registered keys.** Day A's picks (`agave_int` for HarmonicAgave,
  `pf_per_cost` for HarmonicFiredancer) failed on days B and C. Yet the Harmonic orders are not noise:
  on days B and C every full window repeated one order per panel, whatever the send order (3.2).

### 3.2 Harmonic: an explanation that fits and replicates

In the first block of day A, all seven full Harmonic panels fit one formula outside my list: Agave's integer priority, with
the compute-unit limit counted toward cost only up to a cap X. Any X from 1,660 to 4,098 gives the observed
orders. I wrote this down with its predicted orders in `design/predictions-dayB.json` before day B, hashed
in memo #2, as exploratory. After the memo, on days B and C, 90 of 90 full windows on all four Harmonic
validators matched it exactly (day B 37 / 37, day C 53 / 53), including 17 of 17 on `BtsmiEEv` and
`CQdLgwkm`, which had no windows on day A. Day A itself, where the formula was found, is 49 of 51 and is
not a test of it. The formula fits and replicates; it is not a confirmed rule, because it was formed from
the data and the fixed panels cannot pin X down.

CAPSWEEP_PLACEHOLDER

### 3.3 Held-out test (registered)

A validator-day counts only with at least 15 evaluable K-main panels and 5 informative windows against
every rival (PREREG); below that it is "insufficient data", whatever the test says.

| Day | Keys: passed / failed / too few panels | Horizons inside the day's interval | Misses |
|---|---|---|---|
| B (10-30) | 5 / 2 / 1 | 4 of 5 | keys: both Harmonic picks; too few: `Fc6NNdS2` (9); horizon: `SSmBEooM` predicted 44 ms, day B 24 ms |
| C (10-31) | 5 / 3 / 8 | 5 of 6 | keys: `EkvdKhUL`, `87CcUxpy`, `C8Bey3LK`; too few: seven Tier-2 validators and `E1r4Psq8` (6–13); horizon: `87CcUxpy` predicted 20 ms, day C 24 ms |
| D (11-01) | 3 / 1 / 0 | 1 of 3 | keys: `87CcUxpy`; horizons: `87CcUxpy` and `SSmBEooM` |

Outside Harmonic: 13 passed, 1 failed, 7 too few panels. The failure, `C8Bey3LK`, was a Tier-2 Jito
validator predicted from Jito's source code; it is the total-fee result above. The seven short
validator-days had 76 full windows between them, all in the predicted order: consistent, but not a test.

### 3.4 How strictly in time

Overtaking horizon (largest send gap at which a later, richer probe still lands first in at least half of
pairs), with 95% intervals:

| Client | Validator | Day A | Day B | Day C |
|---|---|---|---|---|
| Agave | `7QQGNm3p` | 0 [0, 0] | — | — |
| JitoLabs | `E1r4Psq8` | 0 [0, 0] | — | — |
| Firedancer | `JD549Hsb` | 0 [0, 0] | 0 [0, 0] | 0 [0, 0] |
| Rakurai | `ana2y2Yv` | 0 [0, 0] | 0 [0, 0] | 44 [0, 44] |
| AgaveBam | `Fc6NNdS2` | 16 [12, 28] | too few trains | 16 [12, 28] |
| FireBAM | `SSmBEooM` | 44 [28, 44] | 24 [24, 24] | 44 [44, 44] |
| HarmonicAgave | `EkvdKhUL` | 16 [16, 20] | 12 [8, 20] | 16 [16, 24] |
| HarmonicFiredancer | `87CcUxpy` | 20 [16, 24] | 16 [16, 24] | 24 [24, 24] |

Two regimes. Probes already waiting when the window opens are sorted by the key on every client. Probes
arriving during the window are served in arrival order by Agave, Jito, Firedancer and (on two days of
three) Rakurai: a richer probe sent 4 ms later does not pass a cheaper one. Through a BAM node or Harmonic
endpoint a richer probe can still pass a cheaper one sent 12–44 ms earlier, which fits short batching
before ordering. The FireBAM horizon moved between days (44, 24, 44 ms) on one or two evaluable trains per
day, so I do not read it more precisely than "tens of milliseconds". This Firedancer validator's horizon
is 0; it is one operator, and other Firedancer operators may pace differently.

DAYD_PLACEHOLDER

## 4. What went wrong

- **Memo program address.** The Memo v2 address I had in my notes does not exist on mainnet
  (transactions to it fail with `ProgramAccountNotFound`); the real one is
  `MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr`. Caught by a free `simulateTransaction` before any
  spend.
- **`meta.costUnits` is not the scheduling cost.** It is the cost after execution (consumed CU, actual
  loaded bytes); scheduling priority uses the requested limits. I check the executed cost (1,935) per probe
  and compute priorities from the requested limits.
- **Relayer-port validators.** Two planned Jito validators and one Rakurai validator advertise TPU port
  11228 (the old Jito relayer); I replaced them with own-IP alternates before the pilot.
- **Evicted connections.** In the smoke test, one Jito train and one BAM panel were never acknowledged:
  the validator dropped the idle unstaked connection opened 6 s early. I now connect 3.5 s before the
  window and reconnect if the connection died. Those probes never landed and cost nothing.
- **Decision rule too strict.** See section 2; changed before the pre-registration, from simulation only.
- **A stranger's deposit hid 9,374 lamports of fees.** During pilot-1027a an unknown address sent 9,374
  lamports to one of my fee payers ([`2sLiRbYW…`](https://explorer.solana.com/tx/2sLiRbYWEbhjqXfq4KVcNqoxneckPAVqJBXMFYq99EPreqMabLvfeJRBPBdAZkKNQtzBsddWRstuvqiqzC54hQ85)).
  Spend is measured from wallet balances, and the deposit arrived mid-run while fee reservations were open,
  so the ledger counted 9,374 lamports less than my probes actually paid. Summing block fees per run against
  balances caught it the next day. I logged the deposit as an inflow, which raised the counted spend to the
  true figure; the final reconciliation lists every incoming transfer to all twelve wallets.

- **BAM nodes drop unstaked connections.** Through BAM endpoints, part of the windows were never
  acknowledged: the endpoint closed the connection with code 1 ("dropped") as the probes arrived (day B 16 of
  56 BAM windows, day C 13 of 91). Those probes never landed and cost nothing, but `Fc6NNdS2` lost 13 of 30
  windows on day B and is "insufficient data" for that day.
- **Tier-2 quotas below the data minimum.** I sized the day-C Tier-2 quotas (16–24 windows) for 12
  informative windows, under the 15 evaluable panels PREREG requires for a call. Seven of the eight Tier-2
  validators came out "insufficient data" on their only held-out day. Outside Harmonic their full windows
  all agree with the predicted key, but they replicate nothing in the registered sense.
- **Five windows could not connect.** `C-1031-b0-0045` to `C-1031-b0-0048` and `D-1101-b4-0000` could not
  open a QUIC connection, so nothing was sent or spent; 5 of more than 1,000 campaign windows.
- **Stale slot clock.** Five windows (three on day A, two on day B) were skipped because the slot stream had
  fallen behind; the sender does not time a send from a stale clock.
- **Snapshots that do not bracket a window.** Seven full windows on days A–C had no gossip snapshot of the
  target within 60 s on one side of the send, so they are left out of client claims (the rule in
  PREREG.md). Counting them would add 3 to Agave's key and 4 to the Harmonic formula, all in agreement.

## 5. Deviations from the pre-registration

- **Day D eligibility count.** PREREG lets day D run for a Tier-1 validator that is short of its target
  "because of low supply or transitions", if the budget allows. I counted fully landed K-main windows
  against the 22-window target of days B and C (stricter than counting per contrast) and fixed that reading
  on 10-31 before day C ended. Six validators were short, all with fewer windows planned than their quota
  (low supply); the remaining budget covered four, so day D took the four largest shortfalls
  (`Fc6NNdS2`, `E1r4Psq8`, `SSmBEooM`, `87CcUxpy`) with their day-C quotas
  ([design/campaign-dayD.json](design/campaign-dayD.json), committed before its first probe).
- **Harmonic cap sweep (addition).** Not in PREREG. Designed after days A–C to measure the cap in the
  exploratory Harmonic formula, locked on chain by memo #3 before its first probe
  ([design/capsweep.json](design/capsweep.json)), and reported apart: it changes no registered call.
- **Held-out data gate (correction, 11-02).** My first held-out tables counted validator-days with fewer
  than 15 evaluable panels as passes (`holdout()` skipped the registered minimum), and the README said "17
  of 18 held". The code now applies the gate; the tables above are the corrected ones.
- **Exact-order counts (addition).** The "full windows in exact key order" columns are descriptive, added
  after the campaign as a plain-language check; the calls rest on the registered tests.

## 6. Cost

COST_PLACEHOLDER
