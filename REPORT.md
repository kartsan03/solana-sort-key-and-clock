# Report

I found distinct Agave and Firedancer ordering rules, a total-fee Jito validator, and an exploratory
Harmonic soft cap. Queued probes sort; overtaking during a leader window varies by route and day, measured
without the falling-fee control trains I had registered (§5).
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
the loaded-data limit. The panels tell dividing by C+1 from dividing by C; they cannot see Agave's rounding
down (exact R/(C+1) ranks both panels the same way). Controls use identical probes (K-null) or separate
locks (K-free).

**Trains (Study M).** 10–12 probes with equal L and D, sent one by one 4 ms or 12 ms apart inside the
window, with the fee rising along the send order. If the later, richer probe lands first, it overtook; the
largest send gap at which that still happens in at least half of pairs is the overtaking horizon. PREREG
also asked for 20% falling-fee trains as a control and a random spacing per window; a planning bug sent only
rising trains, and only 4 ms trains after day A (§5). Sends kept their planned gaps closely: median deviation
0.0025 ms, and 2 of 1,029 gaps were more than 1 ms off.

**Route.** I send unstaked QUIC directly to each leader's advertised TPU address, one transaction per
stream, opening a fresh connection 3.5 s before its window. BAM and Harmonic advertise builder endpoints;
the result describes each validator through that ingress.

**Timing.** The slot clock uses the RPC node's `firstShredReceived` timestamps
(`slotsUpdatesSubscribe`), extrapolated with a median gap per position in the 4-slot window (a new
leader's first slot shows up 270 ms after the previous slot, the next one 149 ms later, then 200, 200;
medians over days A–D).
Send times are corrected by half the QUIC round trip to the target.

**Randomisation.** I log OS-random choices per window: panel, send order, payer, offset and arm
(K-main / K-null / K-free); train spacing and direction should have been drawn too (§5). Analysis uses a
fixed seed for exact reproduction with `docker compose up`.

**Checking the pre-registration.** Each memo is a text that names a commit and SHA-256 hashes:

| Memo | Text (hashes shortened) | Check |
|---|---|---|
| #1 [`TywPFLUz…`](https://explorer.solana.com/tx/TywPFLUznyNThfq9hiKp34eikwW8ZHxs3xefwWfABCBsceRaSLJvnAPPk977XyTXSTJWGsMnW6i43cr2NGTwXxd), 10-28 | `itb-prereg 0bb3ee57… 7cee9bdf… 405c8a4b…` | `git show 0bb3ee5:PREREG.md \| sha256sum`, then `0bb3ee5:design/design.json` |
| #2 [`mbp3zEGq…`](https://explorer.solana.com/tx/mbp3zEGqTFnkJuLZkRndhWu4yFRkdxvwHJNMKZimE4QzbAeBMrT2RhE2N7ve8Z6F9BWkTV4ECBG1LoqwaCWJaNF), 10-29 | `itb-predictions f3f1c526… 0df6ff81…` | `git show f3f1c52:design/predictions-dayB.json \| sha256sum` |
| #3 [`4zMGqri3…`](https://explorer.solana.com/tx/4zMGqri3f4ufA5sAFoZsr5VXQM6V4q1YxVpiqHQLgCFwjAtbVLkSTS1yWBK3vRCdXQmgMPP4TynR67CGf41E7HUf), 11-02 | `itb-capsweep f705581d… d899e147… 7480a48c…` | `design/capsweep.json`, then `design/capsweep-targets.json`, at `f705581` |

The files memo #1 fixed (PREREG.md, design.json and the four design files it hashes) are unchanged since;
later design files were added, each committed before the probes it governs.

**Power.** In simulation (`itb sim`, [design/power-corrected.json](design/power-corrected.json)) with 22
K-main panels per validator-day (85% of probes landing), the true key is called in at least 99% of runs when
10% of windows are scrambled (73% at 25%); a random or first-in, first-out (FIFO) scheduler is called a rule
in at most 1%. With 16 panels a day often falls below the 15-panel minimum, and only about half of the runs
make a call. Simulated 20 and 50 ms rounds give horizons near 8 and 24 ms, so I report horizons, not round
lengths.

## 2. Design decisions

