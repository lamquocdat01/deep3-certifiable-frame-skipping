# A1 (R2.2) — Robustness to non-uniform event phase

*Theory notes for the revision. Paper-ready statements + proofs; numbers verified on
`events_durations.csv` (3,723 events) by `sim_phase.py` → `a1_results.json`.*

## Setup

Refresh fires at frames ≡ φ (mod R). Event onset s, phase U = (s − φ) mod R, duration D.
For D < R the event is missed **iff** U ∈ M_D := {1, …, R−D}; for D ≥ R it is always caught
within R−1 frames (Theorem 1 — a deterministic statement, **independent of any phase law**).
Let μ be the phase distribution on {0,…,R−1} and δ := d_TV(μ, Unif) ∈ [0, 1−1/R].

---

## Proposition A1.1 (phase-perturbation bound)

For any phase law μ with d_TV(μ, Unif) = δ:

  (i) |P_μ(miss) − E_D[(1−D/R)₊]| ≤ δ;

  (ii) for events with D ≥ R, the latency L = (R−U) mod R satisfies
       max_k |P_μ(L=k) − 1/R| ≤ δ and |E_μ[L] − (R−1)/2| ≤ (R−1)δ.

**Proof.** (i) P_μ(miss) = E_D[μ(M_D)] and the uniform value is E_D[|M_D|/R]. For every fixed
set A, |μ(A) − Unif(A)| ≤ d_TV(μ, Unif) = δ; apply with A = M_D pointwise in D and take
expectations. (ii) L is a bijective transform of U, so d_TV of the induced laws is also δ;
the pointwise bound is TV applied to singletons, and the mean bound is |E_μ f − E_Unif f| ≤
range(f)·δ with range(L) = R−1. ∎

*Both bounds are tight (achieved by mixtures with a point mass, e.g. the family below).*

## Proposition A1.2 (synchronized worst case — and what survives it)

Over all phase laws μ:

  sup_μ P_μ(miss) = F_D(R−1) = P(D ≤ R−1), attained by μ = δ₁
  (every event begins one frame after a refresh);

  inf_μ P_μ(miss) = 0, attained by μ = δ₀ (every event begins on a refresh frame).

Moreover, **for every μ** — including full adversarial synchronization — every event with
D ≥ R is detected within R−1 frames: the worst-case certificate of Theorem 1 is *unaffected*
by phase; degradation is confined to the sub-R (uncertifiable) events, whose miss probability
rises from E[(1−D/R)₊] to at most F_D(R−1).

**Proof.** μ(M_D) is maximized pointwise by putting all mass on 1 ∈ M_D whenever M_D ≠ ∅
(i.e. D < R), giving E_D[1{D<R}] = F_D(R−1); minimized by mass on 0 ∉ M_D, giving 0. The
final claim is Theorem 1, whose proof never invokes A1/A2. ∎

**Measured on our data (R = 5):** uniform-phase miss 0.4062 (the paper's 0.41); fully
synchronized worst case 0.6035 (= F_D(4)), a +49% relative increase; fully aligned best case
0.0000. Under the mixture family μ_ρ = (1−ρ)Unif + ρδ_{u₀} (TV = ρ(1−1/R)), the measured miss
stays inside the Proposition A1.1 band at all 21 grid points in ρ ∈ [0,1], both directions
(0 violations).

## Proposition A1.3 (randomized-phase refresh: A1 by construction)

Let the scheduler draw its refresh offset Φ ~ Unif{0,…,R−1} at deployment, independently of
the event process, and keep it secret. Then for **any** onset sequence — deterministic,
periodic, or adversarial but Φ-blind — the induced per-event phase U_e = (s_e − Φ) mod R is
exactly uniform, hence:

  P(miss) = E_D[(1−D/R)₊]  and  L | {D ≥ R} ~ Unif{0,…,R−1}  hold **by construction**.

Assumption A1 is thereby converted from a statistical hypothesis about the world into a
property the system enforces. Two refinements:

  (a) **Block re-randomization.** Redrawing Φ every T frames (a *block*) makes per-event
      phases independent **across blocks**, restoring Hoeffding-type concentration for the
      missed-event budget at block granularity (ties into the A3/R1.1 dependent-bound story).
      With one global Φ the *mean* matches the formula but the per-deployment variance is
      inflated (all events share one draw); re-randomization shrinks it as 1/√(#blocks).

  (b) **Guarantee-preserving switch.** Naively switching from offset φ₁ to φ₂ can open a gap
      of up to 2R−1 frames between forced refreshes. Forcing one OPEN on the block-boundary
      frame before adopting the new offset caps every inter-refresh gap at R, so the
      R-refresh property — and with it Theorem 1 — is preserved through re-randomization at
      the cost of ≤ 1/T extra activation.

**Proof.** For fixed s, (s − Φ) mod R with Φ uniform is uniform; independence of Φ from the
event process makes this the conditional phase law of every event, and the paper's
Propositions 1–2 apply verbatim. (a) follows because distinct blocks use i.i.d. offsets;
(b) is immediate from the construction. ∎

**Monte-Carlo check** (2,000 runs, 3,723 events/run, durations resampled from F_D,
adversarial onsets s ≡ 1 (mod R)): fixed-phase refresh misses 0.5982; randomized-phase
refresh misses 0.4053 ± 0.2227 (mean over runs) vs formula 0.4062 — mean restored exactly;
the large per-run std is the shared-Φ effect that (a) removes.

---

## What goes into the manuscript

1. New subsection in Sec. V ("Robustness to non-uniform phase"): Props A1.1–A1.3 (A1.1 and
   A1.3 as formal propositions; A1.2 folded into the text around them).
2. New figure: miss vs ρ for the synchronized-mixture family, with the ±δ band of A1.1 and
   the F_D(R−1) ceiling of A1.2 (both directions u₀ ∈ {0,1}); R = 5.
3. One paragraph in Discussion: the certificate never depended on A1; the stochastic tier now
   degrades gracefully (A1.1), has an explicit worst case (A1.2), and can be made
   assumption-free by randomizing the refresh phase (A1.3).
4. Response letter R2.2: summarize + point to the new subsection/figure.

## Numbers to quote (R = 5, pooled 3,723 events)

| quantity | value |
|---|---|
| miss, uniform phase (formula & paper) | 0.4062 |
| miss, fully synchronized worst (F_D(4)) | 0.6035 (+49%) |
| miss, fully aligned best | 0.0000 |
| perturbation-band violations (42 checks) | 0 |
| randomized-phase refresh vs adversarial stream | 0.4053 ± 0.2227 (mean matches 0.4062) |
