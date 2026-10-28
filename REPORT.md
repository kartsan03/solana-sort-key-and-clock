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

RESULTS_PLACEHOLDER

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

## 5. Deviations from the pre-registration

DEVIATIONS_PLACEHOLDER

## 6. Cost

COST_PLACEHOLDER
