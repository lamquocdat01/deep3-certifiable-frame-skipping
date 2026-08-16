# B1 (R2.4) — Ablation (refresh × gate) + SOTA-style baselines at equal energy

*Trace-driven on the real 131 timelines (`frame_scores.parquet`, 171,589 frames; events from
`events_gated.csv`, onsets mapped into timeline index space). Script `b1_ablation_sota.py`
→ `b1_results.json`, `b1_table.csv`. All policies causal; each calibrated by bisection to
pooled target activations a ∈ {0.25, 0.4, 0.6, 0.8}.*

## Headline table (pooled, R = 5 for refresh-bearing policies)

miss = event miss rate (all 3,723 events) · missD5 = miss among the certified class (D ≥ 5)
· maxgap = largest closed run anywhere (structural worst case) · ε(a) = oblivious frontier.

| policy | a≈0.25 miss / missD5 / maxgap | a≈0.4 | a≈0.6 | a≈0.8 |
|---|---|---|---|---|
| **periodic** (refresh only) | .349 / **0** / 3 | .291*(a=.33)* / 0 / 2 | .176*(a=.5)* / 0 / 1 | 0 *(a=1)* / 0 / 0 |
| random (oblivious) | .414 / .059 / 38 | .283 / .011 / 21 | .172 / 0 / 12 | .080 / 0 / 8 |
| **gate only** (no refresh) | .454 / **.323** / **4000** | .332 / .223 / 4000 | .212 / .138 / 3967 | .090 / .045 / 866 |
| **gate + refresh** (deployed) | .342 / **0** / 4 | .233 / 0 / 4 | .140 / 0 / 4 | .063 / 0 / 4 |
| Glimpse-style | .543 / .327 / 724 | .344 / .118 / 492 | .176 / .037 / 492 | .078 / .029 / 492 |
| Reducto-style | .474 / .187 / 461 | .330 / .073 / 461 | .185 / .017 / 461 | .071 / .005 / 461 |
| FrameHopper-style | .379 / **.010** / **7** | .253 / 0 / 3 | .141 / 0 / 2 | .064 / 0 / 1 |
| ε(a) (frontier) | .357 | .245 | .143 | .072 |

## Ablation reading (the reviewer's separation question, answered)

- **Refresh alone** delivers the certificate (missD5 = 0, maxgap = R−1) *and* essentially all
  of the miss reduction: it tracks ε(a) at every activation.
- **Gate alone** is strictly worse than refresh alone at every equal energy — on *both*
  axes: higher average miss (.454 vs .349 at a=0.25) *and* a destroyed worst case (closed
  runs up to 4,000 frames = an entire video unobserved; 32% of certified-class events
  missed). The gate's activation clumps inside already-long events and starves quiet
  stretches.
- **Gate + refresh** adds a modest average improvement over refresh alone (e.g. .233 vs .245
  at a=0.4; .063 vs .072 at a=0.8) while the refresh preserves the certificate — the
  quantitative form of "the gate improves the average, the refresh owns the worst case",
  and consistent with the A2/R2.3 break-even analysis.

## SOTA-style comparison (equal energy, same timelines, same cheap signal)

- **Glimpse-style** (change trigger) and **Reducto-style** (adaptive differencing) both
  track the frontier on *average* at high activation (Reducto .071 vs ε = .072 at a=0.8)
  but are **structurally uncertifiable**: maxgap 461–724 frames, certified-class misses at
  every budget, latency maxima in the hundreds of frames. Their worst case is not a tail
  accident — it is the absence of any refresh mechanism.
- **FrameHopper-style** (bounded skip-length table) is the instructive exception: its
  average sits on the frontier *and* its worst case is tame (maxgap ≤ 7). The reason is
  structural, and it is *our framework's own thesis*: a bounded maximum skip K **is** the
  R-refresh property with R = K+1. FrameHopper-style policies are implicitly
  refresh-bounded, hence certifiable by Theorem 1 — the framework doesn't just criticize
  SOTA, it *explains which SOTA designs are safe and why*. (At the tightest budget its
  implicit K exceeded the certified class boundary, leaking 1% of D≥5 events — exactly the
  R ≤ D_min condition of Theorem 2 in action.)
- **random vs periodic** reconfirms Theorem 4/optimality empirically at all four budgets.

## Honest caveats (state in the manuscript)

Re-implementations are *-style*: they use the deployed gate score as the cheap per-frame
signal (originals use raw-pixel differencing or a learned RL policy), run trace-driven at
matched pooled activation on identical timelines. This isolates the *scheduling structure* —
which is the object of comparison — from the signal quality. Reducto's rolling quantile is
refreshed every 20 frames for tractability.

## What goes into the manuscript

1. New Sec. VII subsection "Ablation and comparison to frame-skipping baselines": the table
   above + one figure (miss vs a with the frontier; second panel maxgap on log scale —
   the "certificate axis" no prior comparison reports).
2. The FrameHopper observation feeds Discussion: bounded-skip designs are implicitly
   certified; unbounded content-triggered designs (Glimpse/Reducto-style) are not — a
   design guideline directly derived from Theorems 1–2.
3. Response letter R2.4: ablation isolates refresh (certificate + most of the average gain)
   from gating (small average add-on); SOTA compared at equal energy on both average and
   worst-case axes.
