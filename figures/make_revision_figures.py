#!/usr/bin/env python3
"""Revision figures fig8–fig12 for Deep3 IoT-J resubmission.
Same publication style as scripts/make_figures.py (Okabe–Ito, IEEE widths)."""
import json
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OI = {"black": "#000000", "orange": "#E69F00", "skyblue": "#56B4E9",
      "green": "#009E73", "yellow": "#F0E442", "blue": "#0072B2",
      "vermillion": "#D55E00", "purple": "#CC79A7"}
COL1, COL2 = 3.5, 7.16
plt.rcParams.update({
    "font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8,
    "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 6.5,
    "font.family": "serif", "mathtext.fontset": "dejavuserif",
    "axes.linewidth": 0.6, "lines.linewidth": 1.1, "lines.markersize": 3,
    "pdf.fonttype": 42, "ps.fonttype": 42, "savefig.dpi": 300,
    "axes.spines.top": False, "axes.spines.right": False,
})

# Paths are relative to Revision_IoTJ/ (the parent of this script's directory),
# so the script runs from any cwd. Was hardcoded /home/claude/... .
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "figures")
PROC = os.path.join(ROOT, "..", "certifiable-frame-skipping", "data", "processed")

def save(fig, name):
    for ext in ("pdf", "png"):
        fig.savefig(os.path.join(OUT, f"{name}.{ext}"), bbox_inches="tight")
    plt.close(fig)
    print(name)

a1 = json.load(open(os.path.join(ROOT, 'A1_phase', 'a1_results.json')))
a2 = json.load(open(os.path.join(ROOT, 'A2_gate', 'a2_results.json')))
b2 = json.load(open(os.path.join(ROOT, 'B2_density', 'b2_results.json')))
b1 = pd.read_csv(os.path.join(ROOT, 'B1_sota', 'b1_table.csv'))
_d = pd.read_csv(os.path.join(PROC, 'events_durations.csv'))
dur = _d[_d['dataset'] != 'VIRAT']['duration'].values.astype(float)
eps = lambda a: float(np.maximum(0, 1 - a * dur).mean())

# ── fig8: phase robustness (A1 / R2.2) ───────────────────────────────────────
fig, axes = plt.subplots(2, 1, figsize=(COL1, 3.4))
ax = axes[0]
rs = a1["rho_sweep"]
rho = [s["rho"] for s in rs]
ax.fill_between(rho, [s["bound_lo"] for s in rs], [s["bound_hi"] for s in rs],
                color="0.85", label=r"Prop.~band $\pm\delta_{\mathrm{TV}}$")
ax.plot(rho, [s["miss_worst_sync"] for s in rs], color=OI["vermillion"],
        marker="o", ms=2.5, label=r"worst sync ($u_0{=}1$)")
ax.plot(rho, [s["miss_best_sync"] for s in rs], color=OI["green"],
        marker="s", ms=2.5, label=r"best sync ($u_0{=}0$)")
ax.axhline(a1["miss_uniform"], color=OI["black"], lw=0.8, ls="--",
           label=r"uniform $\mathbb{E}[(1-D/R)_+]$")
ax.set_xlabel(r"synchronized mass $\rho$  (mixture $\mu_\rho$)")
ax.set_ylabel("miss probability")
ax.legend(frameon=False, loc="upper left", fontsize=6)
ax.set_title("(a) perturbation bound, $R=5$", loc="left")

ax = axes[1]
Rsw = a1["R_sweep"]
Rv = [s["R"] for s in Rsw]
ax.plot(Rv, [s["miss_uniform"] for s in Rsw], color=OI["blue"], marker="o",
        ms=2.5, label="uniform phase (formula)")
ax.plot(Rv, [s["miss_full_sync_worst"] for s in Rsw], color=OI["vermillion"],
        marker="^", ms=2.5, label=r"fully synchronized: $F_D(R{-}1)$")
ax.set_xlabel(r"refresh period $R$")
ax.set_ylabel("miss probability")
ax.legend(frameon=False, loc="lower right")
ax.set_title("(b) worst-case ceiling across $R$", loc="left")
fig.tight_layout(h_pad=1.2)
save(fig, "fig8_phase_robustness")

