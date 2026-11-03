# Report

I found distinct Agave and Firedancer ordering rules, a total-fee Jito validator, and an exploratory
Harmonic soft cap. Queued probes sort; overtaking during a leader window varies by route and day.
Numbers come from `data/derived/results.json`; `CLAIMS.md` traces claims to windows, slots and signatures.

## 1. Method in one page

All measurement dates are UTC in 2026: smoke test and pilots, 10-27 to 10-28; day A, 10-29; day B,
10-30; day C, 10-31; day D, 11-01; Harmonic follow-up, 11-02. Tier 1 is the eight main validators;
Tier 2 adds a second per client on day C.

**Probe.** I use one legacy transaction shape: 1 signature, fee payer + one never-funded "lock" account,
`SetComputeUnitLimit(L)`, `SetComputeUnitPrice(p)`, `SetLoadedAccountsDataSizeLimit(D)`, and a 0-lamport
transfer to the lock. It always uses 600 compute units (CU) and loads 235 bytes. Its executed cost is
1,935; its fee is 5,000 + ⌈L·p/10⁶⌉ lamports. I checked both on every landed probe. Only L, p and D
change, moving priority under each candidate key in different directions.

**Panels (Study K).** A panel is six probes from six payers sharing one lock, sent together 200–600 ms
before the leader's 4-slot window. They wait in the queue; the lock forces serial execution, making block
order the scheduler's order. A *key* is a sorting rule. Two fixed panels make every candidate-key pair
disagree on at least two probe pairs. Agave uses integer priority ⌊R·10⁶/(C+1)⌋; Firedancer uses exact R/C
(R = priority fee + 2,500; C = scheduling cost). A *fingerprint pair* is two probes these keys rank
oppositely, differing by as little as 0.003%. P1 exposes the difference through the CU limit, P2 through
the loaded-data limit. Controls use identical probes (K-null) or separate locks (K-free).

**Trains (Study M).** 10–12 probes with equal L and D, sent one by one 4 ms or 12 ms apart inside the
window, with the fee rising (80%) or falling (20%) along the send order. If the later, richer probe lands
first, it overtook; the largest send gap at which that still happens in at least half of pairs is the
overtaking horizon.

**Route.** I send unstaked QUIC directly to each leader's advertised TPU address, one transaction per
stream, opening a fresh connection 3.5 s before its window. BAM and Harmonic advertise builder endpoints;
the result describes each validator through that ingress.

