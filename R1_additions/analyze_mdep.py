#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5 (R1, reviewer R2.1) -- why m = R in the m-dependent miss budget.

Descends from A3_clustering/analyze_clustering.py (round-1 artifact). Same
protocol: videos with >= 5 events, delta = 0.05, simulated periodic policy with
R = 5, miss indicators in onset order. Differences from A3:

  * reads the 3,713-event table (A3 ran on the 3,723-row CSV that still held ten
    VIRAT placeholder rows), so p_formula moves 0.4062 -> 0.4073 as recorded in
    the submitted manuscript;
  * sweeps m over a grid instead of reporting three points;
  * adds the randomized-phase refresh configuration of Prop. 6 with re-draw
    period T = R, which is the configuration in which m <= R is a STRUCTURAL
    bound rather than an estimate (Corollary S4-prime);
  * replaces the autocorrelation-only diagnostic with two tests that do not
    assume linear dependence: a block-permutation test and lagged mutual
    information against a permutation null.

FIX2 (2026-09-16). The first version centred EVERY configuration's budget on the
fixed-phase mean miss rate, 0.4073. That is wrong for any configuration whose
own mean differs: the randomized-phase refresh with the forced boundary OPEN
misses 0.301, so a budget centred at 0.4073 carries 0.10 of pure slack and every
m "passes" -- the column measured slack, not concentration, and would have
invited exactly the objection Reviewer 2 raised about m = R. Each configuration
is now centred on its OWN mean miss rate, computed analytically per event and
cross-checked against the simulation:

    P_rand(miss | s, D) = 1{[s, s+D-1] contains no block boundary bR} (1 - D/R)_+

(an event straddling a boundary meets the forced OPEN and is caught outright; an
event inside block b is missed exactly when Phi_b misses its span, which has
probability 1 - D/R under a uniform Phi_b). The old, unmatched numbers are kept
in the JSON under a name that says not to report them.

