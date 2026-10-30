# Claims and their evidence

Each row: what we claim, for which validator, on which windows, and how to re-check it.
`docker compose up` recomputes every number offline; `docker compose run --rm verify` re-fetches the blocks from a public RPC (`VERIFY_ALL=1` for all).

| # | Claim | Validator | Phase | Windows (informative) | Example slot:index / signature | Counterexample windows |
|---|---|---|---|---|---|---|
| 1 | `7QQGNm3p` orders queued probes by `agave_int` (rule (strict); min win rate 1.00) | `7QQGNm3ptwinipDCyaCF7jY5katgmFUu1ieP2f7nwLpE` | dayA | 31 (27+) | 462679412:15 `2VP1BTCUmh1RkVYa…` | none |
| 2 | `E1r4Psq8` orders queued probes by `agave_int` (rule (strict); min win rate 1.00) | `E1r4Psq84tHfQ6aPTvvDka4U3u8zPVD7gEUrH25RdxHL` | dayA | 23 (21+) | 462675844:15 `3cjpLdQJ2BSnJvAH…` | none |
| 3 | `Fc6NNdS2` orders queued probes by `agave_int` (rule (strict); min win rate 1.00) | `Fc6NNdS2j3EmrWbU6Uqt6wsKB5ef72NjaWfNxKYbULGD` | dayA | 25 (20+) | 462681052:54 `3MDynBNg8ns7XyRa…` | none |
| 4 | `JD549Hsb` orders queued probes by `fd_exact` (rule (strict); min win rate 1.00) | `JD549HsbJHeEKKUrKgg4Fj2iyv2RGjsV7NTZjZUrHybB` | dayA | 22 (20+) | 462674172:35 `57i5BGBWgBuEJUtK…` | none |
| 5 | `SSmBEooM` orders queued probes by `agave_int` (rule (strict); min win rate 1.00) | `SSmBEooM7RkmyuXxuKgAhTvhQZ36Z3G2WsmLGJKoQLY` | dayA | 26 (20+) | 462673688:45 `55Cq6kajPapnz72r…` | none |
| 6 | `ana2y2Yv` orders queued probes by `agave_int` (rule (strict); min win rate 1.00) | `ana2y2YvQ3ZPMwm6qhnN3nJoUSiT3qx5Pvetkq9xcfY` | dayA | 37 (34+) | 462674884:5 `3e3xMLgn9GmCVGD1…` | none |
