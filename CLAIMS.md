# Claims and their evidence

Each row: what we claim, for which validator, on which windows, and how to re-check it.
`docker compose up` recomputes every number offline; `docker compose run --rm verify` re-fetches the blocks from a public RPC (`VERIFY_ALL=1` for all).

| # | Claim | Validator | Phase | Windows (informative) | Example slot:index / signature | Counterexample windows |
|---|---|---|---|---|---|---|
| — | No confirmatory claims yet (calibration data only). | | | | | |
