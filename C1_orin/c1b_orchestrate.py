#!/usr/bin/env python3
"""C1b orchestrator: TRT active (both detectors), optional 30fps-paced TRT, and
idle-gate (MOG2). Reuses c1_run.py. Thermal-gated, nohup-safe. Writes results.jsonl
and progress.txt into c1b_out/. RUNS built from INCLUDE flags set after smoke test."""
import json, os, subprocess, sys, time, glob

OUT   = "/home/dat/topic30/c1b_out"
CODE  = "/home/dat/topic30/code/c1_run.py"
Y26E  = "/home/dat/topic30/models/yolo26s_fp16.engine"
YV3E  = "/home/dat/topic30/models/yolov3u_fp16.engine"
FR    = "/home/dat/topic30/data/highway/input"
GATE  = 60.0; GATE_TIMEOUT = 900
WARM  = 60; MEAS = 300

# which paced variants to include (set by launcher via env: PACE26=1 PACEV3=1)
PACE26 = os.environ.get("PACE26","1") == "1"
PACEV3 = os.environ.get("PACEV3","1") == "1"

os.makedirs(OUT, exist_ok=True)
RESULTS = os.path.join(OUT, "results.jsonl")
PROG    = os.path.join(OUT, "progress.txt")
LOG     = os.path.join(OUT, "orchestrate.log")

def _try_read(p):
    try: int(open(p).read()); return True
    except Exception: return False
_ZONES = [z for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*/temp")) if _try_read(z)]
def temp_max():
    m=0
    for z in _ZONES:
        try:
            v=int(open(z).read()); m=v if v>m else m
        except Exception: pass
    return m/1000.0

def log(msg):
    line="[%s] %s"%(time.strftime("%H:%M:%S"),msg); print(line,flush=True)
    with open(LOG,"a") as f: f.write(line+"\n")

RUNS=[]
# idle-gate (MOG2) @416, cool -> first, x3
for r in (1,2,3):
    RUNS.append(dict(tag="idlegate", detector="none", mode="idlegate", runtime="ort",
                     imgsz=416, engine="", k=1, warmup=WARM, measure=MEAS, run=r))
# paced TRT (deployment-realistic 30fps) if applicable
if PACEV3:
    for r in (1,2,3):
        RUNS.append(dict(tag="activepaced_trt_yolov3", detector="yolov3", mode="activepaced",
                         runtime="trt", imgsz=416, engine=YV3E, k=1, warmup=WARM, measure=MEAS, run=r))
if PACE26:
    for r in (1,2,3):
        RUNS.append(dict(tag="activepaced_trt_yolo26s", detector="yolo26s", mode="activepaced",
                         runtime="trt", imgsz=640, engine=Y26E, k=1, warmup=WARM, measure=MEAS, run=r))
# back-to-back TRT active (max throughput), hottest -> last, x3
for r in (1,2,3):
    RUNS.append(dict(tag="active_trt_yolov3", detector="yolov3", mode="active",
                     runtime="trt", imgsz=416, engine=YV3E, k=1, warmup=WARM, measure=MEAS, run=r))
for r in (1,2,3):
    RUNS.append(dict(tag="active_trt_yolo26s", detector="yolo26s", mode="active",
                     runtime="trt", imgsz=640, engine=Y26E, k=1, warmup=WARM, measure=MEAS, run=r))

def gate():
    t0=time.time()
    while True:
        t=temp_max()
        if t<=GATE: log("gate OK temp=%.1f"%t); return
        if time.time()-t0>GATE_TIMEOUT: log("gate TIMEOUT temp=%.1f proceeding"%t); return
        log("cooldown temp=%.1f wait 15s"%t); time.sleep(15)

def main():
    total=len(RUNS); log("START C1b, %d runs (PACEV3=%s PACE26=%s)"%(total,PACEV3,PACE26))
    open(RESULTS,"w").close()
    for i,rc in enumerate(RUNS,1):
        with open(PROG,"w") as f: f.write("run %d/%d : %s run%d (temp=%.1f)\n"%(i,total,rc["tag"],rc["run"],temp_max()))
        gate()
        cmd=[sys.executable,CODE,"--detector",rc["detector"],"--mode",rc["mode"],
             "--runtime",rc["runtime"],"--engine",rc["engine"],"--k",str(rc["k"]),
             "--imgsz",str(rc["imgsz"]),"--model","","--frames",FR,
             "--warmup",str(rc["warmup"]),"--measure",str(rc["measure"]),
             "--fps","30","--power_hz","10","--run",str(rc["run"]),"--tag",rc["tag"],"--outdir",OUT]
        log("RUN %d/%d %s run%d"%(i,total,rc["tag"],rc["run"]))
        p=subprocess.run(cmd,capture_output=True,text=True)
        summ=None
        for ln in p.stdout.splitlines():
            if ln.startswith("SUMMARY "): summ=json.loads(ln[8:])
        if summ is None:
            log("ERROR %s run%d no SUMMARY. stderr: %s"%(rc["tag"],rc["run"],p.stderr[-500:]))
            with open(RESULTS,"a") as f: f.write(json.dumps({"tag":rc["tag"],"run":rc["run"],"error":p.stderr[-300:]})+"\n")
            continue
        summ["runtime"]=rc["runtime"]
        with open(RESULTS,"a") as f: f.write(json.dumps(summ)+"\n")
        log("DONE %s run%d: W=%.3f fps=%.2f infer_fps=%.2f temp %.1f->%.1f"%(
            rc["tag"],rc["run"],summ["watts_mean"],summ["fps"],summ["infer_fps"],
            summ["temp_start"],summ["temp_end"]))
    with open(PROG,"a") as f: f.write("ALL DONE\n")
    log("ALL DONE")

if __name__=="__main__": main()
