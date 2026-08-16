#!/usr/bin/env python3
"""Combined C1 + C1b analysis. Reads C1 (c1_power_logs/results.jsonl) and C1b
(c1b_power_logs/results.jsonl), builds a master per-run table with runtime+mode
columns, computes mJ/frame under Total / Marginal-over-static / Marginal-over-idle-gate,
kappa per convention, and reconciles against the paper's (30.4, 290.8) mJ/frame.
Pure-Python. Writes c1_orin_results.csv (combined) and computed_values_c1b.json."""
import csv, json, os, statistics, sys

BASE = os.path.dirname(os.path.abspath(__file__))
C1 = os.path.join(BASE, "c1_power_logs", "results.jsonl")
C1B = os.path.join(BASE, "c1b_power_logs", "results.jsonl")
FPS_FEED = 30.0
PAPER_EIDLE, PAPER_EACTIVE = 30.4, 290.8

# tag -> (detector, runtime, mode_label, imgsz)
META = {
    "static":            ("none",    "n/a",      "static",    640),
    "idle_yolo26s":      ("yolo26s", "cpu",      "idle-skip", 640),
    "idle_yolov3":       ("yolov3u", "cpu",      "idle-skip", 416),
    "active_yolo26s":    ("yolo26s", "ort-cuda", "active",    640),
    "active_yolov3":     ("yolov3u", "ort-cuda", "active",    416),
    "sweep_yolo26s_k10": ("yolo26s", "ort-cuda", "sweep",     640),
    "sweep_yolo26s_k5":  ("yolo26s", "ort-cuda", "sweep",     640),
    "sweep_yolo26s_k2":  ("yolo26s", "ort-cuda", "sweep",     640),
    "idlegate":          ("none",    "cpu-mog2", "idle-gate", 416),
    "active_trt_yolov3": ("yolov3u", "trt-fp16", "active",    416),
    "active_trt_yolo26s":("yolo26s", "trt-fp16", "active",    640),
}

def load(path):
    out = []
    if not os.path.exists(path): return out
    with open(path) as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                r = json.loads(ln)
                if "error" not in r: out.append(r)
    return out

runs = load(C1) + load(C1B)

def meta(tag):
    return META.get(tag, ("?", "?", "?", 0))

def gmeanW(tag):
    v = [r["watts_mean"] for r in runs if r["tag"] == tag]
    return statistics.mean(v) if v else None

W_static  = gmeanW("static")
W_iskip26 = gmeanW("idle_yolo26s")
W_iskipv3 = gmeanW("idle_yolov3")
W_igate   = gmeanW("idlegate")

# ---- master per-run table ----
rows = []
for r in sorted(runs, key=lambda x: (x["tag"], x["run"])):
    det, rt, ml, imgsz = meta(r["tag"])
    w, fps = r["watts_mean"], r["fps"]
    is_active = ml in ("active", "sweep")
    mj_total = w/fps*1000 if fps else float("nan")
    mj_ms = (w-W_static)/fps*1000 if (W_static and fps and ml != "static") else ""
    mj_mg = ((w-W_igate)/fps*1000) if (is_active and W_igate and fps) else ""
    rows.append(dict(detector=det, runtime=rt, mode=ml, tag=r["tag"], k=r["k"],
                     run=r["run"], imgsz=imgsz, watts_mean=round(w,4),
                     watts_std=r["watts_std"], fps=round(fps,3),
                     infer_fps=round(r["infer_fps"],3), mJ_total=round(mj_total,2),
                     mJ_marginal_static=(round(mj_ms,2) if mj_ms!="" else ""),
                     mJ_marginal_over_idle_gate=(round(mj_mg,2) if mj_mg!="" else ""),
                     temp_start=r["temp_start"], temp_end=r["temp_end"],
                     measure_s=r["measure_s"], n_samples=r["n_power_samples"]))

with open(os.path.join(BASE, "c1_orin_results.csv"), "w", newline="") as f:
    wtr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    wtr.writeheader(); wtr.writerows(rows)

# ---- aggregates ----
def agg(tag):
    g = [r for r in runs if r["tag"] == tag]
    if not g: return None
    W = [x["watts_mean"] for x in g]; F = [x["fps"] for x in g]
    return dict(n=len(g), W=statistics.mean(W),
                Wstd=(statistics.pstdev(W) if len(W)>1 else 0.0),
                fps=statistics.mean(F))

def energy_row(tag):
    a = agg(tag)
    if not a: return None
    det, rt, ml, imgsz = meta(tag)
    d = dict(tag=tag, detector=det, runtime=rt, mode=ml, W=a["W"], Wstd=a["Wstd"], fps=a["fps"])
    d["E_total"] = a["W"]/a["fps"]*1000
    d["E_marg_static"] = (a["W"]-W_static)/a["fps"]*1000
    if ml in ("active","sweep") and W_igate:
        d["E_marg_gate"] = (a["W"]-W_igate)/a["fps"]*1000
    return d