# ── fig9: alignment threshold (A2 / R2.3 + VIRAT-P) ─────────────────────────
fig, ax = plt.subplots(figsize=(COL1, 2.6))
tc = [c for c in a2["threshold_curve_pooled"] if c["q_in_star"] is not None]
qo = [c["q_out"] for c in tc]; qi = [c["q_in_star"] for c in tc]
ax.plot(qo, qi, color=OI["black"], lw=1.3, label=r"threshold $q_{\mathrm{in}}^*(q_{\mathrm{out}})$")
ax.fill_between(qo, qi, 1.0, color=OI["green"], alpha=0.10)
ax.text(0.08, 0.88, "content-aware\nwins", color=OI["green"], fontsize=7)
ax.text(0.60, 0.06, "oblivious frontier wins", color="0.35", fontsize=7)
ax.plot([0, 1], [0, 1], ls=":", color="0.6", lw=0.8)
ax.text(0.72, 0.66, r"$q_{\mathrm{in}}{=}q_{\mathrm{out}}$", color="0.5",
        fontsize=6, rotation=38)
pts = {"CDnet2014": (0.364, 0.784, OI["blue"], "o"),
       "BMC": (0.053, 0.531, OI["vermillion"], "^"),
       "LASIESTA": (0.800, 0.698, OI["green"], "s"),
       "pooled": (0.400, 0.709, OI["black"], "*"),
       "VIRAT-P": (0.399, 0.306, OI["purple"], "D")}
for name, (x, y, c, mk) in pts.items():
    ax.scatter([x], [y], color=c, marker=mk, s=26 if mk != "*" else 60,
               zorder=5, label=name)
ax.set_xlabel(r"out-of-event fire rate $q_{\mathrm{out}}$")
ax.set_ylabel(r"in-event fire rate $q_{\mathrm{in}}$")
ax.set_xlim(0, 0.92); ax.set_ylim(0, 1.0)
ax.legend(frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.01),
          ncol=3, columnspacing=0.7, handletextpad=0.3)
save(fig, "fig9_alignment_threshold")

# ── fig10: density vs advantage (B2 / R2.5) ─────────────────────────────────
fig, ax = plt.subplots(figsize=(COL1, 2.5))
ds = b2["densities"]
rho_m = [d["rho_actual"] for d in ds]
adv_dep = [d["deployed_theta"]["advantage"] for d in ds]
adv_best = [max(c["advantage"] for c in d["curve"] if c["advantage"]) for d in ds]
adv_mod = [d["model"]["advantage_pred"] for d in ds]
ax.plot(rho_m, adv_dep, color=OI["blue"], marker="o", label=r"measured, deployed $\theta$")
ax.plot(rho_m, adv_best, color=OI["skyblue"], marker="s", ls="--",
        label=r"measured, best $\theta$")
ax.plot(rho_m, adv_mod, color=OI["black"], ls=":", marker="x",
        label="channel-model prediction")
ax.scatter([0.4213], [0.576], color=OI["purple"], marker="D", s=30, zorder=6)
ax.annotate("VIRAT-P\n(anti-aligned gate)", (0.4213, 0.576), xytext=(0.10, 0.72),
            fontsize=6.5, color=OI["purple"],
            arrowprops=dict(arrowstyle="-", lw=0.6, color=OI["purple"]))
ax.axhline(1.0, color="0.6", lw=0.7, ls="-")
ax.set_xscale("log")
ax.set_xlabel(r"in-event timeline density $\rho_{\mathrm{ev}}$")
ax.set_ylabel(r"advantage $\varepsilon(a)/\mathrm{miss}_{\mathrm{gated}}$")
ax.legend(frameon=False, loc="upper right")
save(fig, "fig10_density_advantage")