Sources are read-only. Everything is written next to this script.
"""
from __future__ import annotations

import json
import pathlib
import numpy as np
import pandas as pd

R = 5
DELTA = 0.05
M_GRID = [1, 2, 3, 4, 5, 6, 8, 10]
MIN_EVENTS = 5
N_SIM = 2000          # Monte-Carlo replications of the randomized-phase policy
N_PERM = 2000         # block-permutation null replications
N_MI_NULL = 1000      # MI permutation-null replications
N_BOOT = 1000         # bootstrap over videos
SEED = 20260916

HERE = pathlib.Path(__file__).resolve().parent
DATA = pathlib.Path("D:/PhD Program/03.Final Submission/09.05 Certifiable worst-case"
                    "/certifiable-frame-skipping/data/processed")
EVENTS = DATA / "events_gated.csv"

# ---------------------------------------------------------------- load
ev = pd.read_csv(EVENTS).sort_values(["dataset", "video", "onset"]).reset_index(drop=True)
assert len(ev) == 3713, "expected 3,713 events, got %d" % len(ev)

D = ev["duration"].values.astype(int)
S = ev["onset"].values.astype(int)
ev["phase"] = S % R
ev["block"] = S // R
ev["miss_per"] = ((D < R) & (ev["phase"].values >= 1) & (ev["phase"].values <= R - D)).astype(int)

p_hat = float(np.maximum(0.0, 1.0 - D / R).mean())          # E[(1-D/R)_+]

out = {
    "protocol": {
        "source": str(EVENTS),
        "events": int(len(ev)),
        "R": R,
        "delta": DELTA,
        "min_events_per_video": MIN_EVENTS,
        "policy_fixed_phase": "periodic refresh, OPEN at frames = 0 (mod R); "
                              "miss iff D < R and 1 <= onset mod R <= R - D",
        "policy_randomized_phase": "Prop. 6 with re-draw period T = R: Phi_b ~ "
                                   "Uniform{0..R-1} i.i.d. per R-frame block, plus a "
                                   "forced OPEN on every block boundary",
        "policy_jittered_no_boundary": "same block re-draw but WITHOUT the forced "
                                       "boundary OPEN (activation stays exactly 1/R, "
                                       "inter-refresh gap grows to 2R-1)",
        "seed": SEED, "n_sim": N_SIM, "n_perm": N_PERM, "n_boot": N_BOOT,
        "note": "budgets are applied CONDITIONALLY on the duration sequence; only the "
                "refresh phase is random.",
    },
    "p_formula": round(p_hat, 4),
    "p_simulated_fixed_phase": round(float(ev["miss_per"].mean()), 4),
}

# ------------------------------------------------- legacy autocorrelation
def pooled_autocorr(frame, col, maxlag=10):
    acs = {}
    for lag in range(1, maxlag + 1):
        num = den = 0.0
        for _, g in frame.groupby(["dataset", "video"], sort=True):
            x = g[col].values.astype(float)
            if len(x) > lag + 1:
                m = x.mean()
                num += ((x[:-lag] - m) * (x[lag:] - m)).sum()
                den += ((x - m) ** 2).sum()
        acs[lag] = round(num / den, 4) if den > 0 else None
    return acs

ev["logD"] = np.log(D.astype(float))
out["miss_autocorr"] = pooled_autocorr(ev, "miss_per")
out["duration_autocorr_log"] = pooled_autocorr(ev, "logD")
m_eff = next((l for l, v in out["miss_autocorr"].items() if v is not None and abs(v) < 0.05), 10)
out["m_eff_autocorr"] = int(m_eff)

# -------------------------------------------------------- structural order
# onsets are starts of maximal g_t = 1 runs, so consecutive onsets in a video are
# >= 2 frames apart: an R-frame block holds at most ceil(R/2) of them.
gaps_between_onsets = []
for _, g in ev.groupby(["dataset", "video"], sort=True):
    s = np.sort(g["onset"].values)
    if len(s) > 1:
        gaps_between_onsets.append(np.diff(s))
gaps_between_onsets = np.concatenate(gaps_between_onsets)
max_onsets_per_block = int(ev.groupby(["dataset", "video", "block"]).size().max())
out["structural"] = {
    "min_onset_separation_frames": int(gaps_between_onsets.min()),
    "max_onsets_in_one_block_observed": max_onsets_per_block,
    "max_onsets_in_one_block_ceilR2": int(np.ceil(R / 2)),
    "m_structural_tight": max_onsets_per_block - 1,
    "m_structural_upper_bound": R,
    "comment": "m = (max onsets sharing one block) - 1; m <= ceil(R/2) - 1 <= R.",
}

# --------------------------------------------------------- budget helpers
def deviation(N, m):
    """The Hoeffding deviation term of Proposition S4; m = 1 is the independent
    case of Proposition 3."""
    if m > 1:
        return np.sqrt(m * N / 2 * np.log(m / DELTA))
    return np.sqrt(N / 2 * np.log(1 / DELTA))


def budget(N, m, centre=None):
    """Budget for N events. `centre` is the configuration's OWN mean miss rate;
    it defaults to the fixed-phase p_hat, which is correct only for the
    fixed-phase policy."""
    c = p_hat if centre is None else centre
    return N * c + deviation(N, m)

videos = [(k, g) for k, g in ev.groupby(["dataset", "video"], sort=True) if len(g) >= MIN_EVENTS]
Nv = np.array([len(g) for _, g in videos])
out["n_videos_ge5"] = len(videos)
out["n_events_in_those_videos"] = int(Nv.sum())

# --------------------------------------- coverage, fixed-phase periodic
Mv_fixed = np.array([int(g["miss_per"].sum()) for _, g in videos])
cov_fixed = {}
for m in M_GRID:
    cov_fixed[m] = round(float((Mv_fixed <= np.array([budget(n, m) for n in Nv])).mean()), 4)
out["coverage_fixed_phase"] = cov_fixed

# fleet bound (Prop. S5) -- no m needed
M_tot = int(ev["miss_per"].sum())
mu = float(len(ev) * p_hat)
Nv_all = ev.groupby(["dataset", "video"]).size().values.astype(float)
fleet = mu + np.sqrt(np.log(1 / DELTA) * float((Nv_all ** 2).sum()) / 2)
out["fleet_prop_s5"] = {"events": int(len(ev)), "missed": M_tot, "expected": round(mu, 1),
                        "budget_95": round(float(fleet), 1),
                        "within_budget": bool(M_tot <= fleet), "videos": int(len(Nv_all))}

# ------------------------- coverage, randomized-phase refresh (Cor. S4-prime)
def sim_randomized(videos, n_sim, forced_boundary, rng):
    """Return per-video miss counts over n_sim draws, and the pooled miss rate."""
    counts = np.zeros((n_sim, len(videos)), dtype=np.int32)
    tot_miss = np.zeros(n_sim, dtype=np.int64)
    tot_ev = 0
    for vi, (_, g) in enumerate(videos):
        s = g["onset"].values.astype(int)
        d = g["duration"].values.astype(int)
        b = s // R
        j = s % R
        nb = int((s + d - 1).max()) // R + 1        # cover the last frame of every span
        phi = rng.integers(0, R, size=(n_sim, nb))          # Phi_b i.i.d. per block
        if forced_boundary:
            # an event whose span contains a block boundary is caught deterministically
            inside = (j >= 1) & (j + d <= R)
            miss = np.zeros((n_sim, len(s)), dtype=bool)
            if inside.any():
                jj, dd, bb = j[inside], d[inside], b[inside]
                ph = phi[:, bb]                              # (n_sim, n_inside)
                miss[:, inside] = ~((ph >= jj) & (ph <= jj + dd - 1))
        else:
            miss = np.ones((n_sim, len(s)), dtype=bool)
            for e in range(len(s)):
                lo, hi = s[e], s[e] + d[e] - 1
                caught = np.zeros(n_sim, dtype=bool)
                for bb in range(lo // R, hi // R + 1):
                    f = bb * R + phi[:, bb]
                    caught |= (f >= lo) & (f <= hi)
                miss[:, e] = ~caught
        counts[:, vi] = miss.sum(axis=1)
        tot_miss += miss.sum(axis=1)
        tot_ev += len(s)
    return counts, tot_miss / tot_ev

# ---- analytic per-event miss probability of each randomized configuration ----
# These are the centres the budgets must use. Conditioned on (s, D); the only
# randomness is the block phase.
def p_miss_randomized(s, d):
    """Forced boundary OPEN: an event straddling a block boundary is caught."""
    b0 = -((-s) // R)                       # smallest multiple index with b0*R >= s
    straddles = b0 * R <= s + d - 1
    return 0.0 if straddles else max(0.0, 1.0 - d / R)


def p_miss_jittered(s, d):
    """One OPEN per block at b*R + Phi_b, no boundary OPEN. Blocks independent,
    so the miss probability is the product of per-block escape probabilities."""
    if d >= 2 * R - 1:                      # then some block lies wholly inside
        return 0.0
    lo, hi = s, s + d - 1
    p = 1.0
    for bb in range(lo // R, hi // R + 1):
        c = min(hi, bb * R + R - 1) - max(lo, bb * R) + 1
        p *= 1.0 - c / R
    return p


pv_rand, pv_jit = [], []                    # per-video mean miss (the budget centre)
for _, g in videos:
    s = g["onset"].values.astype(int)
    d = g["duration"].values.astype(int)
    pv_rand.append(float(np.mean([p_miss_randomized(a, b) for a, b in zip(s, d)])))
    pv_jit.append(float(np.mean([p_miss_jittered(a, b) for a, b in zip(s, d)])))
pv_rand = np.array(pv_rand)
pv_jit = np.array(pv_jit)
p_rand_pooled = float((pv_rand * Nv).sum() / Nv.sum())
p_jit_pooled = float((pv_jit * Nv).sum() / Nv.sum())

cnt_rand, rate_rand = sim_randomized(videos, N_SIM, True, np.random.default_rng(SEED + 1))
cnt_jit, rate_jit = sim_randomized(videos, 200, False, np.random.default_rng(SEED + 2))

# ---- cross-check: analytic centre must match the simulation ----------------
checks = {}
for tag, ana, sim in (("randomized_phase", p_rand_pooled, rate_rand),
                      ("jittered_no_boundary", p_jit_pooled, rate_jit)):
    lo, hi = float(np.quantile(sim, 0.025)), float(np.quantile(sim, 0.975))
    checks[tag] = {
        "analytic_mean": round(ana, 4),
        "simulated_mean": round(float(sim.mean()), 4),
        "simulated_ci95": [round(lo, 4), round(hi, 4)],
        "abs_gap": round(abs(ana - float(sim.mean())), 5),
        "within_sim_ci": bool(lo <= ana <= hi),
        "within_tolerance_0p005": bool(abs(ana - float(sim.mean())) <= 0.005),
    }
out["centre_cross_check"] = checks
for tag, c in checks.items():
    if not c["within_tolerance_0p005"]:
        raise SystemExit(
            "STOP: analytic budget centre for %s is %.4f but the simulation gives "
            "%.4f (gap %.5f > 0.005). Do not touch the manuscript; investigate the "
            "miss law first." % (tag, c["analytic_mean"], c["simulated_mean"], c["abs_gap"]))

# ---- coverage with each configuration centred on its OWN mean --------------
# Two centres, because they answer different questions and the difference is
# exactly what the first version confused:
#   * POOLED own centre -- one number per configuration, the way the paper's
#     budget is actually deployed. Directly comparable to the fixed-phase
#     column, which also uses one pooled number (0.4073). This is what Table S3
#     prints.
#   * PER-VIDEO own centre -- removes between-video duration heterogeneity, so
#     what is left is within-video concentration alone.
# Reporting the pooled one keeps every column of Table S3 on the same footing.
cov_rand, cov_rand_ci = {}, {}
cov_rand_pv, cov_jit, cov_jit_pv, cov_fix_pv = {}, {}, {}, {}
Mv_fixed_arr = Mv_fixed.astype(float)
pv_fixed = np.array([float(g["miss_per"].mean()) for _, g in videos])
for m in M_GRID:
    dev = np.array([deviation(n, m) for n in Nv])
    # pooled own centre (reported)
    b = Nv * p_rand_pooled + dev
    per_sim = (cnt_rand <= b).mean(axis=1)
    cov_rand[m] = round(float(per_sim.mean()), 4)
    cov_rand_ci[m] = [round(float(np.quantile(per_sim, 0.025)), 4),
                      round(float(np.quantile(per_sim, 0.975)), 4)]
    cov_jit[m] = round(float((cnt_jit <= Nv * p_jit_pooled + dev).mean(axis=1).mean()), 4)
    # per-video own centre (diagnostic)
    cov_rand_pv[m] = round(float((cnt_rand <= Nv * pv_rand + dev).mean(axis=1).mean()), 4)
    cov_jit_pv[m] = round(float((cnt_jit <= Nv * pv_jit + dev).mean(axis=1).mean()), 4)
    cov_fix_pv[m] = round(float((Mv_fixed_arr <= Nv * pv_fixed + dev).mean()), 4)
out["coverage_randomized_phase_matched_centre"] = cov_rand
out["coverage_randomized_phase_matched_centre_ci95"] = cov_rand_ci
out["coverage_jittered_no_boundary_matched_centre"] = cov_jit
out["coverage_randomized_phase_per_video_centre"] = cov_rand_pv
out["coverage_jittered_no_boundary_per_video_centre"] = cov_jit_pv
out["coverage_fixed_phase_per_video_centre"] = cov_fix_pv
out["centre_definitions"] = {
    "fixed_phase_pooled": round(p_hat, 4),
    "randomized_phase_pooled": round(p_rand_pooled, 4),
    "jittered_pooled": round(p_jit_pooled, 4),
    "note": "Table S3 uses the pooled own centre for every column, so the columns "
            "are on the same footing. The *_per_video_centre maps additionally "
            "remove between-video duration heterogeneity and therefore isolate "
            "within-video concentration.",
}

# ---- kept only as a trace of the FIX2 error; DO NOT quote these ------------
cov_rand_unmatched, cov_jit_unmatched = {}, {}
for m in M_GRID:
    b_m = np.array([budget(n, m) for n in Nv])          # fixed-phase centre
    cov_rand_unmatched[m] = round(float((cnt_rand <= b_m).mean(axis=1).mean()), 4)
    cov_jit_unmatched[m] = round(float((cnt_jit <= b_m).mean(axis=1).mean()), 4)
out["coverage_randomized_phase_UNMATCHED_centre_do_not_report"] = cov_rand_unmatched
out["coverage_jittered_no_boundary_UNMATCHED_centre_do_not_report"] = cov_jit_unmatched
out["UNMATCHED_centre_note"] = (
    "These two maps centre every budget on the fixed-phase mean %.4f even though "
    "the configurations miss %.4f and %.4f. The surplus is slack, not "
    "concentration, so the numbers are not reported anywhere. Kept for the audit "
    "trail of the 2026-09-16 FIX2." % (p_hat, p_rand_pooled, p_jit_pooled))

out["randomized_phase_realised_miss_rate"] = {
    "mean": round(float(rate_rand.mean()), 4),
    "ci95": [round(float(np.quantile(rate_rand, 0.025)), 4),
             round(float(np.quantile(rate_rand, 0.975)), 4)],
    "analytic_mean": round(p_rand_pooled, 4),
    "budget_centre_used": round(p_rand_pooled, 4),
}
out["jittered_realised_miss_rate"] = round(float(rate_jit.mean()), 4)
out["jittered_analytic_miss_rate"] = round(p_jit_pooled, 4)
out["fixed_phase_budget_centre_used"] = round(p_hat, 4)

# activation / energy price of the re-draw (analytic, deterministic)
E_IDLE_PLATFORM, E_ACTIVE_PLATFORM = 30.4, 290.8          # Sec. III constants
def E(a):
    return E_IDLE_PLATFORM + min(a, 1.0) * (E_ACTIVE_PLATFORM - E_IDLE_PLATFORM)
a_fixed = 1.0 / R
a_rand = (2 * R - 1) / R ** 2          # boundary OPEN + random OPEN, coincide w.p. 1/R
out["activation_price"] = {
    "fixed_phase_activation": round(a_fixed, 4), "fixed_phase_energy_mJ": round(E(a_fixed), 1),
    "randomized_phase_activation": round(a_rand, 4), "randomized_phase_energy_mJ": round(E(a_rand), 1),
    "extra_activation": round(a_rand - a_fixed, 4),
    "extra_activation_bound_1_over_T": round(1.0 / R, 4),
    "energy_ratio": round(E(a_rand) / E(a_fixed), 3),
    "jittered_activation": round(a_fixed, 4),
    "jittered_max_refresh_gap": 2 * R - 1,
}

# --------------------------------- block-permutation test (non-parametric)
def pooled_stats(seqs):
    """Two order-sensitive statistics pooled over videos."""
    runs = 0
    dmax = 0.0
    for x in seqs:
        if len(x):
            runs += int(1 + (np.diff(x) != 0).sum())
            dev = np.cumsum(x - p_hat)
            dmax += float(max(dev.max(), 0.0)) / np.sqrt(len(x))
    return runs, dmax

seqs = [g["miss_per"].values.astype(float) for _, g in videos]
obs_runs, obs_dmax = pooled_stats(seqs)

def block_permute(x, L, rng):
    if L <= 1:
        return rng.permutation(x)
    nb = int(np.ceil(len(x) / L))
    blocks = [x[i * L:(i + 1) * L] for i in range(nb)]
    order = rng.permutation(nb)
    return np.concatenate([blocks[i] for i in order])

perm_test = {}
rng_p = np.random.default_rng(SEED + 3)
for L in (1, 2, 3, 5):
    nr, nd = np.empty(N_PERM), np.empty(N_PERM)
    for i in range(N_PERM):
        pseqs = [block_permute(x, L, rng_p) for x in seqs]
        nr[i], nd[i] = pooled_stats(pseqs)
    perm_test[L] = {
        "block_length": L,
        "runs_observed": obs_runs,
        "runs_null_mean": round(float(nr.mean()), 1),
        "runs_p_two_sided": round(float(2 * min((nr <= obs_runs).mean(),
                                                (nr >= obs_runs).mean())), 4),
        "dmax_observed": round(obs_dmax, 3),
        "dmax_null_mean": round(float(nd.mean()), 3),
        "dmax_p_upper": round(float((nd >= obs_dmax).mean()), 4),
    }
out["block_permutation_test"] = perm_test

# --------------------------------------- lagged mutual information (bits)
def mi_bits(a, b):
    n = len(a)
    if n == 0:
        return 0.0
    mi = 0.0
    for u in (0, 1):
        for v in (0, 1):
            pxy = float(((a == u) & (b == v)).sum()) / n
            px = float((a == u).sum()) / n
            py = float((b == v).sum()) / n
            if pxy > 0 and px > 0 and py > 0:
                mi += pxy * np.log2(pxy / (px * py))
    return float(mi)

def pooled_pairs(seqs, lag):
    A, B = [], []
    for x in seqs:
        if len(x) > lag:
            A.append(x[:-lag])
            B.append(x[lag:])
    return (np.concatenate(A), np.concatenate(B)) if A else (np.array([]), np.array([]))

rng_mi = np.random.default_rng(SEED + 4)
mi_out = {}
idx_all = np.arange(len(seqs))
for lag in range(1, 11):
    a, b = pooled_pairs(seqs, lag)
    obs = mi_bits(a, b)
    null = np.empty(N_MI_NULL)
    for i in range(N_MI_NULL):
        sh = [rng_mi.permutation(x) for x in seqs]
        aa, bb = pooled_pairs(sh, lag)
        null[i] = mi_bits(aa, bb)
    boot = np.empty(N_BOOT)
    for i in range(N_BOOT):
        pick = rng_mi.choice(idx_all, size=len(idx_all), replace=True)
        aa, bb = pooled_pairs([seqs[k] for k in pick], lag)
        boot[i] = mi_bits(aa, bb)
    mi_out[lag] = {
        "mi_bits": round(obs, 6),
        "boot_ci95": [round(float(np.quantile(boot, 0.025)), 6),
                      round(float(np.quantile(boot, 0.975)), 6)],
        "null_mean_bits": round(float(null.mean()), 6),
        "null_q95_bits": round(float(np.quantile(null, 0.95)), 6),
        "p_value": round(float((null >= obs).mean()), 4),
        "distinguishable_from_zero": bool((null >= obs).mean() < 0.05),
    }
out["mutual_information"] = mi_out
out["mi_first_lag_indistinguishable_from_zero"] = next(
    (l for l in range(1, 11) if not mi_out[l]["distinguishable_from_zero"]), None)

# ------------------------------------------------------------------ write
(HERE / "a5_results.json").write_text(json.dumps(out, indent=1), encoding="utf-8")

TAB = HERE.parent / "manuscript" / "results" / "tables"
TAB.mkdir(parents=True, exist_ok=True)
lines = [
    "% GENERATED by A5_mdep/analyze_mdep.py -- do not edit by hand.",
    r"\begin{tabular}{@{}rrrrr@{}}",
    r"\toprule",
    r"$m$ & deviation$/N$ at $N{=}50$ & fixed phase & randomized phase & MI at lag $m$ [bits] \\",
    r"\midrule",
]
for m in M_GRID:
    mi = out["mutual_information"].get(m, {})
    mis = ("%.4f" % mi["mi_bits"]) if mi else "---"
    if mi and not mi["distinguishable_from_zero"]:
        mis += r"$^{\dagger}$"
    star = r"$^{\ast}$" if m == R else ""
    # the deviation term is centre-independent, so it is the honest thing to
    # print now that each column carries its own centre
    lines.append("%d%s & %.3f & %.1f\\%% & %.1f\\%% & %s \\\\"
                 % (m, star, deviation(50, m) / 50, cov_fixed[m] * 100,
                    cov_rand[m] * 100, mis))
lines += [
    r"\bottomrule",
    r"\end{tabular}",
    "",
    r"\vspace{2pt}",
    r"{\footnotesize Budgets are centred on each configuration's own mean miss rate",
    r"($\rnPfor$ fixed phase, $\rnMissRandFormula$ randomized phase), so every column",
    r"measures concentration, not slack.}",
]
(TAB / "tableS3_mdep_sensitivity.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

# ------------------------------------------------------------------ report
print(json.dumps({k: v for k, v in out.items()
                  if k not in ("mutual_information", "block_permutation_test",
                               "duration_autocorr_log")}, indent=1))
print("\n-- mutual information (pooled, bits) --")
for l, v in mi_out.items():
    print("  lag %2d: MI=%.5f boot95=%s null_q95=%.5f p=%.4f  %s"
          % (l, v["mi_bits"], v["boot_ci95"], v["null_q95_bits"], v["p_value"],
             "DEPENDENT" if v["distinguishable_from_zero"] else "indistinguishable from 0"))
print("\n-- block-permutation test --")
for L, v in perm_test.items():
    print("  block L=%d: runs %d vs null %.1f (p=%.4f), Dmax %.3f vs %.3f (p=%.4f)"
          % (L, v["runs_observed"], v["runs_null_mean"], v["runs_p_two_sided"],
             v["dmax_observed"], v["dmax_null_mean"], v["dmax_p_upper"]))
print("\nwrote %s" % (HERE / "a5_results.json"))
print("wrote %s" % (TAB / "tableS3_mdep_sensitivity.tex"))