The [README](README.md#why-this-design) explains the probe and route choices. Each window counts once per
key pair, since pairs within a block are dependent. Before pre-registration I replaced a rule requiring
every rival to lose in more than 75% of windows (it failed in simulation with 10% scrambled windows) with
the registered one: the key must beat every rival in a majority of windows (exact binomial tests, Holm
across the eight main validators); strictness is reported separately. Day A picks undocumented builders'
keys and days B–D test them; documented clients face their source-code key from day A. Day A's pick is
the best of eight keys, and its p-value is not adjusted for that choice: the fixed-key held-out tests on
days B–D are the confirmatory ones. Rounds and stalled
queues can produce similar orders, so I measure timing without claiming a mechanism.

## 3. Results

A *full window* is a K-main panel whose six probes landed in one block of the target's window. The
registered tests drop windows whose gossip snapshots around the send show a change of client, ingress or
TPU address (PREREG); the exact-order counts also drop 10 full windows of days A–D that lack a snapshot within
60 s on one side. *Registered* means a test fixed before the campaign; *exploratory* means
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

- **Agave's R/(C+1) order on five client types.** 413 of 413 full windows on Agave, Jito
  (`E1r4Psq8`), AgaveBam, FireBAM and Rakurai came out in exact `agave_int` order (the panels cannot see
  its rounding down, §1), including every
  fingerprint pair (two in P1, three in P2), where Firedancer's exact ratio predicts the opposite.
  `E1r4Psq8` moved from Jito 4.3.2 to 4.4.0 during day C, with no change in its order.
- **Firedancer uses its own exact ratio.** All five fingerprint pairs went Firedancer's way in every full
  Firedancer window. The 6 of 77 full-order misses all came from `JD549Hsb`: four swapped the last two
  probes (`BAECFD` instead of `BAECDF`), and in two the last probe moved up to third or fourth place
  (`BAFECD`, `DAFBCE`); no fingerprint pair flipped. All six fell after its upgrade from Firedancer 26.10.4 to
  26.10.5 during day A (15 / 15 exact before, 43 / 49 after; the second validator, on 26.10.5, 13 / 13).
  Fifteen windows are too few to blame the upgrade (Fisher's exact test, p = 0.32).
- **FireBAM sorts like Agave.** FireBAM runs Firedancer, yet both FireBAM validators sort by Agave's key.
  That fits BAM's documentation, which says the BAM node sequences transactions before the validator
  replays them ([bam.dev/validators](https://bam.dev/validators/)); my design cannot see where the comparator
  ran (README, "does NOT separate", item 2).
- **Jito is not one rule.** `E1r4Psq8` follows Agave's key; `C8Bey3LK` sorted by total fee (5,000 + priority
  fee): 14 of 15 full windows in exact `total_fee` order (and both of its calibration windows), against 0
  for `agave_int`. This is one validator on one day (day C), predicted otherwise and never held out:
  exploratory. It ran Jito 4.4.0, as `E1r4Psq8` did from mid day C, so the version does not explain it. With separate locks
  (K-free) its order agrees with total fee in only 7% of pairs: the rule describes competing probes.
- **Harmonic fits none of the eight registered keys.** Day A's picks (`agave_int` for HarmonicAgave,
  `pf_per_cost` for HarmonicFiredancer) failed on days B–D. Yet the Harmonic orders are not noise:
  on days B–D every full window repeated one order per panel, whatever the send order (3.2).
- **Ties (K-null, descriptive).** With six identical probes, Firedancer put the later-sent probe first in
  192 of 195 same-block pairs (both validators, days A–C). No other client has a tie rule this clear: the
  share of pairs in send order runs from 0.25 (FireBAM) to 0.72 (Jito)
  ([tables](data/derived/tables.md), "Send order vs block order").
- **Block load does not change the key (pre-registered sensitivity).** Within thirds of block load per
  day, each validator-day's own best key keeps its pairwise agreement (window-weighted): 1.00 on Agave,
  Jito, AgaveBam, FireBAM and Rakurai, 0.99–1.00 on Firedancer and 0.90–0.94 on Harmonic in light, middle and
  heavy blocks alike ([tables](data/derived/tables.md), "by block load").
- **No clear effect of the fee on whether a probe lands (registered question 3, descriptive).** Trains
  land or fail as a whole: in 4 ms trains each fee rank landed 76–77 times of 87, the losses being BAM
  trains on closed connections ([tables](data/derived/tables.md), "by fee rank"). Every train rose in fee,
  so fee rank is also send position; this covers my small fees and this route only.

### 3.2 Harmonic: an explanation that fits and holds on later days

In day A's first block, all seven full Harmonic panels fit Agave's integer priority with the CU limit
counted toward cost only up to a cap X. Any X from 1,660 to 4,098 gives the observed orders. I fixed the
formula and predicted orders in `design/predictions-dayB.json`, hashed in memo #2 before day B, as
exploratory. On days B–D, 108 / 108 full windows across all four validators matched (B 37 / 37, C 53 / 53,
D 18 / 18), including 17 / 17 on `BtsmiEEv` and `CQdLgwkm`, which had no day-A windows. Only panel P1 tells
the formula from plain `agave_int`: on P2 both predict `DCFAEB`. The test is therefore P1's 48 / 48 (9 of
them on the two new validators); P2's 60 / 60 is consistent with either. Discovery day A is 49 / 51 and
does not test the formula. The later-day prediction held, but the formula remains exploratory and the
fixed panels cannot pin X down.

**Follow-up: the cap is soft (exploratory, 11-02).** Memo #3 [`4zMGqri3…`](https://explorer.solana.com/tx/4zMGqri3f4ufA5sAFoZsr5VXQM6V4q1YxVpiqHQLgCFwjAtbVLkSTS1yWBK3vRCdXQmgMPP4TynR67CGf41E7HUf) locked a follow-up before its
first probe ([design/capsweep.json](design/capsweep.json)): 45 windows on the four Harmonic validators, three
panels. S1 puts three 700-CU probes against three 4,400-CU probes to locate X. S2 and S3 put 4,400-CU probes
against 40,000-CU probes that pay slightly more: under a hard cap the 40,000-CU probes go first, and every
extra CU counted above X pushes them back. The model is cost' = cost − L + min(L, X) + ⌊β·max(L − X, 0)⌋
(β = 0 a hard cap, β = 1 plain `agave_int`). The memo predicted a soft cap (0 < β < 1) with X in 1,660–4,098.

27 windows landed fully, sharing one order per panel across validators: S1
`FEDCBA` 8 / 8, S2 `CBAFED` 7 / 7, S3 `CBAFED` 12 / 12: three orders. S1's order rules out plain
`agave_int`; S2 and S3 give plain `agave_int`'s order, which rules out a hard cap but only bounds β from below.
The capped formula fits all 27; fitted solutions span X = 1,500–1,963 CU and approximately β = 0.10–0.25.
I fitted these parameters to the same 27 windows. The best hard cap matches 8, plain `agave_int` 19. Memo
#3's soft-cap prediction held; fitted X sits at the low end of the predicted range or just below it (S1
alone puts X at or under 2,245; this sweep's grid starts at 1,500, the all-days fit's at 1,300). Other
ways of discounting the limit above X, such as scaling the whole limit, were not tested.
For a 40,000-CU limit this means about 3,600–8,900 of the 35,600 CU above a 4,400-CU limit still count.