# ── fig11: SOTA + certificates (B1 / R2.4) ──────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(COL2, 2.5))
style = {"periodic": (OI["blue"], "o", "periodic (certified)"),
         "random": ("0.55", "v", "random"),
         "gate_only": (OI["orange"], "^", "gate only"),
         "gate_refresh": (OI["green"], "s", "gate + refresh"),
         "glimpse": (OI["purple"], "P", "Glimpse-style"),
         "reducto": (OI["skyblue"], "X", "Reducto-style"),
         "framehopper": (OI["vermillion"], "D", "FrameHopper-style")}
ax = axes[0]
agrid = np.linspace(0.15, 1.0, 200)
ax.plot(agrid, [eps(a) for a in agrid], color=OI["black"], lw=1.4,
        label=r"frontier $\varepsilon(a)$")
for pol, (c, mk, lab) in style.items():
    d = b1[b1["policy"] == pol].sort_values("a")
    ax.plot(d["a"], d["miss"], color=c, marker=mk, ms=3.5, lw=0.8, label=lab)
ax.set_xlabel(r"activation $a$"); ax.set_ylabel("event miss rate")
ax.legend(frameon=False, ncol=2, columnspacing=0.8, handletextpad=0.3)
ax.set_title("(a) average miss at equal energy", loc="left")
ax = axes[1]
for pol, (c, mk, lab) in style.items():
    d = b1[b1["policy"] == pol].sort_values("a")
    ax.plot(d["a"], d["max_closed_run"].clip(lower=0.8), color=c, marker=mk,
            ms=3.5, lw=0.8, label=lab)
ax.axhline(4, color=OI["black"], lw=0.8, ls="--")
ax.text(0.82, 5.2, r"$R-1=4$ (certificate)", fontsize=6.5)
ax.set_yscale("log")
ax.set_xlabel(r"activation $a$")
ax.set_ylabel("max closed run (frames)")
ax.set_title("(b) structural worst case", loc="left")
fig.tight_layout(w_pad=1.5)
save(fig, "fig11_sota_certificates")

# ── fig12: kappa sensitivity of the certification price (C1 / R1.3) ─────────
fig, ax = plt.subplots(figsize=(COL1, 2.5))
Dt = np.arange(1, 31)
# All kappas below use Table III's convention (marginal active energy over
# gate-running idle) EXCEPT the 3.1 reference curve, which is the same Orin
# Nano board reported under a whole-board *total*-energy convention. Keeping
# both on one axis is the point: kappa is convention-dependent, not just
# stack-dependent.
kappas = [(3.06, "0.7",            r"$\kappa=3.1$ (same board, total-energy conv.)"),
          (5.9,  OI["skyblue"],    r"$\kappa=5.9$ (TRT fp16, YOLO26s)"),
          (9.56, OI["black"],      r"$\kappa=9.56$ (original platform)"),
          (19.0, OI["green"],      r"$\kappa=19.0$ (ORT CUDA, YOLO26s)"),
          (66.2, OI["vermillion"], r"$\kappa=66.2$ (ORT CUDA, YOLOv3u)"),
          # C2b, measured 2026-08-01: ESP32-S3 + TFLM under Table III's marginal
          # convention (C2B_REPORT §D.7). Included because the Abstract cites the
          # widened span; a curve absent from the figure would read as a
          # contradiction.
          (268.7, OI["purple"],    r"$\kappa=269$ (ESP32-S3, TFLM int8)")]
for k, c, lab in kappas:
    y = (1 + (k - 1) / Dt) / k          # E(1/D)/E(1)
    lw = 1.6 if abs(k - 9.56) < 0.1 else 1.0
    ax.plot(Dt, y, color=c, lw=lw, label=lab)
ax.annotate("Orin Nano, Table III convention:\n"
            "TRT 5.9–15.1 / ORT 19.0–66.2.\n"
            "Same board, total-energy conv.: 3.1.",
            (11, 0.30), fontsize=6.5, color="0.25")
ax.set_yscale("log")
ax.set_xlabel(r"certified duration $D_{\mathrm{target}}$ (frames)")
ax.set_ylabel(r"certification energy  $E(1/D_{\mathrm{target}})/E(1)$")
ax.legend(frameon=False, loc="lower left", fontsize=6)
save(fig, "fig12_kappa_price")
print("done")
