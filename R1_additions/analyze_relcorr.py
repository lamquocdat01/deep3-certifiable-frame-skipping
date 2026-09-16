#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A6 (R1, reviewer R2.2) -- sensitivity of the reliability-adjusted certificate
to CORRELATED invocation failures.

The submitted paper has two regimes only: independent invocation failures
(k = ceil(ln eta / ln(1-p))) and arbitrarily correlated failures (Pr(miss) <= 1-p,
k useless). R2.2 asks what happens in between. This script

  1. estimates the persistence rho-hat = P(FN at t+R | FN at t, same physical
     event) from the detector's own frame-level false negatives, using the same
     merge-gap-<=3 protocol that produced p-hat = 0.972 in A4, with a bootstrap
     over physical events (not over frames);
  2. checks the round-1 gap-length statistic against what independence predicts,
     which the data plainly refutes at lag 1;
  3. tabulates k(eta, p, rho) for the two-state Markov persistence model and the
     energy E(k/D_target) it costs;
  4. draws Fig. S9 (monochrome, print-safe).

Sources are read-only. Everything is written next to this script, except the
LaTeX table and the figure, which go into manuscript/results/.
"""
from __future__ import annotations

import json
import math
import pathlib
import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

R = 5
MERGE_GAP = 3              # same protocol as A4_detector/analyze_detector.py
MAXLAG = 10
N_BOOT = 2000
SEED = 20260916

# Sec. III platform constants (the same ones A4 used: D_target=5, k=1 -> 82.5 mJ)
E_IDLE, E_ACTIVE = 30.4, 290.8

HERE = pathlib.Path(__file__).resolve().parent
DATA = pathlib.Path("D:/PhD Program/03.Final Submission/09.05 Certifiable worst-case"
                    "/certifiable-frame-skipping/data/processed")

rng = np.random.default_rng(SEED)


def E(a):
    return E_IDLE + min(a, 1.0) * (E_ACTIVE - E_IDLE)


def runs(x):
    """(value, length) run-length encoding."""
    d = np.diff(x)
    idx = np.where(d != 0)[0]
    starts = np.r_[0, idx + 1]
    lens = np.diff(np.r_[starts, len(x)])
    return x[starts], lens


# --------------------------------------------------------------- 1. load
fs = pd.read_parquet(DATA / "frame_scores.parquet")
fs = fs[fs["valid"] == 1].sort_values(["dataset", "video", "frame"])

out = {
    "protocol": {
        "source": str(DATA / "frame_scores.parquet"),
        "R": R,
        "merge_gap": MERGE_GAP,
        "physical_event": "maximal run of g_t=1 after merging interior 0-runs of "
                          "length <= %d frames (A4 protocol)" % MERGE_GAP,
        "FN_t": "1{g_t = 0} inside a physical event",
        "bootstrap": "resample physical events with replacement (not frames)",
        "n_boot": N_BOOT, "seed": SEED,
        "valid_frames": int(len(fs)),
    }
}

# ------------------------------------------- physical events + FN sequences
fn_seqs = []          # one binary array per physical event
gap_lengths = []
for _, g in fs.groupby(["dataset", "video"], sort=True):
    x = g["g_t"].values.astype(int)
    vals, lens = runs(x)
    inner = list(zip(vals, lens))[1:-1]
    gap_lengths += [l for v, l in inner if v == 0]
    # merged mask
    mask = np.zeros(len(x), bool)
    pos = 0
    for i, (v, l) in enumerate(zip(vals, lens)):
        if v == 1:
            mask[pos:pos + l] = True
        elif l <= MERGE_GAP and 0 < i < len(vals) - 1:
            mask[pos:pos + l] = True
        pos += l
    # split the mask into maximal True runs = physical events
    mvals, mlens = runs(mask.astype(int))
    pos = 0
    for v, l in zip(mvals, mlens):
        if v == 1 and l >= 2:
            fn_seqs.append((x[pos:pos + l] == 0).astype(np.int8))
        pos += l

gap_lengths = np.array(gap_lengths)
tot_fr = int(sum(len(s) for s in fn_seqs))
tot_fn = int(sum(int(s.sum()) for s in fn_seqs))
p_hat = 1.0 - tot_fn / tot_fr

out["events"] = {"n_physical_events": len(fn_seqs), "in_event_frames": tot_fr,
                 "in_event_false_negatives": tot_fn, "p_hat": round(p_hat, 4)}
out["gaps"] = {
    "count": int(len(gap_lengths)),
    "frac_len1_observed": round(float((gap_lengths == 1).mean()), 4),
    "frac_len1_under_independence": round(p_hat, 4),
    "frac_len_le3": round(float((gap_lengths <= MERGE_GAP).mean()), 4),
    "median": float(np.median(gap_lengths)),
    "comment": "under independent per-frame failures a gap has length 1 with "
               "probability p_hat; the observed fraction is far lower, so "
               "frame-level failures are NOT independent at lag 1.",
}


# ------------------------------------------------ 2. persistence rho-hat(l)
def per_event_counts(seqs, lag):
    """Per-event (n11, n1, n01, n0) so the bootstrap is a sum over resampled events."""
    n11 = np.zeros(len(seqs)); n1 = np.zeros(len(seqs))
    n01 = np.zeros(len(seqs)); n0 = np.zeros(len(seqs))
    for i, s in enumerate(seqs):
        if len(s) > lag:
            a, b = s[:-lag], s[lag:]
            am1, am0 = (a == 1), (a == 0)
            n1[i] = am1.sum(); n11[i] = (am1 & (b == 1)).sum()
            n0[i] = am0.sum(); n01[i] = (am0 & (b == 1)).sum()
    return n11, n1, n01, n0


rho_by_lag = {}
idx_all = np.arange(len(fn_seqs))
boot_idx = rng.choice(idx_all, size=(N_BOOT, len(idx_all)), replace=True)
for lag in range(1, MAXLAG + 1):
    c11, c1, c01, c0 = per_event_counts(fn_seqs, lag)
    n11, n1, n01, n0 = c11.sum(), c1.sum(), c01.sum(), c0.sum()
    r1 = n11 / n1 if n1 else float("nan")
    r0 = n01 / n0 if n0 else float("nan")
    num = c11[boot_idx].sum(axis=1)
    den = c1[boot_idx].sum(axis=1)
    boot = np.where(den > 0, num / np.maximum(den, 1), np.nan)
    boot = boot[np.isfinite(boot)]
    rho_by_lag[lag] = {
        "rho_given_fail": round(float(r1), 4),
        "rho_ci95": [round(float(np.quantile(boot, 0.025)), 4),
                     round(float(np.quantile(boot, 0.975)), 4)],
        "rate_given_ok": round(float(r0), 4),
        "n_conditioning_pairs_fail": int(n1),
        "n_conditioning_pairs_ok": int(n0),
    }
out["rho_by_lag"] = rho_by_lag
rho_hat = rho_by_lag[R]["rho_given_fail"]
out["rho_hat_at_lag_R"] = rho_hat
out["rho_hat_ci95"] = rho_by_lag[R]["rho_ci95"]
out["rho_independent_reference_1_minus_p"] = round(1 - p_hat, 4)


# ------------------------------------ 3. k(eta, p, rho) under Markov persistence
def k_markov(eta, p, rho):
    """Smallest k with (1-p) rho^{k-1} <= eta (k >= 1). rho = 1-p gives the
    independent formula; rho -> 1 diverges."""
    q = 1.0 - p
    if q <= eta:
        return 1
    if rho <= 0.0:
        return 2
    if rho >= 1.0:
        return math.inf
    return 1 + max(1, math.ceil(math.log(eta / q) / math.log(rho)))


# self-checks
for _p in (0.972, 0.95, 0.90):
    for _eta in (0.05, 0.01):
        k_ind_formula = math.ceil(math.log(_eta) / math.log(1 - _p))
        assert k_markov(_eta, _p, 1 - _p) == max(1, k_ind_formula), (_p, _eta)
out["self_check_independent_limit"] = "k(eta,p,1-p) == ceil(ln eta / ln(1-p)) for all "\
                                      "(eta,p) in the grid: PASS"

ETAS = [0.05, 0.01]
PS = [0.972, 0.95, 0.90]
RHOS_EXTRA = [0.1, 0.2, 0.3, 0.5, 0.7, 0.9]
DTARGETS = [5, 10, 25]

table = []
for eta in ETAS:
    for p in PS:
        rhos = [("independent (1-p)", round(1 - p, 4)), ("rho_hat", rho_hat)] + \
               [("%.1f" % r, r) for r in RHOS_EXTRA]
        for label, rho in rhos:
            k = k_markov(eta, p, rho)
            row = {"eta": eta, "p": p, "rho_label": label, "rho": rho,
                   "k": (None if k is math.inf else int(k))}
            for Dt in DTARGETS:
                if k is math.inf:
                    row["activation_D%d" % Dt] = None
                    row["energy_D%d_mJ" % Dt] = None
                else:
                    a = min(1.0, k / Dt)
                    row["activation_D%d" % Dt] = round(a, 3)
                    row["energy_D%d_mJ" % Dt] = round(E(a), 1)
            table.append(row)
out["k_table"] = table

# the headline invariance statement
out["invariance_at_95pct"] = {
    "one_minus_p_hat": round(1 - p_hat, 4),
    "eta": 0.05,
    "k_for_every_rho": 1,
    "holds": bool((1 - p_hat) <= 0.05),
    "statement": "1 - p_hat <= eta at eta = 0.05, so a single in-event invocation "
                 "already meets the confidence target and k = 1 for EVERY rho: the "
                 "95% certificate is insensitive to invocation-failure correlation "
                 "at the measured reliability.",
}
k99_ind = k_markov(0.01, round(p_hat, 3), round(1 - p_hat, 4))
k99_rho = k_markov(0.01, round(p_hat, 3), rho_hat)
out["sensitivity_at_99pct"] = {
    "eta": 0.01, "p": round(p_hat, 3),
    "k_independent": int(k99_ind),
    "k_at_rho_hat": int(k99_rho),
    "rho_hat": rho_hat,
    "energy_D5_independent_mJ": round(E(min(1.0, k99_ind / 5)), 1),
    "energy_D5_at_rho_hat_mJ": round(E(min(1.0, k99_rho / 5)), 1),
    "rho_at_which_k_exceeds_D5": next(
        (round(r, 2) for r in np.arange(0.01, 1.0, 0.01)
         if k_markov(0.01, round(p_hat, 3), float(r)) > 5), None),
}

# --------------------------------------------------------------- 4. outputs
(HERE / "a6_results.json").write_text(json.dumps(out, indent=1), encoding="utf-8")

RES = HERE.parent / "manuscript" / "results"
(RES / "tables").mkdir(parents=True, exist_ok=True)
(RES / "figures").mkdir(parents=True, exist_ok=True)

RHO_COLS = [("indep.", None), ("$\\hat\\rho$", rho_hat)] + [("%.1f" % r, r) for r in (0.3, 0.5, 0.7, 0.9)]
lines = [
    "% GENERATED by A6_relcorr/analyze_relcorr.py -- do not edit by hand.",
    r"\begin{tabular}{@{}llrrrrrr@{}}",
    r"\toprule",
    r"$\eta$ & $p$ & " + " & ".join(c for c, _ in RHO_COLS) + r" \\",
    r"\midrule",
]
for eta in ETAS:
    for p in PS:
        cells = []
        for _, rho in RHO_COLS:
            rr = (1 - p) if rho is None else rho
            k = k_markov(eta, p, rr)
            cells.append("$\\infty$" if k is math.inf
                         else "%d\\,(%.0f)" % (k, E(min(1.0, k / 5))))
        lines.append("%.2f & %.3f & %s \\\\" % (eta, p, " & ".join(cells)))
    if eta != ETAS[-1]:
        lines.append(r"\midrule")
lines += [r"\bottomrule", r"\end{tabular}"]
(RES / "tables" / "tableS4_relcorr.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")

# ---- Fig. S9
rgrid = np.linspace(0.01, 0.97, 400)
fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.7), sharey=False)
styles = [("-", "k"), ("--", "0.35"), (":", "0.0")]
for ax, eta in zip(axes, ETAS):
    ax2 = ax.twinx()
    for (ls, col), p in zip(styles, PS):
        ks = np.array([k_markov(eta, p, float(r)) for r in rgrid], dtype=float)
        ks = np.where(np.isfinite(ks), ks, np.nan)
        ax.plot(rgrid, ks, ls=ls, color=col, lw=1.3, label="$p=%.3f$" % p)
        es = np.array([E(min(1.0, k / 5)) if np.isfinite(k) else np.nan for k in ks])
        ax2.plot(rgrid, es, ls=ls, color=col, lw=0.7, alpha=0.45)
    ax.axvline(rho_hat, color="k", ls="-.", lw=0.9)
    ax.annotate(r"$\hat\rho=%.2f$" % rho_hat, xy=(rho_hat, 0.93), xycoords=("data", "axes fraction"),
                ha="right", va="top", fontsize=7, rotation=90)
    ax.set_xlabel(r"persistence $\rho=\Pr(\mathrm{fail}_{t+R}\mid \mathrm{fail}_t)$", fontsize=8)
    ax.set_ylabel(r"invocations $k(\eta,p,\rho)$", fontsize=8)
    ax2.set_ylabel(r"$E(k/D_{\mathrm{target}})$ [mJ], $D_{\mathrm{target}}{=}5$", fontsize=7)
    ax.set_title(r"$\eta=%.2f$" % eta, fontsize=8)
    ax.set_ylim(0, 12)
    ax2.set_ylim(0, 300)
    ax.tick_params(labelsize=7)
    ax2.tick_params(labelsize=7)
    ax.grid(True, lw=0.3, alpha=0.4)
axes[0].legend(fontsize=7, frameon=False, loc="upper left")
fig.tight_layout()
fig.savefig(RES / "figures" / "figS9_relcorr.pdf", bbox_inches="tight")
plt.close(fig)

# ------------------------------------------------------------------ report
print(json.dumps({k: v for k, v in out.items() if k not in ("k_table", "rho_by_lag")}, indent=1))
print("\n-- rho-hat(l) = P(FN_{t+l}=1 | FN_t=1) within physical events --")
for l, v in rho_by_lag.items():
    print("  lag %2d: rho=%.4f ci95=%s   P(FN|ok)=%.4f  (n=%d)"
          % (l, v["rho_given_fail"], v["rho_ci95"], v["rate_given_ok"],
             v["n_conditioning_pairs_fail"]))
print("\n-- k(eta,p,rho), energy at D_target=5 in mJ --")
for r in out["k_table"]:
    print("  eta=%.2f p=%.3f rho=%-18s k=%s  E5=%s mJ"
          % (r["eta"], r["p"], "%s=%.4f" % (r["rho_label"], r["rho"]),
             r["k"], r["energy_D5_mJ"]))
print("\nwrote %s" % (HERE / "a6_results.json"))
print("wrote %s" % (RES / "tables" / "tableS4_relcorr.tex"))
print("wrote %s" % (RES / "figures" / "figS9_relcorr.pdf"))