**Timing.** The slot clock uses the RPC node's `firstShredReceived` timestamps
(`slotsUpdatesSubscribe`), extrapolated with a median gap per position in the 4-slot window (a new
leader's first slot shows up ~280 ms after the previous slot, the next one ~146 ms later, then 200, 200).
Send times are corrected by half the QUIC round trip to the target.

**Randomisation.** I log OS-random choices per window: panel, send order, payer, offset, arm
(K-main / K-null / K-free), or train spacing and direction. Analysis uses a fixed seed for exact
reproduction with `docker compose up`.

**Power.** `itb sim` runs the decision procedure on simulated schedulers ([design/power.json](design/power.json),
100 repetitions per cell, 85% of probes landing). With 22 informative windows per validator-day (the day B
and C target; day A aims at 28), the true key is called in at least 99% of runs when 10% of windows are
scrambled, 73% when 25% are; a random or first-in, first-out (FIFO) scheduler is called a key rule in at
most 1%. Simulated rounds of 20 and 50 ms give horizons of about 8 and 24 ms and FIFO gives 0, so I report
the horizon, not a round length.

## 2. Design decisions

The [README](README.md#why-this-design) explains the probe and route choices. For analysis:

- **Independent unit.** I count each window once per key pair; within-block pairs are dependent.
- **Identification and strictness.** Before pre-registration, I replaced a rule requiring every rival to
  lose in more than 75% of windows: it failed in simulation with 10% scrambled windows. The registered
  rule asks which key beats every rival in a majority of windows (exact binomial tests, Holm across the
  eight main validators). I report strictness separately.
- **Held-out checks.** Day A picks undocumented builders' keys; days B–D test those picks. Documented
  clients are tested against their source-code key from day A on.
- **Horizon.** Rounds and stalled queues can produce similar orders; I measure timing without claiming
  either mechanism.
- **Python only.** Sending, collection and analysis share one language; wheels exist for amd64 and arm64.

## 3. Results

A *full window* is a K-main panel whose six probes landed in one block of the target's window.
I exclude windows without gossip snapshots of the target within 60 s on both sides of the send
(7 full windows on days A–C). *Registered* means a test fixed before the campaign; *exploratory* means
found in data and checked later, not confirmed; *descriptive* means a count without a test. Exact-order
counts are descriptive. Tables: [data/derived/tables.md](data/derived/tables.md).

### 3.1 Which key orders queued probes

| Client | Validators | Key | Full windows in exact key order, days A–D | Held out (days B–D) |
|---|---|---|---|---|
| Agave | `7QQGNm3p`, `5Us18hLZ` | `agave_int` | 89 / 89 | 2 passed, 1 too few panels (source-code key) |
| JitoLabs | `E1r4Psq8` | `agave_int` | 69 / 69 | 2 passed, 1 too few panels (source-code key) |
| JitoLabs | `C8Bey3LK` | `total_fee` | 14 / 15 (day C only) | failed: predicted `agave_int` from source |
| AgaveBam | `Fc6NNdS2`, `5EhGYUyQ` | `agave_int` | 75 / 75 | 2 passed, 2 too few panels |
| FireBAM | `SSmBEooM`, `PRGNnb8D` | `agave_int` | 80 / 80 | 3 passed, 1 too few panels |
| Rakurai | `ana2y2Yv`, `E3mDbFMr` | `agave_int` | 100 / 100 | 2 passed, 1 too few panels |
| Firedancer | `JD549Hsb`, `DNVZMSqe` | `fd_exact` | 71 / 77 | 2 passed, 1 too few panels (source-code key) |
| HarmonicAgave | `EkvdKhUL`, `BtsmiEEv` | none of the eight | no single key fits | 2 failed, 1 too few panels |
| HarmonicFiredancer | `87CcUxpy`, `CQdLgwkm` | none of the eight | no single key fits | 3 failed, 1 too few panels |

- **Agave's integer key, exactly, on five client types.** 413 of 413 full windows on Agave, Jito
  (`E1r4Psq8`), AgaveBam, FireBAM and Rakurai came out in exact `agave_int` order, including every
  fingerprint pair (two in P1, three in P2), where Firedancer's exact ratio predicts the opposite.
- **Firedancer uses its own exact ratio.** All five fingerprint pairs went Firedancer's way in every full
  Firedancer window. The 6 of 77 full-order misses swapped the cheapest probes at the end
  (for example `BAECFD` instead of `BAECDF`); no fingerprint pair flipped.
- **The BAM node decides, not the client.** FireBAM runs Firedancer, yet both FireBAM validators sort by
  Agave's key: their transactions come pre-ordered from the BAM node, as BAM's documentation says.
- **Jito is not one rule.** `E1r4Psq8` follows Agave's key; `C8Bey3LK` sorts by total fee (5,000 + priority
  fee): 14 of 15 full windows in exact `total_fee` order (and both of its calibration windows), against 0
  for `agave_int`.
- **Harmonic fits none of the eight registered keys.** Day A's picks (`agave_int` for HarmonicAgave,
  `pf_per_cost` for HarmonicFiredancer) failed on days B–D. Yet the Harmonic orders are not noise:
  on days B–D every full window repeated one order per panel, whatever the send order (3.2).
- **Ties (K-null, descriptive).** With six identical probes, Firedancer put the later-sent probe first in
  192 of 195 same-block pairs (both validators, days A–C). No other client has a tie rule this clear: the
  share of pairs in send order runs from 0.25 (FireBAM) to 0.72 (Jito)
  ([tables](data/derived/tables.md), "Send order vs block order").
