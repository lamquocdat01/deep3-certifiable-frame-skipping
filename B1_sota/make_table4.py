#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Emit results/tables/table4_ablation.tex from b1_table.csv.

Added 2026-08-16 (step 3). Step 2b re-ran b1 on the cleaned 121-timeline
population but the LaTeX table had been hand-transcribed from the 131-timeline
run, so it never picked the new numbers up. This script removes the hand step:
every number in Table IV is now read from b1_table.csv, the direct output of
b1_ablation_sota.py. Run it after any b1 re-run.

    python make_table4.py
"""
import csv
import os
from decimal import Decimal, ROUND_HALF_UP

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "b1_table.csv")
DST = os.path.join(HERE, "..", "manuscript", "results", "tables",
                   "table4_ablation.tex")

TARGET = "0.4"          # the matched-activation column of Table IV
# display order in the paper -> policy key in b1_table.csv
ROWS = [
    (r"periodic (refresh only)$^{\dagger}$", "periodic",    False),
    (r"gate only",                           "gate_only",   False),
    (r"gate + refresh",                      "gate_refresh", True),
    (r"random",                              "random",      False),
    (r"Glimpse-style",                       "glimpse",     False),
    (r"Reducto-style",                       "reducto",     False),
    (r"FrameHopper-style",                   "framehopper", False),
]


def q3(x):
    """3 decimals, half-up (so 0.2285 -> 0.229, not banker's 0.228)."""
    return str(Decimal(x).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def fmt(x, bold=False):
    d = Decimal(x)
    s = "0" if d == 0 else q3(x)
    return r"\textbf{%s}" % s if bold else s


rows = {}
with open(SRC, newline="") as f:
    for r in csv.DictReader(f):
        if r["target_a"] == TARGET:
            rows[r["policy"]] = r

out = [r"\begin{tabular}{@{}lrrr@{}}", r"\toprule",
       r"Policy & miss & miss $(D{\ge}\R)$ & max gap \\", r"\midrule"]
for label, key, bold in ROWS:
    r = rows[key]
    gap = int(r["max_closed_run"])
    gap_s = r"\textbf{%d}" % gap if bold else "%d" % gap
    out.append("%s & %s & %s & %s \\\\" % (
        label, fmt(r["miss"], bold), fmt(r["miss_D5"], bold), gap_s))
out += [r"\bottomrule", r"\end{tabular}", ""]

per = rows["periodic"]
out += [r"\vspace{2pt}",
        r"{\footnotesize $^{\dagger}$A periodic policy can only realize activations on",
        r"the grid $a=1/\R$ with integer $\R$, so $a\approx0.4$ is not attainable; the",
        r"row is its nearest feasible point, $\R=%d$ ($a=%s$), where the frontier is"
        % (int(float(per["param"])), q3(per["a"])),
        r"$\varepsilon=%s$. All other rows are calibrated to $a=0.40\pm0.01$.}"
        % q3(per["eps_at_a"]),
        ""]

with open(DST, "w", newline="\n") as f:
    f.write("\n".join(out))

print("wrote", os.path.normpath(DST))
print("frontier at gate+refresh a=%s : eps=%s  (Table IV caption)"
      % (rows["gate_refresh"]["a"], q3(rows["gate_refresh"]["eps_at_a"])))
for label, key, _ in ROWS:
    r = rows[key]
    print("  %-32s miss=%s  missD5=%s  gap=%s  a=%s"
          % (label, q3(r["miss"]), q3(r["miss_D5"]), r["max_closed_run"], r["a"]))
