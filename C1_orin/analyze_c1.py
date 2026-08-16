#!/usr/bin/env python3
"""Analyze C1 Orin measurements: read results.jsonl (per-run summaries) + power CSVs,
compute mJ/frame under BOTH accounting conventions, kappa, and E(a) linearity fit.
Pure-Python (no numpy). Writes c1_orin_results.csv and computed_values.json.

Usage: python analyze_c1.py <dir with results.jsonl and *_run*.csv>
"""
import csv, json, os, statistics, sys

D = sys.argv[1] if len(sys.argv) > 1 else "c1_power_logs"
FPS_FEED = 30.0

runs = []
with open(os.path.join(D, "results.jsonl")) as f:
    for ln in f:
        ln = ln.strip()
        if ln:
            r = json.loads(ln)
            if "error" not in r:
                runs.append(r)

def group(tag):
    return [r for r in runs if r["tag"] == tag]

def gmean(tag, key):
    v = [r[key] for r in group(tag)]
    return statistics.mean(v) if v else float("nan")

# Reference baselines (mean watts across that mode's runs)
W_static = gmean("static", "watts_mean")
W_idle26 = gmean("idle_yolo26s", "watts_mean")
W_idlev3 = gmean("idle_yolov3", "watts_mean")

# idle ref per row-tag
def idle_ref(tag):
    if tag.startswith("static"):            return None
    if tag.startswith("idle_"):             return W_static
    if "yolov3" in tag:                     return W_idlev3
    return W_idle26   # active/sweep yolo26s

# ---- per-run results table ----
rows = []
for r in sorted(runs, key=lambda x: (x["tag"], x["run"])):
    w, fps = r["watts_mean"], r["fps"]
    mj_total = w / fps * 1000 if fps else float("nan")
    ref = idle_ref(r["tag"])
    mj_marg = ((w - ref) / fps * 1000) if (ref is not None and fps) else ""
    rows.append(dict(detector=r["detector"], mode=r["mode"], tag=r["tag"], k=r["k"],
                     run=r["run"], watts_mean=round(w,4), watts_std=r["watts_std"],
                     fps=round(fps,3), infer_fps=round(r["infer_fps"],3),
                     mJ_total=round(mj_total,2),
                     mJ_marginal=(round(mj_marg,2) if mj_marg != "" else ""),
                     temp_start=r["temp_start"], temp_end=r["temp_end"],
                     measure_s=r["measure_s"], n_samples=r["n_power_samples"]))

with open(os.path.join(D, "..", "c1_orin_results.csv"), "w", newline="") as f:
    wtr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    wtr.writeheader(); wtr.writerows(rows)

# ---- aggregated per (detector,mode) ----
def agg(tag):
    g = group(tag)
    if not g: return None
    W = [x["watts_mean"] for x in g]; F = [x["fps"] for x in g]
    return dict(tag=tag, n=len(g),
                W_mean=statistics.mean(W), W_std=(statistics.pstdev(W) if len(W)>1 else 0.0),
                fps=statistics.mean(F),
                infer_fps=statistics.mean([x["infer_fps"] for x in g]),
                temp_start=statistics.mean([x["temp_start"] for x in g]),
                temp_end=statistics.mean([x["temp_end"] for x in g]))

def E_conventions(active_tag, idle_tag, ref_for_idle):
    """Return E_idle/E_active/kappa under total & marginal conventions."""
    ai = agg(idle_tag); aa = agg(active_tag)
    out = {}
    # idle
    Ei_tot = ai["W_mean"]/ai["fps"]*1000
    Ei_marg = (ai["W_mean"]-ref_for_idle)/ai["fps"]*1000
    # active
    Ea_tot = aa["W_mean"]/aa["fps"]*1000
    Ea_marg = (aa["W_mean"]-ai["W_mean"])/aa["fps"]*1000
    out["idle"] = ai; out["active"] = aa
    out["E_idle_total"]=Ei_tot; out["E_idle_marginal"]=Ei_marg
    out["E_active_total"]=Ea_tot; out["E_active_marginal"]=Ea_marg
    out["kappa_total"]=Ea_tot/Ei_tot; out["kappa_marginal"]=Ea_marg/Ei_marg
    return out