- **Block load does not change the key (pre-registered sensitivity).** Within thirds of block load per
  day, the best key's pairwise agreement stays at 1.00 on Agave, Jito, AgaveBam, FireBAM and Rakurai,
  0.99–1.00 on Firedancer and 0.90–0.94 on Harmonic in light, middle and heavy blocks alike
  ([tables](data/derived/tables.md), "by block load").

### 3.2 Harmonic: an explanation that fits and holds on later days

In day A's first block, all seven full Harmonic panels fit Agave's integer priority with the CU limit
counted toward cost only up to a cap X. Any X from 1,660 to 4,098 gives the observed orders. I fixed the
formula and predicted orders in `design/predictions-dayB.json`, hashed in memo #2 before day B, as
exploratory. On days B–D, 108 / 108 full windows across all four validators matched (B 37 / 37, C 53 / 53,
D 18 / 18), including 17 / 17 on `BtsmiEEv` and `CQdLgwkm`, which had no day-A windows. Discovery day A
is 49 / 51 and does not test the formula. The later-day prediction held, but the formula remains
exploratory and the fixed panels cannot pin X down.

**Follow-up: the cap is soft (exploratory, 11-02).** Memo #3 [`4zMGqri3…`](https://explorer.solana.com/tx/4zMGqri3f4ufA5sAFoZsr5VXQM6V4q1YxVpiqHQLgCFwjAtbVLkSTS1yWBK3vRCdXQmgMPP4TynR67CGf41E7HUf) locked a follow-up before its
first probe ([design/capsweep.json](design/capsweep.json)): 45 windows on the four Harmonic validators, three
panels. S1 puts three 700-CU probes against three 4,400-CU probes to locate X. S2 and S3 put 4,400-CU probes
against 40,000-CU probes that pay slightly more: under a hard cap the 40,000-CU probes go first, and every
extra CU counted above X pushes them back. The model is cost' = cost − L + min(L, X) + ⌊β·max(L − X, 0)⌋
(β = 0 a hard cap, β = 1 plain `agave_int`). The memo predicted a soft cap (0 < β < 1) with X in 1,660–4,098.

