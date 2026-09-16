# R1 additions (IEEE IoT-J revision, 16 September 2026)

This directory holds everything the R1 revision added to the paper's numbers.
It answers two reviewer comments and records one author-initiated correction.
Nothing here changes a central value reported in the previous round.

## Layout

```
R1_additions/
  analyze_mdep.py        -> a5_results.json        reviewer comment R2.1
  analyze_relcorr.py     -> a6_results.json        reviewer comment R2.2
  gum_budget_ina219.json                           JCGM 101 re-analysis of the C2b campaign
  make_numbers_r1.py     -> numbers_r1.json        every number the paper prints, as LaTeX macros
```

Both analysis scripts carry an absolute `DATA` path pointing at the author's
copy of `data/processed/`. Set it to your own checkout of `data/processed/`
before running; the scripts are otherwise byte-identical to the versions that
produced the committed JSON, so the provenance chain stays intact.

## What each one establishes

### `analyze_mdep.py` — why the miss budget may use `m = R` (R2.1)

Descends from `A3_clustering/analyze_clustering.py`, same protocol (videos with
at least five events, `delta = 0.05`, simulated periodic policy, `R = 5`), but
run on the 3,713-event table rather than the 3,723-row CSV that still held ten
VIRAT placeholder rows. It

* reproduces the round-1 numbers exactly: `p_formula = 0.4073`,
  `p_simulated = 0.4099`, per-video coverage 88.0% / 92.0% / 97.3% at
  `m = 1 / 2 / 5`, fleet bound 1,522 missed against 2,270;
* measures the **structural** dependence order: onsets are at least two frames
  apart, at most three share an `R`-frame block, so `m <= 2` and a fortiori
  `m <= R` under the randomized-phase refresh (Corollary S4' in the paper);
* sweeps coverage over `m` for the fixed-phase policy, the randomized-phase
  policy with the forced boundary OPEN, and the cheaper variant without it,
  reporting the activation each costs. Each configuration's budget is centred on
  its OWN mean miss rate, computed analytically per event and cross-checked
  against the simulation (0.4073 fixed phase, 0.3012 randomized phase, 0.4269
  without the boundary OPEN). Centring every configuration on the fixed-phase
  mean, as the first version did, credits the boundary OPEN's lower miss rate as
  concentration and makes every `m` "pass" on slack; those numbers survive in the
  JSON only under `..._UNMATCHED_centre_do_not_report`;
* replaces the autocorrelation-only diagnostic with lagged mutual information
  against a permutation null and a block-permutation test. Both are reported as
  they came out, including the fact that the run statistic still rejects
  `R`-dependence under the fixed-phase policy.

### `analyze_relcorr.py` — sensitivity to correlated invocation failures (R2.2)

Estimates the persistence `rho = P(fail at t+R | fail at t)` from the detector's
own false-negative sequence inside physical events (merge gaps of at most three
frames, the protocol behind `p_hat = 0.972` in `A4_detector/`), bootstrapping
over events rather than frames, and evaluates the two-state Markov model
(Proposition S8) on that estimate. Headline: `rho_hat = 0.210 [0.188, 0.232]`,
7.6x the value independence would give, yet `k = 1` for every `rho` at 95%
confidence because `1 - p_hat < 0.05`.

### `gum_budget_ina219.json` — uncertainty intervals under JCGM 101

A re-analysis of the same INA219 campaign already in `C2_mcu/`, propagating the
Type-A and Type-B contributions and cross-checking with a Monte-Carlo
propagation of the input distributions. The estimator reproduces the published
values to 1e-9 (9 of 9 quantities), so **no central value changes**; what
changes is the interval, from Type-A standard uncertainties at `k = 1` to 95%
Monte-Carlo intervals.

## Suggested tag

`v1.1-iotj-r1` — to be pushed **only after** the revision is submitted.