A consistency check added after the sweep, outside memo #3, fits one (X, β) across all days: 195 of 198
full Harmonic windows at X = 1,500–1,963 (P1's data set the lower bound) and approximately β = 0.10–0.25.
The three misses are one calibration and two day-A windows; a hard cap fits 176, plain `agave_int` 110.
This is a fit, not a test: I chose X and β using these windows. The advance tests are memo #2's
hard cap on days B–D (P1: 48 / 48) and memo #3's soft-cap prediction (held). The mechanism (possibly a
builder-side cost estimate) and stability under other load remain unknown.

### 3.3 Held-out test (registered)

A validator-day counts only with at least 15 evaluable K-main panels and 5 informative windows against
every rival (PREREG); below that it is "insufficient data", whatever the test says.

| Day | Keys: passed / failed / too few panels | Horizons inside the day's interval | Misses |
|---|---|---|---|
| B (10-30) | 5 / 2 / 1 | 4 of 5 | keys: both Harmonic picks; too few: `Fc6NNdS2` (9); horizon: `SSmBEooM` predicted 44 ms, day B 24 ms |
| C (10-31) | 5 / 3 / 8 | 5 of 6 | keys: `EkvdKhUL`, `87CcUxpy`, `C8Bey3LK`; too few: seven Tier-2 validators and `E1r4Psq8` (6–13); horizon: `87CcUxpy` predicted 20 ms, day C 24 ms |
| D (11-01) | 3 / 1 / 0 | 1 of 3, 1 inconclusive | keys: `87CcUxpy`; horizon: `87CcUxpy`; inconclusive: `SSmBEooM` predicted 44 ms, day D ≥36 ms |

