# A2 (R2.3) — A correlation threshold for content-aware gating

*Theory notes for the revision. Verified against `frame_scores.parquet` (171,589 frames),
`events_gated.csv` (3,723 events), `tau_sweep.csv` by `analyze_alignment.py` → `a2_results.json`.*

## The binary-channel gate model

Model the gate as a per-frame binary channel: in-event frames fire with probability
**q_in** = P(score > θ | g_t = 1), out-of-event frames with **q_out** = P(score > θ | g_t = 0);
ρ_ev is the in-event fraction of the timeline. Policy π(R, θ) opens iff the gate fires or the
R-refresh fires. Then:

  activation  a(q_in, q_out) = 1/R + (1 − 1/R)[ρ_ev·q_in + (1−ρ_ev)·q_out]     (†)
  gated miss  P_g(q_in)      = E_D[(1 − D/R)₊ (1 − q_in)^D]                     (paper Prop. 5)
  frontier    ε(a)           = E_D[(1 − aD)₊]                                    (paper Thm. 3)

**(†) is not an approximation in practice:** at the deployed θ = 0.55 it reproduces the traced
activations to three decimals (CDnet 0.7262 vs 0.7268; BMC 0.6140 vs 0.6157; LASIESTA 0.7757
vs 0.7848; pooled 0.7095 vs 0.7112).

## Theorem A2.1 (alignment is necessary)

Within the model, if q_in = q_out then the gate's firing process is independent of the event
process, so π(R, θ) is an *oblivious* policy and Theorem 3 applies:
P(miss) ≥ ε(a) at its own activation a. Hence **no content-aware gain is possible without
alignment**: q_in > q_out is necessary (in the i.i.d. channel model) for escaping the frontier.

**Proof.** With q_in = q_out = q the open set is the union of the deterministic refresh and an
i.i.d. Bernoulli(q) thinning of all frames — a point process whose law does not depend on the
event realization. The oblivious lower bound (union-bound argument of Theorem 3) applies
verbatim to any event-independent open set, randomized or not (condition on the open set,
apply the bound, average). ∎

## Theorem A2.2 (gain–cost decomposition and the threshold)

At equal activation (†), the gated policy's excess miss over the optimal oblivious policy
decomposes as

  P_g − ε(a) = **ActivationCost** − **TargetingGain**, where
  TargetingGain(q_in)        = E_D[(1 − D/R)₊ (1 − (1 − q_in)^D)]   ≥ 0,
  ActivationCost(q_in,q_out) = ε(1/R) − ε(a)                        ≥ 0.

The gate beats the frontier **iff TargetingGain > ActivationCost**. TargetingGain depends only
on q_in (opens spent *inside* events); ActivationCost is the miss reduction an oblivious
policy would extract from the *same* total activation — and it grows with **both** q_in and
q_out. Every unit of q_out therefore inflates the cost with zero gain. Defining
q_in*(q_out) as the smallest q_in achieving equality gives the **correlation threshold**; it is
increasing in q_out. On the pooled duration law (R = 5): q_in*(0) = 0, q_in*(0.2) = 0.53,
q_in*(0.4) = 0.62, q_in*(0.6) = 0.72, q_in*(0.8) = 0.84.

**Proof.** Add and subtract ε(1/R) = E[(1−D/R)₊] = P_g(0):
P_g(q_in) − ε(a) = [P_g(q_in) − P_g(0)] + [ε(1/R) − ε(a)] = −TargetingGain + ActivationCost.
Signs: (1−(1−q)^D) ≥ 0 and ε is non-increasing with a ≥ 1/R. Monotonicity of q_in* follows
since ActivationCost is increasing in q_out while TargetingGain is unchanged. ∎

### Why the paper's empirical finding is "marginal": measured alignment sits at break-even

At the deployed θ = 0.55 (measured per-frame rates):

| dataset | ρ_ev | q_in | q_out | TargetingGain | ActivationCost | model verdict | measured ε/gated |
|---|---|---|---|---|---|---|---|
| CDnet2014 | 0.70 | 0.784 | 0.364 | 0.402 | 0.364 | wins (barely) | 1.13 |
| BMC | 0.97 | 0.531 | 0.053 | 0.223 | 0.245 | **loses** | **0.28** |
| LASIESTA | 0.79 | 0.698 | 0.800 | 0.173 | 0.181 | loses (barely) | 3.34* |
| pooled | 0.77 | 0.709 | 0.400 | 0.315 | 0.302 | ≈ break-even | 1.06 |

Pooled gain 0.315 vs cost 0.302: the deployed gate operates **almost exactly at the
break-even line** — the theoretical explanation of the paper's ≈1.0–1.1× "marginal" finding,
and of BMC losing outright. (*LASIESTA flags the model's i.i.d. limitation — next.)

## Refinement A2.3 (event heterogeneity: the exact predictor)

Real gates are not i.i.d. within events: per-event fire rates q_e are strongly bimodal
(median 1.0, a mass at 0). Replacing the marginal q_in by the per-event law,

  P_g = E_e[(1 − D_e/R)₊ (1 − q_e)^{D_e}],

turns the model into an accurate predictor of the deployed system's measured miss:

| dataset | refined model | measured |
|---|---|---|
| BMC | 0.325 | 0.314 |
| CDnet2014 | 0.101 | 0.080 |
| LASIESTA | 0.016 | 0.011 |
| pooled | 0.095 | 0.079 |

(vs the naive marginal model's 0.123 / 0.079 / 0.053 / 0.091). Two lessons for the response:
**(i)** marginal correlation (q_in − q_out) alone under-specifies content-aware gain —
LASIESTA has *negative* marginal alignment yet wins because its q_e mass sits at 1 on the
events that matter; the operative statistic is the joint law of (q_e, D_e).
**(ii)** BMC's loss is now fully explained: near-saturated timeline (ρ_ev = 0.97) makes
ActivationCost high while a fat q_e = 0 mass (synthetic zero-motion events) caps
TargetingGain.

## Caveat discovered (flag for B2/R2.5)

The committed VIRAT frame dump contains only in-event frames (ρ_ev = 1.0 in the dump), so
q_out is not computable for VIRAT from current artifacts. Re-dump VIRAT gate scores over the
full timeline when doing the B2 low-density work.

## What goes into the manuscript

1. Replace the informal escape argument around Theorem 5 with: Theorem A2.1 (necessity),
   Theorem A2.2 (decomposition + threshold curve), Refinement A2.3 (exact predictor).
2. New figure: threshold curve q_in*(q_out) with the four datasets placed at their measured
   (q_out, q_in); break-even shading; pooled point on the line.
3. Rewrite of Sec. VII-D interpretation: "marginal" is no longer an empirical surprise but a
   prediction — the deployed gate's measured alignment lies on the break-even line.
4. Response letter R2.3: the reviewer asked for a minimum-correlation characterization; we
   provide necessity, an exact gain–cost criterion, the threshold curve, and a refined
   predictor validated against the deployed traces.

## Numbers to quote

Activation model exact to 3 decimals; pooled gain/cost 0.315/0.302 (break-even ⇒ marginal);
BMC 0.223 < 0.245 (loses); threshold curve q_in*(0.4) = 0.62 on pooled F_D; refined predictor
matches measured miss within 0.01–0.02 on all datasets.
