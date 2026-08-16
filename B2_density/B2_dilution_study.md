# B2 (R2.5) — Low-event-density evaluation (dilution study)

*Trace-driven on the 121 non-VIRAT timelines, diluted with background blocks resampled from
each video's own out-of-event score segments (contiguous blocks, autocorrelation preserved;
fully-in-event videos take dataset-pooled background at the boundaries). Event durations are
untouched, so the frontier ε(a) is identical across densities — only the *timeline context*
changes. Script `b2_dilution.py` → `b2_results.json`. Fast π_θ implementation verified
exactly against the reference loop (a: 0.7078 = 0.7078, miss: 0.0964 = 0.0964).*

## Result: content-awareness pays off as events become rare — as predicted

Equal-energy advantage ε(a)/miss of the gated family over the optimal oblivious schedule:

| in-event density ρ | frames | advantage @ deployed θ | best advantage over θ | A2-model prediction |
|---|---|---|---|---|
| 0.76 (native) | 0.17M | 1.09 | 1.13 | 1.16 |
| 0.48 | 0.26M | 1.37 | 1.51 | 1.44 |
| 0.26 | 0.48M | 1.60 | 1.97 | 1.66 |
| 0.11 | 1.15M | 1.73 | 2.17 | 1.81 |
| 0.055 | 2.28M | 1.78 | 2.18 | 1.87 |
| 0.011 | 11.3M | 1.85 | 2.17 | 1.91 |

Three readings:

1. **The reviewer's implicit hypothesis is confirmed and quantified.** The marginal (≈1.1×)
   advantage on foreground-heavy benchmarks grows monotonically to ≈1.9–2.2× as density
   falls to 1% — the paper's original caveat ("a deployment with genuinely rare events could
   differ") is now a measured curve instead of a disclaimer.

2. **The new theory (A2/R2.3) predicts the curve.** The binary-channel model with the
   *fixed* measured channel (q_in = 0.716, q_out = 0.400) and only ρ varying tracks the
   measured advantage within ~0.1 across two orders of magnitude of density. The mechanism:
   at fixed θ the gate's activation falls with density (0.708 → 0.486, since background
   rarely fires it) while its miss stays ≈0.10 (durations unchanged) — meanwhile the
   oblivious policy at that *reduced* energy does much worse.

3. **The advantage saturates (~2.2×), and the theory says why:** as ρ → 0 the activation
   tends to 1/R + (1−1/R)·q_out — the gate's false-fire floor. Every unit of q_out is pure
   waste on an ever-larger background, capping the gain. A cleaner gate (lower q_out) would
   raise the ceiling — the threshold curve q_in*(q_out) of Theorem A2.2 quantifies exactly
   how much. Certification is untouched throughout: the R-refresh shield keeps missD5 = 0
   at every density.

## Scope notes (for the manuscript)

- Dilution preserves F_D by construction; it changes the *context* (timeline composition),
  which is precisely the variable the reviewer asked about. It does not manufacture new
  event content — for that, VIRAT (natively ~1 event/video) is reinstated as a fourth
  dataset in the revision (its frame dump must first be regenerated over the full timeline —
  the committed dump covers only in-event frames).
- Background blocks are resampled from real out-of-event gate scores of the same video
  (or same dataset when a video has none), so gate false-fire statistics are realistic.

## What goes into the manuscript

1. New Sec. VII subsection "Event density and the value of content-awareness": the table +
   one figure (advantage vs ρ, measured curve with model-predicted curve overlaid; second
   panel: activation at fixed θ vs ρ).
2. Rewrites the Discussion limitation: foreground-heaviness is no longer an untested caveat
   — the density axis is mapped, the theory predicts it, and the marginal-at-76% /
   ~2×-at-1% picture bounds what deployments should expect.
3. Response letter R2.5: dilution sweep (this) + VIRAT reinstatement (native sparse data)
   + cross-reference to the A2 theory that explains the trend.
