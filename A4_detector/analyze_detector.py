#!/usr/bin/env python3
"""A4 (R1.2) — Composing the schedule certificate with detector reliability.

Model: each OPEN that lands inside a (physical) event detects it with
per-invocation recall p, independently across invocations (worst case with
arbitrarily correlated failures reported separately).

Exact composed miss under A1 (uniform phase), refresh period R:
  #refreshes inside a span of length D is floor(D/R) or floor(D/R)+1,
  P(+1) = frac(D/R).  =>
  P(miss | D) = (1-f)(1-p)^k + f(1-p)^{k+1},  k = floor(D/R), f = frac(D/R).
  p = 1 recovers the paper's (1 - D/R)_+ for D < R and 0 for D >= R.

Empirical estimate of p without raw video: detector "flicker" — short g_t=0
gaps splitting one physical event into several detected runs — is the visible
trace of per-frame false negatives. Merging runs separated by gaps <= G gives
physical events; the in-event detection rate of the merged timeline estimates
the per-frame recall p wrt those events.
"""
import json
import numpy as np
import pandas as pd

R = 5
fs = pd.read_parquet('/home/claude/a2_gate/frame_scores.parquet')
fs = fs[fs['valid'] == 1].sort_values(['dataset', 'video', 'frame'])

out = {"R": R}

# ---------- gap-length distribution (from g_t run-lengths) ----------
def runs(x):
    """(value, length) run-length encoding."""
    d = np.diff(x)
    idx = np.where(d != 0)[0]
    starts = np.r_[0, idx + 1]
    lens = np.diff(np.r_[starts, len(x)])
    return x[starts], lens

gap_lengths, in_ev_frames = [], 0
for (_, _), g in fs.groupby(['dataset', 'video']):
    vals, lens = runs(g['g_t'].values)
    inner = [(v, l) for v, l in zip(vals, lens)][1:-1]  # drop boundary runs
    gap_lengths += [l for v, l in inner if v == 0]
    in_ev_frames += int((g['g_t'] == 1).sum())
gap_lengths = np.array(gap_lengths)
out["gaps"] = {"count": int(len(gap_lengths)),
               "frac_len1": round(float((gap_lengths == 1).mean()), 4),
               "frac_len_le3": round(float((gap_lengths <= 3).mean()), 4),
               "median": float(np.median(gap_lengths))}

# ---------- estimate p by merge tolerance G ----------
def estimate_p(G):
    miss_frames, ev_frames = 0, 0
    for (_, _), g in fs.groupby(['dataset', 'video']):
        x = g['g_t'].values
        vals, lens = runs(x)
        # build merged-event mask: 1-runs, plus 0-runs of length <= G that sit between 1-runs
        mask = np.zeros(len(x), bool)
        pos = 0
        for i, (v, l) in enumerate(zip(vals, lens)):
            if v == 1:
                mask[pos:pos + l] = True
            elif l <= G and 0 < i < len(vals) - 1:
                mask[pos:pos + l] = True
            pos += l
        ev_frames += int(mask.sum())
        miss_frames += int((mask & (x == 0)).sum())
    return 1.0 - miss_frames / ev_frames

out["p_by_G"] = {G: round(estimate_p(G), 4) for G in (1, 2, 3, 5)}
p_hat = out["p_by_G"][3]
out["p_hat"] = p_hat

# ---------- composed miss over F_D ----------
dur = pd.read_csv('/home/claude/a1_phase/events_durations.csv')['duration'].values.astype(float)

def composed_miss(D, R, p):
    k = np.floor(D / R)
    f = D / R - k
    return ((1 - f) * (1 - p) ** k + f * (1 - p) ** (k + 1)).mean()

out["composed_miss"] = {str(p): round(composed_miss(dur, R, p), 4)
                        for p in (1.0, 0.99, 0.95, 0.9, round(p_hat, 3), 0.8)}
out["miss_p1_check"] = round(float(np.maximum(0, 1 - dur / R).mean()), 4)

# ---------- reliability-adjusted certification ----------
# to certify events of duration >= D_target at confidence 1-eta with recall p:
# need k invocations, (1-p)^k <= eta  =>  k = ceil(ln eta / ln(1-p));
# guaranteed k invocations inside every such event requires R <= D_target/k
# => activation >= k / D_target => energy E(k/D_target).
E_idle, E_active = 30.4, 290.8
def E(a): return E_idle + min(a, 1.0) * (E_active - E_idle)
table = []
for eta in (0.05, 0.01):
    for p in (0.99, 0.95, round(p_hat, 3)):
        k = int(np.ceil(np.log(eta) / np.log(1 - p)))
        for Dt in (5, 10, 25):
            a = min(1.0, k / Dt)
            table.append({"eta": eta, "p": p, "k": k, "D_target": Dt,
                          "activation": round(a, 3), "energy_mJ": round(E(a), 1),
                          "energy_p1_mJ": round(E(1 / Dt), 1)})
out["reliability_adjusted_certification"] = table

json.dump(out, open('/home/claude/a4_detector/a4_results.json', 'w'), indent=1)
print(json.dumps({k: v for k, v in out.items() if k != "reliability_adjusted_certification"}, indent=1))
for r in table[:8]:
    print(r)
