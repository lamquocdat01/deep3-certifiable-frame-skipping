#!/usr/bin/env python3
"""C1 orchestrator: runs the full (detector, mode, run) matrix with thermal-gated
cooldowns. Robust to SSH drops (run under nohup). Appends each run's JSON summary
to results.jsonl and maintains progress.txt."""
import json, os, subprocess, sys, time, glob

OUT   = "/home/dat/topic30/c1_out"
CODE  = "/home/dat/topic30/code/c1_run.py"
Y26   = "/home/dat/topic30/models/yolo26s.onnx"
YV3   = "/home/dat/topic30/models/yolov3u.onnx"
FR    = "/home/dat/topic30/data/highway/input"
GATE  = 60.0          # cooldown gate (deg C); floor ~57
GATE_TIMEOUT = 900    # max seconds to wait for cooldown before proceeding
WARM  = 60
MEAS  = 300

os.makedirs(OUT, exist_ok=True)
RESULTS = os.path.join(OUT, "results.jsonl")
PROG    = os.path.join(OUT, "progress.txt")
LOG     = os.path.join(OUT, "orchestrate.log")

def _try_read(p):
    try: int(open(p).read()); return True
    except Exception: return False
_ZONES = [z for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*/temp")) if _try_read(z)]
def temp_max():
    m = 0
    for z in _ZONES:
        try:
            v = int(open(z).read())
            if v > m: m = v
        except Exception: pass
    return m/1000.0

def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    with open(LOG, "a") as f: f.write(line+"\n")

# Run matrix: dicts with all c1_run args
RUNS = []
# static board baseline (cool) x3, short
for r in (1,2,3):
    RUNS.append(dict(tag="static", detector="none", mode="static", imgsz=640,
                     model="", k=1, warmup=10, measure=180, run=r))
# idle-skip per detector (preprocessing differs: 640 vs 416) x3
for r in (1,2,3):
    RUNS.append(dict(tag="idle_yolo26s", detector="yolo26s", mode="idle", imgsz=640,
                     model="", k=1, warmup=WARM, measure=MEAS, run=r))
for r in (1,2,3):
    RUNS.append(dict(tag="idle_yolov3", detector="yolov3", mode="idle", imgsz=416,
                     model="", k=1, warmup=WARM, measure=MEAS, run=r))
# active per detector x3
for r in (1,2,3):
    RUNS.append(dict(tag="active_yolo26s", detector="yolo26s", mode="active", imgsz=640,
                     model=Y26, k=1, warmup=WARM, measure=MEAS, run=r))
for r in (1,2,3):
    RUNS.append(dict(tag="active_yolov3", detector="yolov3", mode="active", imgsz=416,
                     model=YV3, k=1, warmup=WARM, measure=MEAS, run=r))
# activation sweep yolo26s: k=10(a=.1),5(a=.2),2(a=.5) x1 each
for k in (10,5,2):
    RUNS.append(dict(tag="sweep_yolo26s_k%d"%k, detector="yolo26s", mode="sweep", imgsz=640,
                     model=Y26, k=k, warmup=WARM, measure=MEAS, run=1))

def gate():
    t0 = time.time()
    while True:
        t = temp_max()
        if t <= GATE:
            log("gate OK temp=%.1f<=%.1f" % (t, GATE)); return
        if time.time()-t0 > GATE_TIMEOUT:
            log("gate TIMEOUT temp=%.1f, proceeding" % t); return
        log("cooldown temp=%.1f>%.1f, wait 15s" % (t, GATE)); time.sleep(15)

def main():
    total = len(RUNS)
    log("START orchestrator, %d runs" % total)
    open(RESULTS, "w").close()
    for i, rc in enumerate(RUNS, 1):
        with open(PROG,"w") as f:
            f.write("run %d/%d : %s run%d (temp=%.1f)\n" % (i,total,rc["tag"],rc["run"],temp_max()))
        gate()
        cmd = [sys.executable, CODE,
               "--detector", rc["detector"], "--mode", rc["mode"], "--k", str(rc["k"]),
               "--imgsz", str(rc["imgsz"]), "--model", rc["model"], "--frames", FR,
               "--warmup", str(rc["warmup"]), "--measure", str(rc["measure"]),
               "--fps", "30", "--power_hz", "10", "--run", str(rc["run"]),
               "--tag", rc["tag"], "--outdir", OUT]
        log("RUN %d/%d %s run%d starting (est %ds)" % (i,total,rc["tag"],rc["run"],rc["warmup"]+rc["measure"]))
        p = subprocess.run(cmd, capture_output=True, text=True)
        out = p.stdout.strip()
        summ = None
        for ln in out.splitlines():
            if ln.startswith("SUMMARY "):
                summ = json.loads(ln[8:])
        if summ is None:
            log("ERROR %s run%d: no SUMMARY. stderr tail: %s" % (rc["tag"],rc["run"], p.stderr[-500:]))
            with open(RESULTS,"a") as f:
                f.write(json.dumps({"tag":rc["tag"],"run":rc["run"],"error":p.stderr[-300:]})+"\n")
            continue
        with open(RESULTS,"a") as f: f.write(json.dumps(summ)+"\n")
        log("DONE %s run%d: W=%.3f+-%.3f fps=%.2f infer_fps=%.2f temp %.1f->%.1f" % (
            rc["tag"],rc["run"],summ["watts_mean"],summ["watts_std"],summ["fps"],
            summ["infer_fps"],summ["temp_start"],summ["temp_end"]))
    with open(PROG,"a") as f: f.write("ALL DONE\n")
    log("ALL DONE")

if __name__ == "__main__":
    main()