comp = {"W_static": W_static, "W_idle26": W_idle26, "W_idlev3": W_idlev3}
comp["yolo26s"] = E_conventions("active_yolo26s","idle_yolo26s", W_static)
comp["yolov3"]  = E_conventions("active_yolov3","idle_yolov3", W_static)

# ---- E(a) linearity (yolo26s, paced 30fps): a=0 idle, sweeps k=10/5/2 ----
def linfit(xs, ys):
    n=len(xs); mx=statistics.mean(xs); my=statistics.mean(ys)
    sxx=sum((x-mx)**2 for x in xs); sxy=sum((xs[i]-mx)*(ys[i]-my) for i in range(n))
    b1=sxy/sxx; b0=my-b1*mx
    ss_res=sum((ys[i]-(b0+b1*xs[i]))**2 for i in range(n))
    ss_tot=sum((y-my)**2 for y in ys)
    r2=1-ss_res/ss_tot if ss_tot>0 else float("nan")
    return b0,b1,r2

sweep_pts = [(0.0, W_idle26)]
for k,a in [(10,0.1),(5,0.2),(2,0.5)]:
    ag = agg("sweep_yolo26s_k%d"%k)
    if ag: sweep_pts.append((a, ag["W_mean"]))
xs=[p[0] for p in sweep_pts]; ys=[p[1] for p in sweep_pts]
b0,b1,r2 = linfit(xs,ys)
comp["sweep"] = dict(points=sweep_pts, W0=b0, slope=b1, r2=r2,
                     E_idle_fit_total=b0/FPS_FEED*1000,
                     E_active_fit_total=(b0+b1)/FPS_FEED*1000,
                     E_idle_fit_marg=(b0-W_static)/FPS_FEED*1000,
                     E_active_fit_marg=((b0+b1)-W_static)/FPS_FEED*1000)

with open(os.path.join(D, "..", "computed_values.json"), "w") as f:
    json.dump(comp, f, indent=2, default=lambda o: round(o,4) if isinstance(o,float) else o)

# ---- console summary ----
def mjt(x): return "%.1f"%x
print("== baselines (W) ==")
print("  static=%.3f  idle_yolo26s=%.3f  idle_yolov3=%.3f" % (W_static,W_idle26,W_idlev3))
for det in ("yolo26s","yolov3"):
    c=comp[det]
    print("\n== %s ==" % det)
    print("  idle:   W=%.3f fps=%.2f" % (c["idle"]["W_mean"], c["idle"]["fps"]))
    print("  active: W=%.3f fps=%.2f" % (c["active"]["W_mean"], c["active"]["fps"]))
    print("  TOTAL   : E_idle=%s  E_active=%s  kappa=%.2f" %
          (mjt(c["E_idle_total"]),mjt(c["E_active_total"]),c["kappa_total"]))
    print("  MARGINAL: E_idle=%s  E_active=%s  kappa=%.2f" %
          (mjt(c["E_idle_marginal"]),mjt(c["E_active_marginal"]),c["kappa_marginal"]))
s=comp["sweep"]
print("\n== E(a) linearity (yolo26s, 30fps) ==")
print("  points (a,W):", [(round(a,2),round(w,3)) for a,w in s["points"]])
print("  W(a)=%.4f + %.4f*a   R2=%.5f" % (s["W0"],s["slope"],s["r2"]))
print("  E_idle_fit(total)=%s  E_active_fit(a=1,total)=%s" %
      (mjt(s["E_idle_fit_total"]),mjt(s["E_active_fit_total"])))
print("\nWrote c1_orin_results.csv and computed_values.json")
