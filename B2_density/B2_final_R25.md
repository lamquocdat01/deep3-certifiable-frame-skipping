# B2 (R2.5) — FINAL: Low-event-density evaluation
### (dilution study + VIRAT-P case study + the event-definition finding)

*Consolidates `B2_dilution_study.md` (cloud, 2026-07-15) and the VIRAT-P run
(`VIRAT_REDUMP_REPORT.md`, `*_viratp.*` artifacts, user PC, 2026-07-16). All committed
3-dataset artifacts untouched throughout.*

## 1. The finding that reframes the comment

Under the paper's class-agnostic has-box g_t, **no public surveillance benchmark is
sparse**: ρ_ev = 0.70 (CDnet2014), 0.79 (LASIESTA), 0.97 (BMC), and — decisively — **1.0000
for VIRAT over its full 41,823-frame timelines** (persistent objects: parked cars, standing
people keep an always-on detector firing). Event density is therefore **a property of the
(scene, event-definition) pair, not of the scene**. This is the paper-facing answer to "all
test datasets are foreground-heavy": under any-box events they cannot be otherwise; sparse
regimes arise from *task-relevant* event definitions. Two complementary evaluations follow.

## 2. Density as a controlled variable — dilution study (unchanged)

Background-resampled dilution of the 121 real timelines, ρ: 0.76 → 0.011 (up to 11.3M
frames). Equal-energy advantage of the gated family over the optimal oblivious schedule
rises monotonically 1.09 → 1.85 (best-θ ≈ 2.2), predicted within ~0.1 by the A2
binary-channel model with the *fixed aligned* channel (q_in = 0.716 > q_out = 0.400);
saturation at ~2.2× explained by the q_out activation floor. Certificate intact at every
density.

## 3. Density from a task-relevant definition — VIRAT-P (new, real data)

VIRAT-P = person-class ∧ conf ≥ 0.7 on the same committed detections, full timelines;
gate signal s_t unchanged (deployed has-box feedback) — only the event *label* changes,
isolating the density question from any controller change. ρ_ev = 0.4213 (per-video
0.01–0.80); 1,119 events; F_D heavy-tailed (median 3, mean 15.8, max 2,111, CV 6.99) —
**the paper's heavy-tail law replicates under a different event definition**. Sensitivity
at conf 0.5/0.8 monotone (not a 0.7 artifact).

**Certificate replicates — third leak-then-fix witness.** Among 473 events with D ≥ R,
the deployed `>` reuse cap leaks 9; the `>=` hard refresh restores 0/473. The worst-case
guarantee holds on the sparse, person-defined dataset exactly as the theory says.

**Alignment, not density, gates content-aware gains.** The deployed motion gate is
*anti-aligned* with person-events: q_in = 0.306 < q_out = 0.399 (it fires on vehicle motion
more than on standing people). The A2 theory then predicts it cannot beat the frontier:
TargetingGain 0.146 < ActivationCost 0.209; the threshold theorem requires q_in* ≥ 0.55 at
this q_out — an **alignment deficit of 0.25**. Measured: gated ratio < 1 across the entire
useful range (a ≈ 0.20–0.75), with wins only above a ≈ 0.75–0.89 — mirroring BMC and the
original paper's near-full-activation pattern. Model checks on VIRAT-P: activation formula
0.4879 predicted vs 0.4844 measured; per-event refined predictor 0.238 vs 0.195 measured.

## 4. The combined R2.5 message (for manuscript + response letter)

1. Sparse regimes were evaluated **two independent ways**: controlled dilution (76% → 1%)
   and a real task-relevant sparse definition (VIRAT-P, ρ = 0.42).
2. The certifiable results are **density-invariant**: frontier shape, periodic optimality,
   the R−1 certificate, and leak-then-fix all replicate at every density and definition.
3. Content-aware gains are governed by **alignment × density jointly** (the A2 theory's
   two axes): with an aligned gate, rarity amplifies the advantage (dilution: 1.09 → 1.85);
   with an anti-aligned gate, rarity does not rescue it (VIRAT-P loses everywhere useful).
   Both branches are *predicted before measured* — the strongest form of validation the
   revision offers.
4. Deployment guidance: in genuinely sparse person-surveillance, the cheap motion gate must
   be *person-aligned* (or learned) to earn anything beyond the certified oblivious
   baseline — connecting directly to the shielded-learned-gating future work.

## 5. Artifacts

Cloud/dilution: `B2_density/b2_dilution.py`, `b2_results.json`. PC/VIRAT-P (all parallel,
non-destructive): `data/processed/{frame_scores,events_durations,events_gated,tau_sweep}_viratp.*`,
`viratp_metrics.json`, `scripts/viratp_gatepass.py`, `viratp_analyze.py`;
report `B2_density/VIRAT_REDUMP_REPORT.md`. Committed 3-dataset core: byte-untouched
(2026-06-09 timestamps verified, git clean).

## 6. Manuscript changes

- Sec. VII: subsection "Event density and the value of content-awareness" — (a) the ρ_ev
  table across datasets/definitions, (b) dilution advantage curve with model overlay,
  (c) VIRAT-P as the real sparse case: F_D replication, leak-then-fix #3, the alignment-
  deficit explanation with the q_in*(q_out) threshold curve (one figure ties R2.3+R2.5).
- Setup: VIRAT-P dataset definition paragraph (person ∧ conf ≥ 0.7, full timelines,
  same detections; conf 0.5/0.8 sensitivity in one sentence).
- Discussion: replace the foreground-heavy caveat with the event-definition finding.
- Response R2.5: diagnosis → two-pronged evaluation → invariance of certified results →
  alignment×density law. No integrated `cfs.run_all` rerun needed — manuscript tables are
  built from the parallel VIRAT-P artifacts at writing time.
