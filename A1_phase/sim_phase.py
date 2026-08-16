#!/usr/bin/env python3
"""A1 (R2.2) — Non-uniform phase: exact computation + simulation.

Model: refresh at frames ≡ 0 (mod R). Event onset s, phase U = s mod R,
duration D. For D < R the event is missed iff U ∈ M_D = {1, ..., R-D};
for D >= R it is always caught (Theorem 1, phase-free).
Under phase law mu:  P(miss) = E_D[ mu(M_D) ].

Phase families studied:
  * uniform            : mu = Unif{0..R-1}                         (A1 of the paper)
  * sync-worst (rho)   : mu = (1-rho) Unif + rho * delta_{u0=1}    (events start right after a refresh)
  * sync-best  (rho)   : mu = (1-rho) Unif + rho * delta_{u0=0}    (events aligned with refresh)
  TV distance to uniform: d_TV = rho * (1 - 1/R).

Randomized-phase refresh: refresh offset Phi ~ Unif{0..R-1} drawn by the
*scheduler* (secret, independent of events). For ANY deterministic onset
sequence, the induced per-event phase is uniform => the distribution-free
formula holds again, by construction. Verified by Monte Carlo against an
adversarial fully synchronized stream.
"""
import csv, json, math, os, random
import numpy as np

rng = np.random.default_rng(7)

# Paths anchored on this file so the script runs from any cwd (was: bare
# 'events_durations.csv' / 'a1_results.json' resolved against the cwd).
HERE = os.path.dirname(os.path.abspath(__file__))
CSV_IN = os.path.join(HERE, '..', '..', 'certifiable-frame-skipping',
                      'data', 'processed', 'events_durations.csv')
JSON_OUT = os.path.join(HERE, 'a1_results.json')

# ---------- data ----------
# 2026-07-31: the processed CSV carries 10 placeholder rows (dataset=VIRAT,
# event_id=0, onset=1, duration=500) that are not events; they are excluded so
# the pooled set is the 3,713 events of the Setup and Table I. See
# verify_event_count.py and AUTHOR_FIXES_REPORT.md item A.
rows = [r for r in csv.DictReader(open(CSV_IN))
        if r['dataset'] != 'VIRAT']
D_all = np.array([int(r['duration']) for r in rows])
datasets = sorted(set(r['dataset'] for r in rows))
print(f"events={len(D_all)}  median={np.median(D_all)}  mean={D_all.mean():.1f}")

# ---------- exact quantities ----------
def miss_uniform(D, R):
    return np.maximum(0.0, 1.0 - D / R).mean()

def miss_mixture(D, R, rho, u0):
    """mu = (1-rho)Unif + rho*delta_{u0}; M_D = {1..R-D} for D<R."""
    unif_part = np.maximum(0.0, (R - D)) / R          # |M_D|/R
    point_part = ((D < R) & (1 <= u0) & (u0 <= R - D)).astype(float)
    return ((1 - rho) * unif_part + rho * point_part).mean()

def tv_mixture(R, rho):
    return rho * (1 - 1.0 / R)

R_DEPLOYED = 5
out = {"R": R_DEPLOYED, "n_events": int(len(D_all))}

# (a) rho sweep at deployed R
rho_grid = np.linspace(0, 1, 21)
base = miss_uniform(D_all, R_DEPLOYED)
sweep = []
for rho in rho_grid:
    sweep.append({
        "rho": round(float(rho), 3),
        "tv": round(tv_mixture(R_DEPLOYED, rho), 4),
        "miss_worst_sync": round(miss_mixture(D_all, R_DEPLOYED, rho, u0=1), 4),
        "miss_best_sync":  round(miss_mixture(D_all, R_DEPLOYED, rho, u0=0), 4),
        "bound_hi": round(min(1.0, base + tv_mixture(R_DEPLOYED, rho)), 4),
        "bound_lo": round(max(0.0, base - tv_mixture(R_DEPLOYED, rho)), 4),
    })
out["miss_uniform"] = round(float(base), 4)
out["rho_sweep"] = sweep

# check the perturbation bound holds everywhere
viol = [s for s in sweep if not (s["bound_lo"] - 1e-9 <= s["miss_worst_sync"] <= s["bound_hi"] + 1e-9
                                 and s["bound_lo"] - 1e-9 <= s["miss_best_sync"] <= s["bound_hi"] + 1e-9)]
out["bound_violations"] = len(viol)

# (b) fully synchronized worst case across R: F_D(R-1) vs uniform formula
Rs = list(range(2, 33))
out["R_sweep"] = [{
    "R": R,
    "miss_uniform": round(miss_uniform(D_all, R), 4),
    "miss_full_sync_worst": round(float((D_all <= R - 1).mean()), 4),  # = F_D(R-1)
} for R in Rs]

# (c) Monte Carlo: adversarial deterministic stream vs randomized-phase refresh
#     Onsets fixed at s ≡ 1 (mod R) (worst sync). Durations resampled from F_D.
# N_MC raised 2000 -> 20000 on 2026-07-31: with a single global Phi per run the
# per-run miss takes only R distinct values, so 2000 runs left a +-0.005 s.e. on
# the randomized-phase mean -- large enough to look like a mismatch with the
# formula it is supposed to confirm.
N_MC, N_EV = 20000, len(D_all)
# streamed to keep memory flat at N_MC=20000
# fixed refresh (phase 0): U = 1 always -> miss iff D <= R-1; averaged over ALL
# runs (was: row 0 only, a single 3,713-sample draw with a +-0.008 s.e.)
fixed_runs, miss_runs = [], []
for _ in range(N_MC):
    D = rng.choice(D_all, size=N_EV)
    fixed_runs.append(float((D <= R_DEPLOYED - 1).mean()))
    # randomized global phase Phi ~ Unif{0..R-1} per run: U = (1 - Phi) mod R
    U = (1 - int(rng.integers(0, R_DEPLOYED))) % R_DEPLOYED
    m = (D < R_DEPLOYED) & (1 <= U) & (U <= R_DEPLOYED - D)
    miss_runs.append(float(m.mean()))
miss_fixed = float(np.mean(fixed_runs))
miss_rand = float(np.mean(miss_runs))
out["mc"] = {
    "adversarial_fixed_refresh": round(miss_fixed, 4),
    "randomized_phase_refresh_mean": round(miss_rand, 4),
    "randomized_phase_refresh_std": round(float(np.std(miss_runs)), 4),
    "uniform_formula": round(float(base), 4),
}

# (d) latency law for D >= R under mixtures (worst-case tail check)
D_long = D_all[D_all >= R_DEPLOYED]
lat = {}
for rho in (0.0, 0.5, 1.0):
    # latency L = (R - U) mod R ; under mixture with u0=1 -> L = R-1 w.p. rho + unif part
    probs = np.full(R_DEPLOYED, (1 - rho) / R_DEPLOYED)
    probs[(R_DEPLOYED - 1) % R_DEPLOYED] += rho  # L = R-1 when U=1
    lat[str(rho)] = {"EL": round(float(sum(l * p for l, p in zip(range(R_DEPLOYED), probs))), 3),
                     "P_Lmax": round(float(probs[R_DEPLOYED - 1]), 3)}
out["latency_law_worst_sync"] = lat
out["EL_uniform"] = (R_DEPLOYED - 1) / 2

json.dump(out, open(JSON_OUT, 'w'), indent=1)
print(json.dumps(out["mc"], indent=1))
print("miss uniform:", out["miss_uniform"], "| full-sync worst:", out["R_sweep"][3]["miss_full_sync_worst"], "(R=5)")
print("bound violations:", out["bound_violations"])
