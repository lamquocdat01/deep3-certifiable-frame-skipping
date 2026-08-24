#!/usr/bin/env python3
"""c2b_ina219_analyze.py — turn a firmware DUMP of the INA219 campaign into the
C2b energy numbers.

Input is the raw `DUMP` CSV (the header line plus one row per run, with the
leading "DUMP," stripped). Output is a printed report plus a JSON blob.

    python c2b_ina219_analyze.py --csv ../../C2_mcu/c2b_meter_logs/ina219_campaign_20260731.csv \
        --json ../../C2_mcu/c2b_meter_logs/ina219_campaign_20260731_analysis.json

This is the INA219 path. It deliberately does NOT touch log_um24c.py, which
belongs to the USB-meter path and stays valid as an independent cross-check.

Nothing here invents a number: every quantity is derived from the CSV, and any
threshold breach is printed as a FAIL rather than silently accepted.

Stdlib only (no numpy) so it runs in the same interpreter as c2b_probe.py.
"""

import argparse
import csv
import json
import math
import statistics
import sys

# Modes with replicates, in report order, then the single-run sweep points.
REPLICATED = ["idle-skip", "gate", "active"]
SWEEP = ["ctrl-k10", "ctrl-k5", "ctrl-k2"]
# The E(a) fit deliberately excludes `gate`: the gate runs the controller with
# inference disabled, so it is not a point on the same W(a) line as the modes
# that do infer. Its purpose is to price the gate itself, in the marginal
# convention below.
FIT_MODES = ["idle-skip", "ctrl-k10", "ctrl-k5", "ctrl-k2", "active"]

# Per-run acceptance thresholds (INA219 measurement protocol, Part A).
SAMPLE_TOL = 0.05        # power_samples vs expected
PVI_TOL = 0.02           # mean_mw vs mean_v * mean_ma
V_RANGE = (4.7, 5.3)
MW_RANGE = (200.0, 2500.0)
DISCARD_MS = 30000       # CFS_MEAS_DISCARD_MS
SAMPLE_MS = 140          # CFS_MEAS_SAMPLE_MS
RESOLVE_SIGMA = 5.0      # B.2: margin must clear 5 sigma to use the marginal convention
VDROP_ALARM = 0.05       # B.4: >5% change under the voltage correction => stop


# --------------------------------------------------------------------------
# loading and per-run validation
# --------------------------------------------------------------------------

