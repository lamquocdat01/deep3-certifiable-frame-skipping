# A3 (R1.1) — Event clustering: what it touches, what it doesn't, and robust budgets

*Theory notes for the revision. Numbers from `analyze_clustering.py` → `a3_results.json`
(onsets/durations from `events_gated.csv`, simulated periodic policy R = 5, δ = 0.05).*

## Scoping the concern (the response's opening move)

Assumption A2 (independent durations) is used in **exactly one place** in the paper: the
Hoeffding concentration of Proposition 4 (missed-event budget). It is *not* used by:

- **Theorem 1 / Theorem 2** (worst-case bound & detectability) — deterministic, no A1/A2;
- **Proposition 2** (miss probability): by *linearity of expectation*, E[miss rate] =
  E_D[(1−D/R)₊] holds for the marginal duration law F_D under **arbitrary dependence**
  between events — clustering shifts the variance, never the mean.

Empirical confirmation: on real onsets (which do cluster), the simulated periodic policy's
miss rate is 0.4088 vs the formula's 0.4062 — the mean formula is unaffected by the measured
dependence.

## Measured dependence (new empirical subsection)

On 3,723 events ordered by onset within each of the videos:

| statistic | value |
|---|---|
| miss-indicator autocorrelation, lag 1 / 2 / 3 | 0.060 / 0.031 / −0.013 |
| log-duration autocorrelation, lag 1 / 2 / 3 | 0.198 / 0.081 / 0.041 |
| effective dependence range m_eff (first lag with \|ρ\|<0.05) | 2 |
| within-video clumping ratio (obs/shuffled), median / q90 | 0.34 / 4.05 |

Durations are noticeably correlated at lag 1 (ρ ≈ 0.20) — neighbours are alike — but the
*miss indicators* decorrelate almost immediately (ρ₁ ≈ 0.06), because the refresh phase
re-randomizes the outcome between neighbouring events. Dependence is real, weak, and
short-range; a heavy-clumping tail exists (q90 ≈ 4) in a minority of scenes.

## Proposition A3.1 (mean invariance)

Under A1 alone (uniform phase per event, no independence), the expected number of misses in
any horizon with events {e₁,…,e_N} is Σᵢ (1 − Dᵢ/R)₊, and the expected miss *rate* equals
E_{D~F̂}[(1−D/R)₊] for the empirical marginal F̂. **Proof.** Linearity of expectation;
each event's miss probability given its duration is (1−D/R)₊ regardless of the joint law. ∎

## Proposition A3.2 (m-dependent missed-event budget)

If miss indicators are m-dependent (events at distance > m in onset order are independent),
then with probability ≥ 1−δ,

  M ≤ N·Pr(miss) + √( mN/2 · ln(m/δ) ).

**Proof.** Partition the sequence into m interleaved subsequences by index mod m; each is an
independent Bernoulli sequence of length ≤ ⌈N/m⌉. Hoeffding with confidence δ/m on each and
a union bound give total deviation ≤ m·√(⌈N/m⌉/2 · ln(m/δ)) ≤ √(mN/2 · ln(m/δ)). ∎

The independent case m = 1 recovers Proposition 4. The price of dependence is the √m factor.

## Proposition A3.3 (fleet-level budget — no within-scene assumption at all)

Across independent scenes/videos v with N_v events each (arbitrary dependence *inside* each
scene), with probability ≥ 1−δ,

  M ≤ Σ_v N_v·Pr(miss) + √( ln(1/δ)/2 · Σ_v N_v² ).

**Proof.** M = Σ_v M_v with independent M_v ∈ [0, N_v]; Hoeffding for bounded independent
summands. ∎ This is the deployment-relevant statement (a fleet of cameras), and it holds
even if every scene is arbitrarily clustered internally.

## Empirical coverage (the 92.4%-vs-95% reconciliation)

Per-video budget coverage at δ = 0.05 (videos with ≥5 events, simulated periodic policy):

| budget | coverage |
|---|---|
| independent Hoeffding (paper's Prop. 4) | 88.0% — shortfall, as the paper observed |
| m-dependent, m = m_eff = 2 | 92.0% |
| m-dependent, m = R = 5 (natural choice: one refresh period) | **97.3% ≥ 95% ✓** |
| fleet-level (all 3,723 events) | 1,522 missed ≤ 2,270 budget ✓ |

The shortfall under the independence assumption is *reproduced*, and choosing m = R —
interpretable as "events within one refresh period of each other may interact" — restores
the nominal confidence. (Note: our reproduction filters to videos with ≥5 events; the
manuscript revision will recompute the original 92.4% figure and the corrected one under one
consistent protocol.)

## What goes into the manuscript

1. Sec. V: add Props A3.1–A3.3 (A3.1 one line after Prop 2; A3.2 replacing/augmenting
   Prop 4; A3.3 as the deployment statement). State plainly which results never needed A2.
2. Sec. VII-B: new table with the dependence diagnostics + the coverage comparison above.
3. Discussion: clustering affects only concentration, the √m correction is cheap, and the
   randomized-phase refresh of A1.3 (R2.2) further weakens within-scene phase coupling —
   cross-reference the two responses.
4. Response letter R1.1: acknowledge the reviewer's point as correct in scope (concentration
   only), show measurements, give the two robust bounds, show restored coverage.