A day with one evaluable train has an "interval" of that one value, so its horizon check is weak. A horizon
at the longest same-block gap the day's trains showed is only a lower bound (≥ in the tables); a prediction
above it cannot miss. Of 14 horizon predictions, 10 fell inside, 3 missed and 1 was inconclusive. Outside
Harmonic: 13 passed, 1 failed, 7 too few panels. The failure, `C8Bey3LK`, was a Tier-2 Jito validator
predicted from Jito's source code; it is the total-fee result above. The seven short validator-days had 76
full windows between them, all in the predicted order: consistent, but not a test.

### 3.4 How strictly in time

Horizons in ms, with 95% bootstrap intervals over trains and, in brackets, the number of evaluable trains;
a cell from one train shows only its value. With two to seven trains the intervals describe these trains,
not a population. ≥ marks a horizon at the longest same-block gap the trains showed (44 ms at most for
4 ms trains): a lower bound. Dates follow the day labels in §1.

| Client | Validator | Day A | Day B | Day C | Day D |
|---|---|---|---|---|---|
| Agave | `7QQGNm3p` | 0 [0, 0] (2) | — | — | — |
| JitoLabs | `E1r4Psq8` | 0 [0, 0] (3) | — | — | — |
| Firedancer | `JD549Hsb` | 0 [0, 0] (6) | 0 [0, 0] (4) | 0 [0, 0] (4) | — |
| Rakurai | `ana2y2Yv` | 0 [0, 0] (7) | 0 [0, 0] (3) | ≥44 [0, 44] (3) | — |
| AgaveBam | `Fc6NNdS2` | 16 [12, 28] (2) | no evaluable train | 16 [12, 28] (2) | 16 [8, 28] (2) |
| FireBAM | `SSmBEooM` | ≥44 [28, 44] (2) | 24 (1) | ≥44 (1) | ≥36 (1) |
| HarmonicAgave | `EkvdKhUL` | 16 [16, 20] (7) | 12 [8, 20] (4) | 16 [16, 24] (3) | — |
| HarmonicFiredancer | `87CcUxpy` | 20 [20, 24] (7) | 16 [16, 24] (4) | 24 [24, 24] (2) | 16 [16, 16] (3) |

Queued probes sort on every client. During the window, probes keep send order on Agave, Jito, Firedancer
and (on two days of three) Rakurai: a richer probe sent 4 ms later does not pass a cheaper one. Through a
BAM node or Harmonic endpoint a richer probe can still pass a cheaper one sent 12–44 ms earlier, which
fits short batching before ordering. The FireBAM horizon moved between days (≥44, 24, ≥44, ≥36 ms) on one or
two evaluable trains per day, so I do not read it more precisely than "tens of milliseconds". Without the
falling-fee control (§5) I cannot fully separate overtaking by fee from a reordering that ignores the fee;
in the identical-probe panels no client outside Firedancer showed a clear send-order rule. This Firedancer
validator's horizon is 0; it is one operator, and other Firedancer operators may pace differently.

### 3.5 Day D