27 windows landed fully, sharing one order per panel across validators: S1
`FEDCBA` 8 / 8, S2 `CBAFED` 7 / 7, S3 `CBAFED` 12 / 12. The capped formula fits all 27; fitted solutions
span X = 1,500–1,963 CU and approximately β = 0.10–0.25. I fitted these parameters to the same 27 windows. The best hard cap
matches 8, plain `agave_int` 19. Memo #3's soft-cap prediction held; fitted X sits at the low end of the
predicted range or just below it (S1 alone puts X at or under 2,245; the sweep's grid starts at 1,500).
For a 40,000-CU limit this means about 3,600–8,900 of the 35,600 CU above a 4,400-CU limit still count.

A consistency check added after the sweep, outside memo #3, fits one (X, β) across all days: 195 of 198
full Harmonic windows at X = 1,500–1,963 (P1's data set the lower bound) and approximately β = 0.10–0.25.
The three misses are one calibration and two day-A windows; a hard cap fits 176, plain `agave_int` 110.
This is a fit, not a test: I chose X and β using these windows. It shows that one formula can explain
nearly every Harmonic order I saw, on the original and the follow-up panels. The advance tests are memo #2's
hard cap on days B–D (108 / 108) and memo #3's soft-cap prediction (held). The mechanism (possibly a
builder-side cost estimate) and stability under other load remain unknown.

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

Horizons in ms, with 95% intervals; dates follow the day labels in §1:

| Client | Validator | Day A | Day B | Day C | Day D |
|---|---|---|---|---|---|
| Agave | `7QQGNm3p` | 0 [0, 0] | — | — | — |
| JitoLabs | `E1r4Psq8` | 0 [0, 0] | — | — | — |
| Firedancer | `JD549Hsb` | 0 [0, 0] | 0 [0, 0] | 0 [0, 0] | — |
| Rakurai | `ana2y2Yv` | 0 [0, 0] | 0 [0, 0] | 44 [0, 44] | — |
| AgaveBam | `Fc6NNdS2` | 16 [12, 28] | too few trains | 16 [12, 28] | 16 [8, 28] |
| FireBAM | `SSmBEooM` | 44 [28, 44] | 24 [24, 24] | 44 [44, 44] | 36 [36, 36] |
| HarmonicAgave | `EkvdKhUL` | 16 [16, 20] | 12 [8, 20] | 16 [16, 24] | — |
| HarmonicFiredancer | `87CcUxpy` | 20 [20, 24] | 16 [16, 24] | 24 [24, 24] | 16 [16, 16] |

Queued probes sort on every client. During the window, probes keep send order on Agave, Jito, Firedancer
and (on two days of three) Rakurai: a richer probe sent 4 ms later does not pass a cheaper one. Through a
BAM node or Harmonic endpoint a richer probe can still pass a cheaper one sent 12–44 ms earlier, which
fits short batching before ordering. The FireBAM horizon moved between days (44, 24, 44, 36 ms) on one or
two evaluable trains per day, so I do not read it more precisely than "tens of milliseconds". Where a
validator-day has only one or two evaluable trains (counts in [tables](data/derived/tables.md)), the
interval collapses to the point estimate and says little about precision. This Firedancer validator's horizon
is 0; it is one operator, and other Firedancer operators may pace differently.

### 3.5 Day D

Day D (11-01) topped up the four Tier-1 validators furthest short of their target (§5). All four repeated
their earlier result: `Fc6NNdS2` 17 / 17, `SSmBEooM` 19 / 19 and `E1r4Psq8` 22 / 22 full windows in exact
`agave_int` order, and `87CcUxpy` 18 / 18 in the Harmonic formula's order. The horizons kept their size but
not their exact value: AgaveBam 16 ms again, FireBAM 36 ms (a fourth value), Harmonic 16 ms.

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
- **Evicted connections.** In the smoke test one Jito train and one BAM panel were never acknowledged: the
  validators dropped idle unstaked connections opened 6 s early. I now connect 3.5 s before the window
  (§1). Those probes never landed and cost nothing.
- **Decision rule too strict.** See section 2; changed before the pre-registration, from simulation only.
- **A stranger's deposit hid 9,374 lamports of fees.** During pilot-1027a an unknown address sent 9,374
  lamports to one of my fee payers ([`2sLiRbYW…`](https://explorer.solana.com/tx/2sLiRbYWEbhjqXfq4KVcNqoxneckPAVqJBXMFYq99EPreqMabLvfeJRBPBdAZkKNQtzBsddWRstuvqiqzC54hQ85)).
  The deposit arrived while fee reservations were open, understating balance-based spend by 9,374
  lamports. Comparing block fees with balances caught it the next day, and I logged it as an inflow.
  Seven more unsolicited deposits (54,701 lamports: six within three minutes on 10-29, one on 10-31) did the
  same and were found only by the final audit (§6).
- **The main wallet could not empty itself.** On 11-02 I emptied the eleven fee payers first. A fee payer
  must keep the rent minimum (650,240 lamports) after its 5,000-lamport fee unless it ends at zero, so the
  main wallet (654,597) could not pay for its own transfer, and no funded wallet was left to pay for it. The
  sweep code now empties the smallest wallets first and lets a richer one pay their fees.
- **Unstaked connection closures.** Days A–D: the endpoint closed the connection in 61 of 288 BAM windows
  (21%), 33 of 550 own-IP windows (6%) and 0 of 263 Harmonic windows ([tables](data/derived/tables.md),
  "Delivery by route"). A closed stream does not prove the probe was lost: 84 of the 628 probes on a closed
  connection still landed (36 through BAM, 48 own-IP) and their 544,473 lamports are in the fee totals; the
  other 544 never landed and cost nothing. `Fc6NNdS2` lost 13 of 30 day-B windows and is "insufficient data"
  that day.
- **Tier-2 quotas below the data minimum.** I sized the day-C Tier-2 quotas (16–24 windows) for 12
  informative windows, under the 15 evaluable panels PREREG requires for a call. Seven of the eight Tier-2
  validators came out "insufficient data" on their only held-out day. Outside Harmonic, their full
  windows are consistent with the predicted key; they do not establish registered passes.
- **Connection failures.** 5 of more than 1,000 campaign windows (`C-1031-b0-0045` to `C-1031-b0-0048` and
  `D-1101-b4-0000`) could not open a QUIC connection, so nothing was sent or spent.
- **Stale slot clock.** Five windows (three on day A, two on day B) were skipped because the slot stream had
  fallen behind; the sender does not time a send from a stale clock.
- **Snapshots that do not bracket a window.** Seven full windows on days A–C had no gossip snapshot of the
  target within 60 s on one side of the send, so they are left out of client claims (the rule in
  PREREG.md). Counting them would add 3 to Agave's key and 4 to the Harmonic formula, all in agreement.

## 5. Deviations from the pre-registration

- **Day D eligibility count.** PREREG allows day D for a Tier-1 validator short of its target "because of
  low supply or transitions". I counted fully landed K-main windows against the 22-window target (stricter
  than per contrast), fixed on 10-31 before day C ended. Six were short; the budget covered the four largest
  shortfalls (`Fc6NNdS2`, `E1r4Psq8`, `SSmBEooM`, `87CcUxpy`), with their day-C quotas
  ([design/campaign-dayD.json](design/campaign-dayD.json), committed before its first probe).
- **Harmonic cap sweep (addition).** Not in PREREG. Designed after days A–C to measure the cap in the
  exploratory Harmonic formula, locked on chain by memo #3 before its first probe
  ([design/capsweep.json](design/capsweep.json)), and reported apart: it changes no registered call.
- **Harmonic follow-up plan drawn twice.** The first random draw of the follow-up plan gave panels S3 29,
  S2 9 and S1 9 of 47 windows (about a 1-in-3,000 split; the generator checked out uniform). S1 and S2 each
  need at least four fully landed windows, so I drew once more, on panel counts only, before any probe of
  the follow-up was sent: S3 18, S2 14, S1 13 of 45. The unused first draw is
  [design/capsweep-plan-draw1-unused.json](design/capsweep-plan-draw1-unused.json).
- **Held-out data gate (correction, 11-02).** My first held-out tables counted validator-days with fewer
  than 15 evaluable panels as passes (`holdout()` skipped the registered minimum), and the README said "17
  of 18 held". The code now applies the gate; the tables above are the corrected ones.
- **Exact-order counts (addition).** The "full windows in exact key order" columns are descriptive, added
  after the campaign as a plain-language check; the calls rest on the registered tests.

## 6. Cost

Fees charged, from the block `meta.fee` of every transaction my wallets signed (per run in
[data/derived/tables.md](data/derived/tables.md), "Runs"):

| Phase | Dates (UTC) | Fees, lamports |
|---|---|---|
| Smoke test and pilots | 10-27 to 10-28 | 3,883,727 |
| Day A | 10-29 | 13,183,839 |
| Day B | 10-30 | 9,727,658 |
| Day C | 10-31 | 13,988,910 |
| Day D | 11-01 | 4,677,654 |
| Harmonic follow-up | 11-02 | 2,510,921 |
| Payer funding (26 transfers) | 10-27 to 11-02 | 130,000 |
| Memos (3) | 10-28 to 11-02 | 15,000 |
| Returning the funds (11 transfers) | 11-02 | 55,000 |
| **Total** | | **48,172,709 (0.048173 SOL)** |

The cap in code is 50,000,000 lamports for everything. The ledger reserves each transaction's maximum fee
before sending and releases reservations only after a balance check of all twelve wallets. The final audit,
[data/audit/audit-2026-11-02T093538Z.json](data/audit/audit-2026-11-02T093538Z.json), lists all 40 operations transactions by signature
and fee, and every transaction that touched my wallets without my signature. `docker compose up` checks
the total three ways ([tables](data/derived/tables.md), "Cost check"): probe plus operations fees equal the
audit's on-chain total (48,172,709) and the balance-based spend (48,118,008) plus the seven unsolicited
deposits (54,701). The deposits made the ledger show 54,701 lamports more headroom than there was; the cap
held either way. 11 transfers returned 11,236,769 lamports to the funding wallet; 654,597 stay in the main
wallet (§4).
