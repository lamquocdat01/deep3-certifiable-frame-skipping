# A4 (R1.2) — Composing the schedule certificate with detector reliability

*Theory notes for the revision. Numbers from `analyze_detector.py` → `a4_results.json`
(g_t timelines from `frame_scores.parquet`, 171,589 frames; F_D from the committed table).*

## Scoping (response opening)

The paper's event definition is deliberately *detector-relative*: an event is footage the
deployed detector can recognize, so the certificate isolates the **schedule's** contribution.
The reviewer is right that a deployment cares about the **composition**: schedule × detector.
This note supplies that composition — an exact stochastic law, a probabilistic worst-case
certificate, and a measured reliability input — while stating honestly what no schedule can
fix (footage the detector can never recognize is invisible to any invocation policy).

## Model

Each OPEN landing inside an event detects it with per-invocation recall p, independently
across invocations. (The adversarial fully-correlated case is treated in the remark below.)

## Theorem A4.1 (composed stochastic law)

Under A1 (uniform phase), the number of refresh invocations inside a span of length D is
⌊D/R⌋ or ⌊D/R⌋+1, the latter with probability f = D/R − ⌊D/R⌋. Hence

  P(miss | D) = (1−f)(1−p)^{⌊D/R⌋} + f(1−p)^{⌊D/R⌋+1},

and P(miss) = E_D[·]. Setting p = 1 recovers the paper's (1−D/R)₊ exactly. Latency given
detection: successful detection occurs at the j-th in-event invocation with geometric law;
for long events E[L] ≈ (R−1)/2 + R(1−p)/p.

**Proof.** The refresh grid intersects a span of length D in ⌊D/R⌋ points, plus one more iff
the phase falls in a set of measure f — the same counting as in the paper's Prop. 2; failures
multiply by independence. p = 1: the expression becomes P(at least one invocation) missing
⇔ k = 0 and no extra point, probability (1−f)·1{D<R} = (1−D/R)₊. Latency: the first success
among consecutive invocations spaced R apart. ∎

**Empirical magnitude (R = 5, pooled F_D):** composed miss 0.4062 (p=1) → 0.4137 (p=0.972,
measured) → 0.4341 (p=0.9): a +1.8% relative increase at the measured reliability — the
schedule term, not detector error, dominates the miss budget at the deployed operating point.

## Theorem A4.2 (reliability-adjusted certification — the "price" extended)

An event with D ≥ kR contains at least k refresh invocations, so under independent failures
P(miss) ≤ (1−p)^k. Consequently, to certify events of duration ≥ D_target at confidence
1−η one needs

  k(η, p) = ⌈ln η / ln(1−p)⌉ invocations, i.e. R ≤ D_target / k(η,p),
  activation ≥ k(η,p)/D_target, energy E(k(η,p)/D_target).

This generalizes the price of certifiability: the deterministic certificate (η = 0) is
unattainable for p < 1; certificates become (1−η)-probabilistic, and reliability enters the
energy price as the multiplicative factor k(η, p).

**Measured examples (E_idle = 30.4, E_active = 290.8 mJ; p̂ = 0.972):**

| η | p | k | D_target=5 | D_target=10 |
|---|---|---|---|---|
| 0.05 | 0.972 | 1 | 82.5 mJ (unchanged) | 56.4 mJ (unchanged) |
| 0.01 | 0.972 | 2 | 134.6 mJ (+63%) | 82.5 mJ (+46%) |
| 0.05 | 0.95 | 2 | 134.6 mJ | 82.5 mJ |

At the measured reliability, 95%-confidence certification costs *no more energy* than the
idealized certificate; pushing to 99% doubles the required invocations.

**Remark (correlated failures — the honest caveat).** If invocation failures may be
arbitrarily correlated (e.g. a persistent occlusion the detector never resolves), then
P(miss) ≤ 1−p for any k: repetition buys nothing. The schedule-level remedy is invocation
*diversity* (alternating detectors/thresholds across refreshes), which restores an effective
independence — we note this as the detector-side dual of shielding and leave it to future
work.

## Measured reliability input (no raw video needed)

Detector flicker — short g_t = 0 gaps splitting one physical event into several detected
runs — is the visible trace of per-frame false negatives in the existing artifacts:

- 3,592 gaps between detected runs; **53.6% have length exactly 1** (single-frame dropouts),
  75.5% length ≤ 3, median 1 — the gap structure is flicker-dominated, which independently
  supports the paper's reading of D_min = 1 events as detector flicker.
- Merging runs separated by ≤ G frames and measuring the in-event detection rate gives
  p̂(G) = 0.986 / 0.978 / 0.972 / 0.965 for G = 1/2/3/5 — stable; we adopt p̂ = 0.972 (G=3).

*Scope note for the manuscript:* p̂ is recall with respect to detector-visible physical
events (merged runs). Recall against full ground truth (CDnet2014 masks) is a stricter
number; the revision will report both, but the composition theorems take either as input.

## What goes into the manuscript

1. Sec. IV/V: Theorem A4.1 (+ latency remark) after Prop. 2; Theorem A4.2 extending the
   price-of-certifiability (Thm. 7-family), with the correlated-failure remark.
2. Sec. VII: flicker/gap measurement subsection (also strengthens the D_min = 1 discussion);
   composed-miss column added to the certification table.
3. Discussion: guarantee = schedule certificate × detector reliability, now explicit;
   diversity-across-invocations as future work.
4. Response letter R1.2: definition was deliberate (isolation), composition now provided
   (A4.1/A4.2), reliability measured (p̂ = 0.972), limitation stated (correlated failures).