Day D (11-01) topped up the four Tier-1 validators furthest short of their target (§5). All four repeated
their earlier orders (`Fc6NNdS2` 17 / 17, `SSmBEooM` 19 / 19, `E1r4Psq8` 22 / 22 in `agave_int` order,
`87CcUxpy` 18 / 18 in the Harmonic formula's), and their horizons kept their size but not their value.

## 4. What went wrong

- **Memo program address.** The Memo v2 address in my notes does not exist on mainnet; a free
  `simulateTransaction` caught it before any spend (the real one is `MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr`).
- **`meta.costUnits` is the cost after execution,** not the scheduling cost, which uses the requested
  limits. I check the executed cost (1,935) per probe and compute priorities from the requested limits.
- **Relayer-port validators.** Two planned Jito validators and one Rakurai validator advertise TPU port
  11228 (the old Jito relayer); I replaced them with own-IP alternates before the pilot.
- **Evicted connections.** In the smoke test, validators dropped idle unstaked connections opened 6 s early,
  so one Jito train and one BAM panel never landed (no cost). I now connect 3.5 s before the window.
- **Decision rule too strict.** See section 2; changed before the pre-registration, from simulation only.
- **Unsolicited deposits hid fees.** During pilot-1027a an unknown address sent 9,374 lamports to a fee
  payer ([`2sLiRbYW…`](https://explorer.solana.com/tx/2sLiRbYWEbhjqXfq4KVcNqoxneckPAVqJBXMFYq99EPreqMabLvfeJRBPBdAZkKNQtzBsddWRstuvqiqzC54hQ85))
  while reservations were open, so balance-based spend read 9,374 too low; comparing block fees with
  balances caught it the next day. Seven more deposits (54,701 lamports: six on 10-29, one on 10-31) did the
  same; only the final audit found them (§6). Since 11-03 the ledger also counts landed fees from the chain,
  so such a deposit halts it.
- **The main wallet could not empty itself.** A fee payer must keep the rent minimum (650,240 lamports) after
  its fee unless it ends at zero. On 11-02 I emptied the fee payers first, so nothing was left to pay the main
  wallet's (654,597) transfer. The sweep code now empties the smallest wallets first, a richer one paying.
- **Unstaked connection closures.** Days A–D: the endpoint closed the connection in 61 of 288 BAM windows
  (21%), 33 of 550 own-IP windows (6%) and 0 of 263 Harmonic windows ([tables](data/derived/tables.md),
  "Delivery by route"). A closed stream does not prove a loss: 84 of the 628 probes on a closed connection
  still landed (544,473 lamports, in the totals). `Fc6NNdS2` lost 13 of 30 day-B windows this way.
- **Tier-2 quotas below the data minimum.** I sized day C's Tier-2 quotas for 12 informative windows, under
  the 15 evaluable panels PREREG requires for a call, so seven of eight Tier-2 validators came out
  "insufficient data": consistent with the predicted key, not registered passes.
- **Connection failures.** 5 of more than 1,000 campaign windows (`C-1031-b0-0045` to `C-1031-b0-0048` and
  `D-1101-b4-0000`) could not open a QUIC connection, so nothing was sent or spent.
- **Stale slot clock.** Five windows (three on day A, two on day B) were skipped because the slot stream had
  fallen behind; the sender does not time a send from a stale clock.
- **Snapshots that do not bracket a window.** Ten full windows (day A 1, B 3, C 3, D 3) had no gossip
  snapshot of the target within 60 s on one side of the send. The exact-order counts leave them out; the
  registered tests keep them, since PREREG excludes only windows whose snapshots show a change. Counting
  them would add 5 to Agave's key and 5 to the Harmonic formula, all in agreement.
- **The falling-fee trains were never sent.** PREREG draws 20% of trains with falling fees, as a control,
  and the spacing per window. The quota file carried a fixed list of spacings meant for calibration, and the
  plan step, given such a list, also forced every train to rising fees; it alternated the spacing per
  validator instead of drawing it, so days B–D got only 4 ms trains. An outside review found this on 11-03,
  after the measurements. The code is fixed and tested; the data cannot be redone.
- **Code faults found in the same review, fixed with tests.** `itb campaign` lost an option when the cap
  sweep added one (11-01, after the last campaign day). The spend cap watched the wallets listed in
  `design/wallets.json` instead of the loaded key's (the same wallets here). Reconciliation read balances
  before the finalized height, a small gap in which a landing fee could be missed.

## 5. Deviations from the pre-registration

- **Day D eligibility count.** PREREG allows day D for a Tier-1 validator short of its target "because of
  low supply or transitions". I counted fully landed K-main windows against the 22-window target (stricter
  than per contrast), fixed on 10-31 before day C ended. Six were short; the budget covered the four largest
  shortfalls (`Fc6NNdS2`, `E1r4Psq8`, `SSmBEooM`, `87CcUxpy`), with their day-C quotas
  ([design/campaign-dayD.json](design/campaign-dayD.json), committed before its first probe).
- **Harmonic cap sweep (addition).** Not in PREREG. Designed after days A–C to measure the cap in the
  exploratory Harmonic formula, locked on chain by memo #3 before its first probe
  ([design/capsweep.json](design/capsweep.json)), and reported apart: it changes no registered call.
- **Harmonic follow-up plan drawn twice.** The first draw gave panels S3 29, S2 9, S1 9 of 47 windows (about
  a 1-in-3,000 split); S1 and S2 each need four fully landed windows, so before any probe I drew once more,
  on panel counts only: S3 18, S2 14, S1 13 of 45 ([unused first draw](design/capsweep-plan-draw1-unused.json)).
- **Held-out data gate (correction, 11-02).** My first held-out tables counted validator-days with fewer
  than 15 evaluable panels as passes (`holdout()` skipped the registered minimum), and the README said "17
  of 18 held". The code now applies the gate; the tables above are the corrected ones.
- **Exact-order counts (addition).** The "full windows in exact key order" columns are descriptive, added
  after the campaign as a plain-language check; the calls rest on the registered tests.
- **Train direction and spacing (planning bug, §4).** All 95 campaign trains rose in fee; none fell. Spacing
  alternated per validator; days B–D used only 4 ms trains, while the day-A horizon predictions came from
  both spacings. The horizons therefore have no falling-fee control.
- **Strictness bound (correction, 11-03).** PREREG calls a key strict when the weakest rival's lower bound is
  at least 0.75. The code took the rival with the lowest win rate, which need not have the lowest bound; it
  now takes the lowest bound. Five bounds moved, no verdict changed: `JD549Hsb` day A 0.839 → 0.832, day B
  0.858 → 0.852, day C 0.824 → 0.815, calibration 0.398 → 0.292; `C8Bey3LK` day C 0.782 → 0.768.
- **Censored horizons (correction, 11-03).** A horizon at the longest same-block gap a day's trains showed
  is only a lower bound. FireBAM's day-D train split across two blocks, so its longest same-block gap was
  36 ms; the held-out check compared the predicted 44 ms with 36 and called it a miss. It is now
  inconclusive: horizon predictions went from 10 inside and 4 missed to 10 inside, 3 missed, 1 inconclusive.
- **Power simulation (correction, 11-03).** The simulation counted a correct key as a success even when
  the day had too few panels for a call, and judged train eligibility on landed instead of planned probes.
  Rerun after the fix ([design/power-corrected.json](design/power-corrected.json); the original
  [design/power.json](design/power.json) is kept): at 22 panels per validator-day the worst key's rate went
  from 1.00 to 0.99 with no scrambling and stayed at 0.99 and 0.73 with 10% and 25%; at 16 panels it fell
  from 0.79–1.00 to 0.45–0.54; horizons did not change. The quotas were 22 or more, so the design stands.
- **Randomisation check (addition, 11-03).** The registered test keeps the best key fixed while it permutes.
  For the seven Harmonic validator-days without an identified key I also re-chose the key inside every
  permutation; both versions give p = 0.0005, the smallest possible with 2,000 permutations.
- **Budget priority.** PREREG drops Tier 2, then K-free, then trains if money runs short. I applied that
  order when sizing blocks; the runner itself stops at the cap, which was never reached.
- **Inclusion by fee rank (late).** Registered as descriptive; first reported on 11-03.

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
before sending and releases reservations only after a balance check of all twelve wallets (since 11-03 the
loaded key's wallets, plus a chain count of landed fees). The final audit,
[data/audit/audit-2026-11-02T093538Z.json](data/audit/audit-2026-11-02T093538Z.json), lists all 40 operations transactions by signature
and fee, and every transaction that touched my wallets without my signature. `docker compose up` checks
the total three ways ([tables](data/derived/tables.md), "Cost check"): probe plus operations fees equal the
audit's on-chain total (48,172,709) and the balance-based spend (48,118,008) plus the seven unsolicited
deposits (54,701). The deposits made the ledger show 54,701 lamports more headroom than there was; the cap
held either way. 11 transfers returned 11,236,769 lamports to the funding wallet; 654,597 stay in the main
wallet (§4).