def load(path):
    rows = []
    # utf-8-sig, not utf-8: PowerShell's Set-Content -Encoding utf8 writes a BOM,
    # which would otherwise turn the first header field into "﻿run_id" and
    # silently drop every row.
    with open(path, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if not r.get("run_id"):
                continue
            rows.append({
                "run_id": int(r["run_id"]),
                "mode": r["mode"].strip(),
                "frames": int(r["frames"]),
                "opens": int(r["opens"]),
                "infer_count": int(r["infer_count"]),
                "elapsed_ms": int(r["elapsed_ms"]),
                "fps": float(r["fps"]),
                "open_frac": float(r["open_frac"]),
                "max_closed_run": int(r["max_closed_run"]),
                "mean_mw": float(r["mean_mw"]),
                "mean_v": float(r["mean_v"]),
                "mean_ma": float(r["mean_ma"]),
                "power_samples": int(r["power_samples"]),
            })
    return rows


def expected_samples(elapsed_ms):
    if elapsed_ms <= DISCARD_MS:
        return 0
    return (elapsed_ms - DISCARD_MS) // SAMPLE_MS


def validate(rows):
    """Re-run the per-run acceptance checks over the whole campaign."""
    out = []
    for r in rows:
        checks = []
        exp = expected_samples(r["elapsed_ms"])
        dev = abs(r["power_samples"] - exp) / exp if exp else 1.0
        checks.append(("power_samples", dev <= SAMPLE_TOL,
                       "%d vs %d expected (%.2f%%)" % (r["power_samples"], exp,
                                                       dev * 100)))
        checks.append(("mean_ma > 0", r["mean_ma"] > 0,
                       "%.2f mA" % r["mean_ma"]))
        pvi = r["mean_v"] * r["mean_ma"]
        pdev = abs(r["mean_mw"] - pvi) / r["mean_mw"] if r["mean_mw"] else 1.0
        checks.append(("P vs VxI", pdev <= PVI_TOL,
                       "%.2f vs %.2f mW (%.2f%%)" % (r["mean_mw"], pvi,
                                                     pdev * 100)))
        checks.append(("mean_v range", V_RANGE[0] <= r["mean_v"] <= V_RANGE[1],
                       "%.4f V" % r["mean_v"]))
        checks.append(("mean_mw range", MW_RANGE[0] <= r["mean_mw"] <= MW_RANGE[1],
                       "%.2f mW" % r["mean_mw"]))
        out.append((r, checks, all(ok for _, ok, _ in checks)))
    return out


# --------------------------------------------------------------------------
# B.1 per-mode statistics
# --------------------------------------------------------------------------

def sem(values):
    """Standard error of the mean, sigma/sqrt(n) with the sample sigma.

    None for n < 2: a single run carries no internal estimate of its own
    spread, and inventing one would be worse than admitting the gap.
    """
    n = len(values)
    if n < 2:
        return None
    return statistics.stdev(values) / math.sqrt(n)


def per_mode(rows):
    stats = {}
    for mode in REPLICATED + SWEEP:
        sel = [r for r in rows if r["mode"] == mode]
        if not sel:
            continue
        entry = {"n": len(sel), "run_ids": [r["run_id"] for r in sel]}
        for key in ("mean_mw", "mean_v", "mean_ma", "fps"):
            vals = [r[key] for r in sel]
            entry[key] = statistics.fmean(vals)
            entry[key + "_sem"] = sem(vals)
        avals = [r["opens"] / r["frames"] if r["frames"] else 0.0 for r in sel]
        entry["a"] = statistics.fmean(avals)
        entry["a_sem"] = sem(avals)
        stats[mode] = entry
    return stats


def s_of(stats, mode, key):
    v = stats[mode].get(key + "_sem")
    return 0.0 if v is None else v


# --------------------------------------------------------------------------
# B.2 / B.3 energy conventions
# --------------------------------------------------------------------------

def conventions(stats, power_key="mean_mw", power_sem_key=None):
    """Both conventions with propagated errors.

    Marginal:
        E_idle   = [P(gate)   - P(idle-skip)] / fps(gate)      mJ/frame
        E_active = [P(active) - P(gate)     ] / fps(active)    mJ/frame
    Total:
        E_*_tot  = P(mode) / fps(mode)

    Units: the prompt writes these with a "* 1000" because it states P in watts.
    Here P is `mean_mw`, already in mW = mJ/s, so mW / (frames/s) is mJ/frame
    directly and the factor would be a 1000x error. kappa, being a ratio, is
    unaffected either way.

    The two marginal energies share P(gate) with opposite signs, so they are
    negatively correlated. Ignoring that would understate sigma(kappa), so the
    covariance term is carried explicitly:
        (s_k/k)^2 = (s_A/A)^2 + (s_I/I)^2 + (s_fa/fa)^2 + (s_fi/fi)^2
                    - 2*Cov(A,I)/(A*I),      Cov(A,I) = -s_Pgate^2
    """
    psem = power_sem_key or (power_key + "_sem")

    def P(m):
        return stats[m][power_key]

    def sP(m):
        v = stats[m].get(psem)
        return 0.0 if v is None else v

    Pi, Pg, Pa = P("idle-skip"), P("gate"), P("active")
    sPi, sPg, sPa = sP("idle-skip"), sP("gate"), sP("active")
    fi, fg, fa = (stats["idle-skip"]["fps"], stats["gate"]["fps"],
                  stats["active"]["fps"])
    sfi, sfg, sfa = (s_of(stats, "idle-skip", "fps"), s_of(stats, "gate", "fps"),
                     s_of(stats, "active", "fps"))

    # --- B.2 resolution criterion, fixed in advance --------------------------
    margin = Pg - Pi
    s_comb = math.hypot(sPg, sPi)
    ratio = (margin / s_comb) if s_comb > 0 else float("inf")
    verdict = "MARGINAL" if ratio >= RESOLVE_SIGMA else "TOTAL"

    # --- marginal ------------------------------------------------------------
    I = Pg - Pi                      # numerator of E_idle
    A = Pa - Pg                      # numerator of E_active
    sI, sA = math.hypot(sPg, sPi), math.hypot(sPa, sPg)

    E_idle = I / fg
    rel_Ei = math.hypot(sI / I if I else 0.0, sfg / fg if fg else 0.0)
    E_active = A / fa
    rel_Ea = math.hypot(sA / A if A else 0.0, sfa / fa if fa else 0.0)

    kappa = E_active / E_idle if E_idle else float("nan")
    cov_term = (2.0 * sPg ** 2 / (A * I)) if (A and I) else 0.0
    var_rel_k = rel_Ea ** 2 + rel_Ei ** 2 + cov_term
    rel_k = math.sqrt(var_rel_k) if var_rel_k > 0 else 0.0

    # --- total ---------------------------------------------------------------
    E_idle_tot = Pi / fi
    rel_Eit = math.hypot(sPi / Pi if Pi else 0.0, sfi / fi if fi else 0.0)
    E_active_tot = Pa / fa
    rel_Eat = math.hypot(sPa / Pa if Pa else 0.0, sfa / fa if fa else 0.0)
    kappa_tot = E_active_tot / E_idle_tot if E_idle_tot else float("nan")
    rel_kt = math.hypot(rel_Eat, rel_Eit)

    return {
        "margin_mw": margin, "s_comb_mw": s_comb, "ratio_sigma": ratio,
        "verdict": verdict, "criterion_sigma": RESOLVE_SIGMA,
        "marginal": {
            "E_idle": E_idle, "E_idle_err": abs(E_idle) * rel_Ei,
            "E_active": E_active, "E_active_err": abs(E_active) * rel_Ea,
            "kappa": kappa, "kappa_err": abs(kappa) * rel_k,
            "covariance_term_included": True,
        },
        "total": {
            "E_idle": E_idle_tot, "E_idle_err": abs(E_idle_tot) * rel_Eit,
            "E_active": E_active_tot, "E_active_err": abs(E_active_tot) * rel_Eat,
            "kappa": kappa_tot, "kappa_err": abs(kappa_tot) * rel_kt,
        },
    }


# --------------------------------------------------------------------------
# B.4 voltage-drop correction
# --------------------------------------------------------------------------

def add_corrected_power(rows, stats):
    """P* = V_ref * I, with V_ref the campaign-wide mean of mean_v.

    The supply sags differently per mode (higher current -> lower rail through
    the ~0.88 ohm source resistance), so a raw power difference conflates the
    load change with the rail change. Referring every run to one voltage
    separates them.
    """
    v_ref = statistics.fmean([r["mean_v"] for r in rows])
    for r in rows:
        r["corr_mw"] = v_ref * r["mean_ma"]
    for mode, entry in stats.items():
        sel = [r for r in rows if r["mode"] == mode]
        vals = [r["corr_mw"] for r in sel]
        entry["corr_mw"] = statistics.fmean(vals)
        entry["corr_mw_sem"] = sem(vals)
    return v_ref


# --------------------------------------------------------------------------
# B.5 linearity of E(a)
# --------------------------------------------------------------------------

def fit_linear(points):
    """Ordinary least squares W = W0 + c*a, plus R^2."""
    n = len(points)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    c = sxy / sxx if sxx else float("nan")
    w0 = my - c * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (w0 + c * x)) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - ss_res / ss_tot if ss_tot else float("nan")
    return {"W0_mw": w0, "c_mw": c, "r2": r2, "n": n,
            "points": [{"a": x, "W_mw": y} for x, y in points]}


