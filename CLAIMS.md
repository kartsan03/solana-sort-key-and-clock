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
| 7 | `7QQGNm3p` orders queued probes by `agave_int` (rule (strict); min win rate 1.00) | `7QQGNm3ptwinipDCyaCF7jY5katgmFUu1ieP2f7nwLpE` | dayB | 28 (25+) | 463092332:50 `5jmzfiyzHHgrbQJJ…` | none |
| 8 | `E1r4Psq8` orders queued probes by `agave_int` (rule (strict); min win rate 1.00) | `E1r4Psq84tHfQ6aPTvvDka4U3u8zPVD7gEUrH25RdxHL` | dayB | 19 (16+) | 463075104:45 `38AuX5dB1rqkUpuW…` | none |
| 9 | `Fc6NNdS2` orders queued probes by `agave_int` (insufficient data; min win rate 1.00) | `Fc6NNdS2j3EmrWbU6Uqt6wsKB5ef72NjaWfNxKYbULGD` | dayB | 17 (9+) | 463153340:53 `2CduZnoKgHdJ6DJq…` | none |
| 10 | `JD549Hsb` orders queued probes by `fd_exact` (rule (strict); min win rate 1.00) | `JD549HsbJHeEKKUrKgg4Fj2iyv2RGjsV7NTZjZUrHybB` | dayB | 24 (23+) | 463084372:85 `bpYXYVcN5ZFdGvi4…` | none |
| 11 | `SSmBEooM` orders queued probes by `agave_int` (rule (strict); min win rate 1.00) | `SSmBEooM7RkmyuXxuKgAhTvhQZ36Z3G2WsmLGJKoQLY` | dayB | 19 (16+) | 463097312:61 `erCpv2EjLXvEX9vm…` | none |
| 12 | `ana2y2Yv` orders queued probes by `agave_int` (rule (strict); min win rate 1.00) | `ana2y2YvQ3ZPMwm6qhnN3nJoUSiT3qx5Pvetkq9xcfY` | dayB | 35 (33+) | 463075948:25 `2SkvbmBmKMCzqxkb…` | none |
| 13 | `5EhGYUyQ` orders queued probes by `agave_int` (insufficient data; min win rate 1.00) | `5EhGYUyQNrxgUbuYF4vbL2SZDT6RMfhq3yjeyevvULeC` | dayC | 16 (12+) | 463483852:49 `2PfcmbCZsuw8FCXL…` | none |
| 14 | `5Us18hLZ` orders queued probes by `agave_int` (insufficient data; min win rate 1.00) | `5Us18hLZPXJTS4QVuGSsUw137Dyd2tgBaem24Xsf5nBS` | dayC | 12 (11+) | 463494300:19 `3YSyq7DtHubSmSdM…` | none |
| 15 | `7QQGNm3p` orders queued probes by `agave_int` (rule (strict); min win rate 1.00) | `7QQGNm3ptwinipDCyaCF7jY5katgmFUu1ieP2f7nwLpE` | dayC | 30 (26+) | 463488040:21 `2CJrnWGEr8p2kcV7…` | none |
| 16 | `C8Bey3LK` orders queued probes by `total_fee` (rule (strict); min win rate 1.00) | `C8Bey3LKVJHVqN6xPTeW8WJfUgFQAeGNBpT4Rp99JP1k` | dayC | 16 (14+) | 463518028:31 `5iRzs9gfoWMtTPAu…` | none |
| 17 | `DNVZMSqe` orders queued probes by `fd_exact` (insufficient data; min win rate 1.00) | `DNVZMSqeRH18Xa4MCTrb1MndNf3Npg4MEwqswo23eWkf` | dayC | 13 (13+) | 463497128:50 `PXmDwYSJzWcMVXh6…` | none |
| 18 | `E1r4Psq8` orders queued probes by `agave_int` (insufficient data; min win rate 1.00) | `E1r4Psq84tHfQ6aPTvvDka4U3u8zPVD7gEUrH25RdxHL` | dayC | 14 (10+) | 463484484:16 `2HCUaVyk6GfRsNNv…` | none |
| 19 | `E3mDbFMr` orders queued probes by `agave_int` (insufficient data; min win rate 1.00) | `E3mDbFMr8yZcCAZx5wPUFCRmLX31u8Nnj4jPoPc54h3F` | dayC | 12 (12+) | 463519520:25 `icXr8ogaLFPPa96z…` | none |
| 20 | `Fc6NNdS2` orders queued probes by `agave_int` (rule (strict); min win rate 1.00) | `Fc6NNdS2j3EmrWbU6Uqt6wsKB5ef72NjaWfNxKYbULGD` | dayC | 21 (18+) | 463481264:28 `4TNcoLX27XmeEi4N…` | none |
| 21 | `JD549Hsb` orders queued probes by `fd_exact` (rule (strict); min win rate 1.00) | `JD549HsbJHeEKKUrKgg4Fj2iyv2RGjsV7NTZjZUrHybB` | dayC | 19 (18+) | 463494772:32 `2fj7UbsfuvrvZW12…` | none |
| 22 | `PRGNnb8D` orders queued probes by `agave_int` (insufficient data; min win rate 1.00) | `PRGNnb8DxVcP2WjSHfVRGgc8SkA5u6dbMwoTVV1BGKN` | dayC | 10 (10+) | 463489760:23 `2AK5LPM7AHH5sRHR…` | none |
| 23 | `SSmBEooM` orders queued probes by `agave_int` (rule (strict); min win rate 1.00) | `SSmBEooM7RkmyuXxuKgAhTvhQZ36Z3G2WsmLGJKoQLY` | dayC | 17 (15+) | 463491140:32 `3sREe6U483HRND8y…` | none |
| 24 | `ana2y2Yv` orders queued probes by `agave_int` (rule (strict); min win rate 1.00) | `ana2y2YvQ3ZPMwm6qhnN3nJoUSiT3qx5Pvetkq9xcfY` | dayC | 23 (23+) | 463503932:24 `3faDUPqPMv9wnvMK…` | none |
| 25 | `E1r4Psq8` orders queued probes by `agave_int` (rule (strict); min win rate 1.00) | `E1r4Psq84tHfQ6aPTvvDka4U3u8zPVD7gEUrH25RdxHL` | dayD | 23 (23+) | 463897408:11 `2MUSQygrxJqbnyY8…` | none |
| 26 | `Fc6NNdS2` orders queued probes by `agave_int` (rule (strict); min win rate 1.00) | `Fc6NNdS2j3EmrWbU6Uqt6wsKB5ef72NjaWfNxKYbULGD` | dayD | 21 (17+) | 463912368:42 `122w5sb86b2qN5bz…` | none |
| 27 | `SSmBEooM` orders queued probes by `agave_int` (rule (strict); min win rate 1.00) | `SSmBEooM7RkmyuXxuKgAhTvhQZ36Z3G2WsmLGJKoQLY` | dayD | 23 (20+) | 463912740:32 `46u65FJnPtabJu4V…` | none |
