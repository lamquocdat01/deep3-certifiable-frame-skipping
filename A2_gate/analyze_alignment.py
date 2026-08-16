#!/usr/bin/env python3
"""A2 (R2.3) — Correlation threshold for content-aware gating.

Binary-channel gate model:
  q_in  = P(score > theta | in-event frame)   (per-frame TPR)
  q_out = P(score > theta | out-event frame)  (per-frame FPR)
  rho_ev = in-event fraction of the timeline.

Policy pi(R, theta): OPEN iff gate fires or refresh fires.
  activation  a(q_in, q_out) = 1/R + (1 - 1/R) * [rho_ev*q_in + (1-rho_ev)*q_out]
  gated miss  P_g(q_in)      = E_D[(1 - D/R)_+ * (1 - q_in)^D]
  frontier    eps(a)         = E_D[(1 - a*D)_+]

Decomposition (Theorem A2.2):
  P_g - eps(a) = ActivationCost - TargetingGain
  TargetingGain(q_in)        = E[(1-D/R)_+ * (1 - (1-q_in)^D)]   (only q_in helps)
  ActivationCost(q_in,q_out) = eps(1/R) - eps(a)                 (what an oblivious
                               policy would gain from the same extra activation)
Gate beats the frontier iff TargetingGain > ActivationCost.
"""
import json
import numpy as np
import pandas as pd

R = 5
TAU = 0.55

fs = pd.read_parquet('frame_scores.parquet')
fs = fs[fs['valid'] == 1]
ev = pd.read_csv('events_durations_link.csv') if False else None
D_all = pd.read_csv('../a1_phase/events_durations.csv') if False else None

# durations pooled + per dataset (from the committed table)
dur = pd.read_csv('/home/claude/a1_phase/events_durations.csv')

def eps(D, a):
    return np.maximum(0.0, 1.0 - a * np.asarray(D, float)).mean()

def gated_miss(D, R, q_in):
    D = np.asarray(D, float)
    return (np.maximum(0.0, 1.0 - D / R) * (1.0 - q_in) ** D).mean()

def activation(R, rho_ev, q_in, q_out):
    return 1.0 / R + (1.0 - 1.0 / R) * (rho_ev * q_in + (1 - rho_ev) * q_out)

results = {"R": R, "tau": TAU, "datasets": {}}

for name, g in fs.groupby('dataset'):
    D = dur[dur['dataset'] == name]['duration'].values
    rho_ev = float((g['g_t'] == 1).mean())
    q_in = float((g.loc[g['g_t'] == 1, 'score'] > TAU).mean())
    q_out = float((g.loc[g['g_t'] == 0, 'score'] > TAU).mean())
    a = activation(R, rho_ev, q_in, q_out)
    Pg = gated_miss(D, R, q_in)
    e_a = eps(D, a)
    gain = gated_miss(D, R, 0.0) - Pg                # TargetingGain
    cost = eps(D, 1.0 / R) - e_a                     # ActivationCost
    # minimum q_in needed to tie the frontier at the *measured* q_out
    qs = np.linspace(0, 1, 2001)
    q_star = None
    for q in qs:
        aa = activation(R, rho_ev, q, q_out)
        if gated_miss(D, R, q) <= eps(D, aa) + 1e-12:
            q_star = float(q); break
    results["datasets"][name] = {
        "n_events": int(len(D)), "rho_ev": round(rho_ev, 4),
        "q_in": round(q_in, 4), "q_out": round(q_out, 4),
        "alignment": round(q_in - q_out, 4),
        "activation": round(a, 4),
        "gated_miss_model": round(Pg, 4), "eps_at_a": round(e_a, 4),
        "TargetingGain": round(gain, 4), "ActivationCost": round(cost, 4),
        "beats_frontier_model": bool(gain > cost),
        "q_in_star_at_measured_qout": None if q_star is None else round(q_star, 4),
        "alignment_deficit": None if q_star is None else round(q_star - q_in, 4),
    }

# pooled
D = dur['duration'].values
rho_ev = float((fs['g_t'] == 1).mean())
q_in = float((fs.loc[fs['g_t'] == 1, 'score'] > TAU).mean())
q_out = float((fs.loc[fs['g_t'] == 0, 'score'] > TAU).mean())
a = activation(R, rho_ev, q_in, q_out)
results["pooled"] = {
    "rho_ev": round(rho_ev, 4), "q_in": round(q_in, 4), "q_out": round(q_out, 4),
    "activation": round(a, 4),
    "gated_miss_model": round(gated_miss(D, R, q_in), 4),
    "eps_at_a": round(eps(D, a), 4),
    "TargetingGain": round(gated_miss(D, R, 0.0) - gated_miss(D, R, q_in), 4),
    "ActivationCost": round(eps(D, 1.0 / R) - eps(D, a), 4),
}

# threshold curve q_in*(q_out) on pooled F_D (for the paper figure)
curve = []
for q_out_v in np.linspace(0, 0.9, 19):
    found = None
    for q in np.linspace(0, 1, 1001):
        aa = activation(R, rho_ev, q, q_out_v)
        if aa >= 1.0:
            break
        if gated_miss(D, R, q) <= eps(D, aa) + 1e-12:
            found = round(float(q), 4); break
    curve.append({"q_out": round(float(q_out_v), 3), "q_in_star": found})
results["threshold_curve_pooled"] = curve

# cross-check vs the measured tau_sweep at deployed reuse (validation of the model)
ts = pd.read_csv('tau_sweep.csv')
near = ts[(ts['theta'].between(TAU - 0.01, TAU + 0.01)) & (ts['reuse'] == 'deployed')]
results["tau_sweep_at_deployed_theta"] = near[['dataset', 'a', 'gated_miss', 'eps', 'ratio']].to_dict('records')

json.dump(results, open('a2_results.json', 'w'), indent=1)
for k, v in results["datasets"].items():
    print(k, v)
print("POOLED", results["pooled"])