TAGS = ["static","idle_yolo26s","idle_yolov3","idlegate",
        "active_yolo26s","active_trt_yolo26s","active_yolov3","active_trt_yolov3"]
table = [energy_row(t) for t in TAGS if energy_row(t)]

# E_idle candidates
E_idle_iskip26 = {"total": W_iskip26/FPS_FEED*1000, "marg_static": (W_iskip26-W_static)/FPS_FEED*1000}
E_idle_iskipv3 = {"total": W_iskipv3/FPS_FEED*1000, "marg_static": (W_iskipv3-W_static)/FPS_FEED*1000}
E_idle_gate    = {"total": W_igate/FPS_FEED*1000,   "marg_static": (W_igate-W_static)/FPS_FEED*1000} if W_igate else None

comp = dict(W_static=W_static, W_idleskip26=W_iskip26, W_idleskipv3=W_iskipv3, W_idlegate=W_igate,
            E_idle_idleskip_yolo26s=E_idle_iskip26, E_idle_idleskip_yolov3=E_idle_iskipv3,
            E_idle_idlegate=E_idle_gate, table=table,
            paper=dict(E_idle=PAPER_EIDLE, E_active=PAPER_EACTIVE, kappa=PAPER_EACTIVE/PAPER_EIDLE))

# ---- reconciliation vs paper (30.4 / 290.8) ----
# paper convention: E_idle = decode+MOG2 marginal over board (idle-gate marg_static);
#                   E_active = active marginal over the running gate (marg_gate).
recon = {}
if E_idle_gate:
    recon["E_idle_used"] = E_idle_gate["marg_static"]
    recon["E_idle_ratio_vs_paper"] = E_idle_gate["marg_static"]/PAPER_EIDLE
    for tag in ("active_trt_yolov3","active_trt_yolo26s","active_yolov3","active_yolo26s"):
        er = energy_row(tag)
        if er and "E_marg_gate" in er:
            recon[tag] = dict(E_active_marg_gate=er["E_marg_gate"],
                              ratio_vs_paper=er["E_marg_gate"]/PAPER_EACTIVE,
                              kappa_gate=er["E_marg_gate"]/E_idle_gate["marg_static"])
comp["reconciliation"] = recon

with open(os.path.join(BASE, "computed_values_c1b.json"), "w") as f:
    json.dump(comp, f, indent=2, default=lambda o: round(o,4) if isinstance(o,float) else o)

# ---- console ----
print("== baseline W ==  static=%.3f  idleskip26=%.3f  idleskipv3=%.3f  idlegate=%s"
      % (W_static, W_iskip26, W_iskipv3, ("%.3f"%W_igate if W_igate else "NA")))
print("\n%-20s %-9s %-10s %6s %7s %9s %11s %11s" %
      ("tag","runtime","mode","W","fps","E_total","E_mgStatic","E_mgGate"))
for d in table:
    print("%-20s %-9s %-10s %6.3f %7.2f %9.1f %11.1f %11s" %
          (d["tag"], d["runtime"], d["mode"], d["W"], d["fps"], d["E_total"],
           d["E_marg_static"], ("%.1f"%d["E_marg_gate"] if "E_marg_gate" in d else "-")))
print("\n== E_idle candidates (mJ/frame @30fps) ==")
print("  idle-skip yolo26s: total=%.1f  marg_static=%.1f" % (E_idle_iskip26["total"],E_idle_iskip26["marg_static"]))
print("  idle-skip yolov3 : total=%.1f  marg_static=%.1f" % (E_idle_iskipv3["total"],E_idle_iskipv3["marg_static"]))
if E_idle_gate:
    print("  idle-GATE (MOG2) : total=%.1f  marg_static=%.1f  <-- paper's E_idle convention" %
          (E_idle_gate["total"],E_idle_gate["marg_static"]))
print("\n== Reconciliation vs paper (E_idle=30.4, E_active=290.8, kappa=9.57) ==")
if recon:
    print("  E_idle (idle-gate marg_static) = %.1f  ->  %.2fx paper" %
          (recon["E_idle_used"], recon["E_idle_ratio_vs_paper"]))
    for k,v in recon.items():
        if isinstance(v,dict):
            print("  %-20s E_active(marg over gate)=%.1f  ->  %.2fx paper   kappa=%.1f" %
                  (k, v["E_active_marg_gate"], v["ratio_vs_paper"], v["kappa_gate"]))
print("\nWrote c1_orin_results.csv (combined) and computed_values_c1b.json")