# --------------------------------------------------------------------------

def pm(v, e, fmt="%.3f"):
    if e is None:
        return (fmt % v) + " (n=1, no error)"
    return (fmt % v) + " +- " + (fmt % e)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True, help="DUMP csv of the campaign")
    ap.add_argument("--json", help="write the result blob here")
    args = ap.parse_args()

    rows = load(args.csv)
    print("=" * 74)
    print("C2b INA219 campaign analysis — %d runs from %s" % (len(rows), args.csv))
    print("=" * 74)

    # ---- per-run acceptance --------------------------------------------------
    print("\n--- per-run acceptance ------------------------------------------")
    checked = validate(rows)
    n_fail = 0
    for r, checks, ok in checked:
        if not ok:
            n_fail += 1
        print("  run %-3d %-10s %s" % (r["run_id"], r["mode"],
                                       "PASS" if ok else "FAIL"))
        for name, cok, detail in checks:
            if not cok:
                print("      [FAIL] %-16s %s" % (name, detail))
    print("  %d/%d runs pass every per-run check" % (len(rows) - n_fail, len(rows)))

    # ---- B.1 -----------------------------------------------------------------
    stats = per_mode(rows)
    print("\n--- B.1 per-mode statistics (mean +- sigma/sqrt(n)) -------------")
    print("  %-10s %3s  %-22s %-20s %-20s %s" %
          ("mode", "n", "P (mW)", "V (V)", "I (mA)", "fps"))
    for mode in REPLICATED + SWEEP:
        if mode not in stats:
            continue
        e = stats[mode]
        print("  %-10s %3d  %-22s %-20s %-20s %s" % (
            mode, e["n"],
            pm(e["mean_mw"], e["mean_mw_sem"], "%.2f"),
            pm(e["mean_v"], e["mean_v_sem"], "%.4f"),
            pm(e["mean_ma"], e["mean_ma_sem"], "%.2f"),
            pm(e["fps"], e["fps_sem"], "%.2f")))

    # ---- B.2 / B.3 -----------------------------------------------------------
    conv = conventions(stats)
    # The voltage-corrected estimator is computed here, before B.2 is reported,
    # so the criterion can be shown against BOTH power estimates. The rule as
    # written does not say which one it applies to; that ambiguity is surfaced
    # rather than resolved by picking whichever answer is preferred.
    v_ref = add_corrected_power(rows, stats)
    conv_c = conventions(stats, power_key="corr_mw", power_sem_key="corr_mw_sem")

    print("\n--- B.2 resolution criterion (fixed BEFORE seeing the data) -----")
    print("  [on raw mean_mw, the chip's POWER register, LSB = 2 mW]")
    print("    margin = P(gate) - P(idle-skip) = %.6f mW" % conv["margin_mw"])
    print("    s_comb = sqrt(s_gate^2 + s_idle^2) = %.6f mW" % conv["s_comb_mw"])
    print("    margin / s_comb = %.2f   (threshold %.0f)" %
          (conv["ratio_sigma"], conv["criterion_sigma"]))
    print("    VERDICT: %s" % conv["verdict"])
    print("  [on V_ref x I, the CURRENT register, LSB = 0.1 mA ~ 0.48 mW]")
    print("    margin = %.6f mW" % conv_c["margin_mw"])
    print("    s_comb = %.6f mW" % conv_c["s_comb_mw"])
    print("    margin / s_comb = %.2f   (threshold %.0f)" %
          (conv_c["ratio_sigma"], conv_c["criterion_sigma"]))
    print("    VERDICT: %s" % conv_c["verdict"])
    if conv["verdict"] != conv_c["verdict"]:
        print("  *** THE TWO ESTIMATORS DISAGREE — see the report. The raw POWER")
        print("      register cannot resolve this margin (2 mW LSB); its apparent")
        print("      sigma is quantisation, not noise. Author's decision. ***")

    print("\n--- B.3 both conventions ----------------------------------------")
    for name in ("marginal", "total"):
        c = conv[name]
        print("  [%s]" % name)
        print("    E_idle   = %s mJ/frame" % pm(c["E_idle"], c["E_idle_err"]))
        print("    E_active = %s mJ/frame" % pm(c["E_active"], c["E_active_err"]))
        print("    kappa    = %s" % pm(c["kappa"], c["kappa_err"]))

    # ---- B.4 -----------------------------------------------------------------
    print("\n--- B.4 voltage-drop correction (P* = V_ref x I) ----------------")
    print("  V_ref = campaign mean of mean_v = %.4f V" % v_ref)
    deltas = {}
    worst = 0.0
    for name in ("marginal", "total"):
        for key in ("E_idle", "E_active", "kappa"):
            base, corr = conv[name][key], conv_c[name][key]
            d = abs(corr - base) / abs(base) if base else 0.0
            deltas["%s.%s" % (name, key)] = {"raw": base, "corrected": corr,
                                             "delta_pct": d * 100}
            worst = max(worst, d)
            print("    %-9s %-9s raw %10.4f -> corr %10.4f   (%.2f %%)" %
                  (name, key, base, corr, d * 100))
    print("  worst change = %.2f %%  %s" %
          (worst * 100,
           "OK (<= 5 %)" if worst <= VDROP_ALARM else "*** EXCEEDS 5 % — STOP ***"))

    # ---- B.5 -----------------------------------------------------------------
    pts = [(stats[m]["a"], stats[m]["mean_mw"]) for m in FIT_MODES if m in stats]
    fit = fit_linear(pts)
    print("\n--- B.5 linearity of W(a) = W0 + c*a  (gate excluded) -----------")
    for p in fit["points"]:
        print("    a = %.4f   W = %8.2f mW" % (p["a"], p["W_mw"]))
    print("  W0 = %.2f mW   c = %.2f mW   R^2 = %.5f   (Orin reference 0.99901)"
          % (fit["W0_mw"], fit["c_mw"], fit["r2"]))

    # ---- B.5b diagnostic: W against inference RATE ---------------------------
    # Not a substitute for B.5, an explanation of it. fps is not constant across
    # modes here (inference blocks the capture loop: 24.99 fps at a=0 down to
    # 13.88 at a=1), so `a` = opens/frames is not proportional to the number of
    # inferences executed per second — and it is the per-second rate that costs
    # energy. Fitting against the rate tests whether the curvature in W(a) is
    # simply that reparametrisation.
    rate_pts = [(r["infer_count"] / (r["elapsed_ms"] / 1000.0), r["mean_mw"])
                for r in rows]
    rate_fit = fit_linear(rate_pts)
    rate_pts_c = [(r["infer_count"] / (r["elapsed_ms"] / 1000.0), r["corr_mw"])
                  for r in rows]
    rate_fit_c = fit_linear(rate_pts_c)
    print("\n--- B.5b diagnostic: W(rate) = W0 + c*(inferences/s), all runs ---")
    print("  raw       W0 = %.2f mW   c = %.3f mW per inf/s   R^2 = %.5f"
          % (rate_fit["W0_mw"], rate_fit["c_mw"], rate_fit["r2"]))
    print("  V-corrected W0 = %.2f mW   c = %.3f mW per inf/s   R^2 = %.5f"
          % (rate_fit_c["W0_mw"], rate_fit_c["c_mw"], rate_fit_c["r2"]))

    # ---- B.6 -----------------------------------------------------------------
    floor = stats["idle-skip"]["mean_mw"] / stats["active"]["mean_mw"] * 100.0
    print("\n--- B.6 platform floor ------------------------------------------")
    print("  P(idle-skip) / P(active) = %.2f %%" % floor)

    blob = {
        "csv": args.csv,
        "n_runs": len(rows),
        "runs": rows,
        "per_run_failures": n_fail,
        "per_mode": stats,
        "conventions_raw": conv,
        "conventions_voltage_corrected": conv_c,
        "v_ref": v_ref,
        "voltage_correction_deltas": deltas,
        "fit_E_of_a": fit,
        "fit_W_of_rate_raw": rate_fit,
        "fit_W_of_rate_corrected": rate_fit_c,
        "platform_floor_pct": floor,
    }
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(blob, f, indent=2)
        print("\n[json -> %s]" % args.json)
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
