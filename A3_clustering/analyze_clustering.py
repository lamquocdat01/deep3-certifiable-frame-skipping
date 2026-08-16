#!/usr/bin/env python3
"""A3 (R1.1) — Event clustering: measurement + dependence-robust budgets.

Key clarification first: the paper uses A2 (independence) in exactly ONE place —
the Hoeffding concentration of Prop. 4 (missed-event budget). The mean miss
formula (Prop. 2) needs only A1, by linearity of expectation, under ARBITRARY
dependence between events. Theorem 1 needs neither.

This script:
 1. Measures within-video dependence on real onsets (events_gated.csv):
    - autocorrelation of miss indicators (onset order), pooled lags 1..10
    - dispersion index of per-video miss counts vs binomial
    - inter-onset gap statistics
 2. Reproduces the paper's per-video Hoeffding budget coverage (~92.4%).
 3. Applies two dependence-robust replacements and reports their coverage:
    (a) m-dependent Hoeffding: M <= N p + sqrt(m N/2 * ln(m/delta)),
        with m chosen from the measured autocorrelation decay.
    (b) fleet-level bound across independent videos (no within-video assumption).
Simulated policy: periodic refresh R=5, refresh at frames ≡ 0 (mod R)
(the same simulated-periodic setting in which the paper reports coverage).
"""
import json
import numpy as np
import pandas as pd

R = 5
DELTA = 0.05
rng = np.random.default_rng(11)

ev = pd.read_csv('/home/claude/a2_gate/events_gated.csv').sort_values(['dataset', 'video', 'onset'])
ev['phase'] = ev['onset'] % R
# periodic-policy miss: D < R and phase in {1..R-D}
D = ev['duration'].values
ph = ev['phase'].values
ev['miss_per'] = ((D < R) & (ph >= 1) & (ph <= R - D)).astype(int)

p_hat = float(np.maximum(0.0, 1.0 - ev['duration'].values / R).mean())  # E[(1-D/R)+]
out = {"R": R, "delta": DELTA, "p_formula": round(p_hat, 4),
       "p_simulated": round(float(ev['miss_per'].mean()), 4)}

# ---------- 1. dependence diagnostics ----------
def pooled_autocorr(ev, col, maxlag=10):
    acs = {}
    for lag in range(1, maxlag + 1):
        num, den, n = 0.0, 0.0, 0
        for _, g in ev.groupby(['dataset', 'video']):
            x = g[col].values.astype(float)
            if len(x) > lag + 1:
                x0, x1 = x[:-lag], x[lag:]
                num += ((x0 - x.mean()) * (x1 - x.mean())).sum()
                den += ((x - x.mean()) ** 2).sum()
                n += len(x0)
        acs[lag] = round(num / den, 4) if den > 0 else None
    return acs

out["miss_autocorr"] = pooled_autocorr(ev, 'miss_per')
out["duration_autocorr_log"] = None
ev['logD'] = np.log(ev['duration'].astype(float))
out["duration_autocorr_log"] = pooled_autocorr(ev, 'logD')

# dispersion index of per-video miss counts vs binomial
per_video = ev.groupby(['dataset', 'video']).agg(N=('miss_per', 'size'), M=('miss_per', 'sum'),
                                                 p=('miss_per', 'mean'))
pv = per_video[per_video['N'] >= 5]
binom_var = (pv['N'] * pv['p'] * (1 - pv['p'])).replace(0, np.nan)
# empirical local dispersion: bootstrap within-video shuffle baseline
disp_rows = []
for (ds, vid), g in ev.groupby(['dataset', 'video']):
    x = g['miss_per'].values
    if len(x) < 10 or x.sum() == 0:
        continue
    # block clumping statistic: variance of miss count over halves vs shuffled
    k = len(x) // 2
    obs = np.var([x[:k].sum(), x[k:2 * k].sum()])
    sh = np.array([np.var([s[:k].sum(), s[k:2 * k].sum()])
                   for s in (rng.permutation(x) for _ in range(200))])
    disp_rows.append(obs / (sh.mean() + 1e-12))
out["clumping_ratio_median"] = round(float(np.median(disp_rows)), 3)
out["clumping_ratio_q90"] = round(float(np.quantile(disp_rows, 0.9)), 3)

# choose m_eff = smallest lag with |autocorr| < 0.05 (measured decay)
m_eff = next((lag for lag, v in out["miss_autocorr"].items() if v is not None and abs(v) < 0.05), 10)
out["m_eff"] = int(m_eff)

# ---------- 2. per-video budget coverage ----------
def coverage(budget_fn):
    ok, tot = 0, 0
    for (ds, vid), g in ev.groupby(['dataset', 'video']):
        N, M = len(g), int(g['miss_per'].sum())
        if N < 5:
            continue
        tot += 1
        if M <= budget_fn(N):
            ok += 1
    return ok / tot, tot

# original (independent) Hoeffding budget, as in the paper
b_indep = lambda N: N * p_hat + np.sqrt(N / 2 * np.log(1 / DELTA))
cov0, nvid = coverage(b_indep)
out["coverage_independent_hoeffding"] = {"coverage": round(cov0, 4), "videos": nvid}

# (a) m-dependent Hoeffding
m = out["m_eff"]
b_mdep = lambda N: N * p_hat + np.sqrt(m * N / 2 * np.log(m / DELTA))
cov1, _ = coverage(b_mdep)
out["coverage_m_dependent"] = {"m": m, "coverage": round(cov1, 4)}

# conservative m=5 (one refresh period of separation)
b_m5 = lambda N: N * p_hat + np.sqrt(5 * N / 2 * np.log(5 / DELTA))
cov2, _ = coverage(b_m5)
out["coverage_m5"] = round(cov2, 4)

# (b) fleet-level: single global budget across independent videos
Ns = per_video['N'].values
M_tot = int(per_video['M'].sum())
mu = float((per_video['N'] * p_hat).sum())
fleet_budget = mu + np.sqrt(np.log(1 / DELTA) * float((Ns.astype(float) ** 2).sum()) / 2)
out["fleet"] = {"events": int(Ns.sum()), "missed": M_tot, "expected": round(mu, 1),
                "budget_95": round(float(fleet_budget), 1),
                "within_budget": bool(M_tot <= fleet_budget)}

json.dump(out, open('/home/claude/a3_clustering/a3_results.json', 'w'), indent=1)
print(json.dumps(out, indent=1))
