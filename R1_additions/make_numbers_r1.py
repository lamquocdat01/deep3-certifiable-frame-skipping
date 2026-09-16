#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Emit manuscript/results/tables/numbers_r1.tex: every number the R1 revision
prints in prose, as a LaTeX macro read straight out of the analysis JSONs.

Nothing in the R1 text is typed by hand; verify_package_R1.py re-reads the same
JSONs and checks the rendered PDF against them.
"""
from __future__ import annotations

import json
import math
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
A5 = json.loads((HERE / "A5_mdep" / "a5_results.json").read_text(encoding="utf-8"))
A6 = json.loads((HERE / "A6_relcorr" / "a6_results.json").read_text(encoding="utf-8"))
GUM = json.loads((HERE / "C3_gum" / "gum_budget_ina219.json").read_text(encoding="utf-8"))

OUT = HERE / "manuscript" / "results" / "tables" / "numbers_r1.tex"


def thousands(n):
    return "{:,}".format(int(n)).replace(",", "{,}")


M = {}

# ---- A5: m-dependence -----------------------------------------------------
M["rnEvents"] = thousands(A5["protocol"]["events"])
M["rnNvid"] = str(A5["n_videos_ge5"])
M["rnPfor"] = "%.4f" % A5["p_formula"]
M["rnPsim"] = "%.4f" % A5["p_simulated_fixed_phase"]
cf, cr, cj = A5["coverage_fixed_phase"], A5["coverage_randomized_phase"], A5["coverage_jittered_no_boundary"]
for tag, d in (("Fix", cf), ("Rand", cr), ("Jit", cj)):
    for k, name in (("1", "One"), ("2", "Two"), ("5", "Five")):
        M["rnCov%s%s" % (tag, name)] = "%.1f" % (d[k] * 100)
M["rnMStruct"] = str(A5["structural"]["m_structural_tight"])
M["rnMaxOnsetsBlock"] = str(A5["structural"]["max_onsets_in_one_block_observed"])
M["rnOnsetSep"] = str(A5["structural"]["min_onset_separation_frames"])
M["rnMEff"] = str(A5["m_eff_autocorr"])
M["rnAcOne"] = "%.2f" % A5["miss_autocorr"]["1"]
M["rnAcDurOne"] = "%.2f" % A5["duration_autocorr_log"]["1"]
lag0 = A5["mi_first_lag_indistinguishable_from_zero"]
M["rnMIlag"] = str(lag0)
M["rnMIp"] = "%.2f" % A5["mutual_information"][str(lag0)]["p_value"]
M["rnMIoneBits"] = "%.3f" % A5["mutual_information"]["1"]["mi_bits"]
M["rnBlockPermP"] = "%.3f" % A5["block_permutation_test"]["5"]["runs_p_two_sided"]
M["rnDmaxPmin"] = "%.2f" % min(v["dmax_p_upper"] for v in A5["block_permutation_test"].values())
M["rnRunsObs"] = str(A5["block_permutation_test"]["5"]["runs_observed"])
M["rnRunsNull"] = "%.0f" % A5["block_permutation_test"]["5"]["runs_null_mean"]
M["rnFleetMissed"] = thousands(A5["fleet_prop_s5"]["missed"])
M["rnFleetBudget"] = thousands(round(A5["fleet_prop_s5"]["budget_95"]))
ap = A5["activation_price"]
M["rnActFix"] = "%.2f" % ap["fixed_phase_activation"]
M["rnActRand"] = "%.2f" % ap["randomized_phase_activation"]
M["rnEfix"] = "%.1f" % ap["fixed_phase_energy_mJ"]
M["rnErand"] = "%.1f" % ap["randomized_phase_energy_mJ"]
M["rnEratio"] = "%.2f" % ap["energy_ratio"]
M["rnGapJit"] = str(ap["jittered_max_refresh_gap"])
M["rnMissRand"] = "%.3f" % A5["randomized_phase_realised_miss_rate"]["mean"]
M["rnMissJit"] = "%.3f" % A5["jittered_realised_miss_rate"]

# ---- A6: invocation-failure persistence -----------------------------------
M["rnPhat"] = "%.3f" % A6["events"]["p_hat"]
M["rnOneMinusP"] = "%.3f" % A6["rho_independent_reference_1_minus_p"]
M["rnGaps"] = thousands(A6["gaps"]["count"])
M["rnFracLenOne"] = "%.1f" % (A6["gaps"]["frac_len1_observed"] * 100)
M["rnRhoHat"] = "%.3f" % A6["rho_hat_at_lag_R"]
M["rnRhoLo"] = "%.3f" % A6["rho_hat_ci95"][0]
M["rnRhoHi"] = "%.3f" % A6["rho_hat_ci95"][1]
M["rnRhoOne"] = "%.3f" % A6["rho_by_lag"]["1"]["rho_given_fail"]
M["rnRhoGivenOk"] = "%.3f" % A6["rho_by_lag"]["5"]["rate_given_ok"]
M["rnRhoRatio"] = "%.1f" % (A6["rho_hat_at_lag_R"] / A6["rho_independent_reference_1_minus_p"])
M["rnPhysEvents"] = str(A6["events"]["n_physical_events"])
M["rnRhoInfeasible"] = "%.2f" % A6["sensitivity_at_99pct"]["rho_at_which_k_exceeds_D5"]


def _k(eta, p, rho):
    for r in A6["k_table"]:
        if abs(r["eta"] - eta) < 1e-12 and abs(r["p"] - p) < 1e-12 and abs(r["rho"] - rho) < 1e-9:
            return r["k"]
    raise KeyError((eta, p, rho))


rh = A6["rho_hat_at_lag_R"]
M["rnKninetyfiveRhohat"] = str(_k(0.05, 0.972, rh))
M["rnKninetynineIndep"] = str(_k(0.01, 0.972, round(1 - 0.972, 4)))
M["rnKninetynineRhohat"] = str(_k(0.01, 0.972, rh))
# smallest rho in the reported grid at which k grows beyond the independent value
kind = _k(0.01, 0.972, round(1 - 0.972, 4))
M["rnRhoKgrows"] = next("%.1f" % r["rho"] for r in A6["k_table"]
                        if r["eta"] == 0.01 and r["p"] == 0.972 and r["k"] > kind)
M["rnKgrown"] = next(str(r["k"]) for r in A6["k_table"]
                     if r["eta"] == 0.01 and r["p"] == 0.972 and r["k"] > kind)
M["rnKweakIndep"] = str(_k(0.01, 0.95, round(1 - 0.95, 4)))
M["rnKweakRhohat"] = str(_k(0.01, 0.95, rh))

# ---- C3: JCGM 101 intervals ----------------------------------------------
mc = GUM["monte_carlo"]
g = GUM["gum"]
M["rnEidle"] = "%.4f" % g["E_idle"]["value"]
M["rnEidleLo"] = "%.4f" % mc["E_idle"]["ci95_low"]
M["rnEidleHi"] = "%.4f" % mc["E_idle"]["ci95_high"]
M["rnEact"] = "%.2f" % g["E_active"]["value"]
M["rnEactLo"] = "%.2f" % mc["E_active"]["ci95_low"]
M["rnEactHi"] = "%.2f" % mc["E_active"]["ci95_high"]
M["rnKappa"] = "%d" % round(g["kappa"]["value"])
M["rnKappaLo"] = "%d" % round(mc["kappa"]["ci95_low"])
M["rnKappaHi"] = "%d" % round(mc["kappa"]["ci95_high"])
M["rnGumRuns"] = str(GUM["meta"]["n_runs"])
M["rnGumPerMode"] = str(GUM["meta"]["n_per_mode"])
M["rnMCdraws"] = thousands(GUM["meta"]["mc_draws"])

lines = ["% GENERATED by make_numbers_r1.py from a5_results.json, a6_results.json",
         "% and gum_budget_ina219.json. Do not edit by hand."]
for k in sorted(M):
    lines.append("\\newcommand{\\%s}{%s}" % (k, M[k]))
OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")

json.dump(M, open(HERE / "numbers_r1.json", "w"), indent=1)
print("wrote %s (%d macros)" % (OUT, len(M)))
for k in sorted(M):
    print("  \\%-24s %s" % (k, M[k]))
