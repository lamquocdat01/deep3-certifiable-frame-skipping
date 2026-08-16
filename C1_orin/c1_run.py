#!/usr/bin/env python3
"""
c1_run.py — one C1 measurement run on Jetson Orin Nano.
Reads VDD_IN (INA3221 hwmon sysfs) + SoC temp in a background thread while a
frame feed runs in one of four modes. Writes a per-run power CSV and prints a
one-line JSON summary (watts over the MEASURE window only).

Modes:
  static : no feed at all (board idle baseline). No warmup work.
  idle   : decode(imread)+preprocess(letterbox+normalize) every frame, NO inference, paced to --fps.
  active : decode+preprocess+inference every frame, back-to-back (no pacing). Records achieved fps.
  sweep  : decode+preprocess every frame, inference every k-th frame, paced to --fps.
"""
import argparse, glob, json, os, sys, threading, time
import numpy as np
sys.path.insert(0, "/home/dat/topic30/code")

HWMON = "/sys/class/hwmon/hwmon1"
IN_V = HWMON + "/in1_input"      # VDD_IN bus voltage (mV)
IN_C = HWMON + "/curr1_input"    # VDD_IN current (mA)
def _probe_zones():
    good = []
    for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*/temp")):
        try:
            int(open(z).read()); good.append(z)
        except Exception:
            pass
    return good
ZONES = _probe_zones()

def read_temp_max():
    m = 0
    for z in ZONES:
        try:
            v = int(open(z).read())
            if v > m: m = v
        except Exception:
            pass
    return m / 1000.0

def read_power():
    mv = float(open(IN_V).read()); ma = float(open(IN_C).read())
    return mv, ma, (mv/1000.0)*(ma/1000.0)

class Sampler(threading.Thread):
    def __init__(self, hz, csv_path):
        super().__init__(daemon=True)
        self.dt = 1.0/hz; self.run_flag = True
        self.rows = []           # (t_rel, phase, mv, ma, watt, temp)
        self.phase = "warmup"
        self.t0 = None
        self.csv_path = csv_path
    def run(self):
        self.t0 = time.time()
        while self.run_flag:
            t = time.time()
            try:
                mv, ma, w = read_power(); temp = read_temp_max()
                self.rows.append((t - self.t0, self.phase, mv, ma, w, temp))
            except Exception:
                pass
            sl = self.dt - (time.time() - t)
            if sl > 0: time.sleep(sl)
    def stop(self):
        self.run_flag = False; self.join()
        with open(self.csv_path, "w") as f:
            f.write("t_rel_s,phase,mv,ma,watt,temp_max_c\n")
            for r in self.rows:
                f.write("%.3f,%s,%.1f,%.1f,%.4f,%.2f\n" % r)

def preprocess(img, imgsz):
    import cv2
    h, w = img.shape[:2]
    r = min(imgsz/h, imgsz/w)
    nh, nw = int(round(h*r)), int(round(w*r))
    canvas = np.full((imgsz, imgsz, 3), 114, dtype=np.uint8)
    canvas[:nh, :nw] = cv2.resize(img, (nw, nh))
    x = np.ascontiguousarray(canvas[:, :, ::-1].transpose(2,0,1)[None].astype(np.float32)/255.0)
    return x

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--detector", default="none")
    ap.add_argument("--mode", required=True,
                    choices=["static","idle","active","activepaced","sweep","idlegate"])
    ap.add_argument("--runtime", default="ort", choices=["ort","trt"])
    ap.add_argument("--engine", default="")
    ap.add_argument("--k", type=int, default=1)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--model", default="")
    ap.add_argument("--frames", default="/home/dat/topic30/data/highway/input")
    ap.add_argument("--warmup", type=float, default=60.0)
    ap.add_argument("--measure", type=float, default=300.0)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--power_hz", type=float, default=10.0)
    ap.add_argument("--run", type=int, default=1)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()

    os.makedirs(a.outdir, exist_ok=True)
    csv_path = os.path.join(a.outdir, "%s_run%d.csv" % (a.tag, a.run))

    files = sorted(glob.glob(os.path.join(a.frames, "*.jpg")) +
                   glob.glob(os.path.join(a.frames, "*.png")))
    if a.mode != "static" and not files:
        print(json.dumps({"error": "no frames in %s" % a.frames})); sys.exit(2)

    det = None
    if a.mode in ("active","activepaced","sweep"):
        if a.runtime == "trt":
            from trt_infer import TRTDetector
            det = TRTDetector(a.engine, imgsz=a.imgsz)
        else:
            from detector_t1 import DetectorT1
            det = DetectorT1(a.model, imgsz=a.imgsz, require_gpu=True)

    import cv2
    mog2 = cv2.createBackgroundSubtractorMOG2() if a.mode == "idlegate" else None
    period = 1.0/a.fps
    smp = Sampler(a.power_hz, csv_path); smp.start()
    time.sleep(0.3)  # let sampler prime

    def feed(duration, phase):
        smp.phase = phase
        t_end = time.time() + duration
        n_frames = 0; n_infer = 0; i = 0
        next_tick = time.time()
        while time.time() < t_end:
            if a.mode == "static":
                time.sleep(0.05); n_frames += 1; continue
            f = files[i % len(files)]; i += 1
            img = cv2.imread(f)
            if img is None: continue
            if a.mode == "idle":
                _ = preprocess(img, a.imgsz)
            elif a.mode == "idlegate":
                r = cv2.resize(img, (a.imgsz, a.imgsz))
                _ = mog2.apply(r)
            elif a.mode in ("active", "activepaced"):
                det.infer(img); n_infer += 1
            elif a.mode == "sweep":
                if (n_frames % a.k) == 0:
                    det.infer(img); n_infer += 1
                else:
                    _ = preprocess(img, a.imgsz)
            n_frames += 1
            if a.mode in ("idle","sweep","activepaced","idlegate"):      # paced
                next_tick += period
                sl = next_tick - time.time()
                if sl > 0: time.sleep(sl)
                elif sl < -1.0: next_tick = time.time()   # fell far behind; resync
            # active: no sleep (back-to-back)
        return n_frames, n_infer

    feed(a.warmup, "warmup")
    t_m0 = time.time()
    temp_start = read_temp_max()
    n_frames, n_infer = feed(a.measure, "measure")
    t_m1 = time.time()
    temp_end = read_temp_max()
    smp.stop()

    mw = [r for r in smp.rows if r[1] == "measure"]
    watts = [r[4] for r in mw]
    import statistics
    wmean = statistics.mean(watts) if watts else 0.0
    wstd = statistics.pstdev(watts) if len(watts) > 1 else 0.0
    elapsed = t_m1 - t_m0
    fps = n_frames/elapsed if elapsed > 0 else 0.0
    infer_fps = n_infer/elapsed if elapsed > 0 else 0.0
    summary = {
        "tag": a.tag, "detector": a.detector, "mode": a.mode, "k": a.k,
        "imgsz": a.imgsz, "run": a.run, "watts_mean": round(wmean,4),
        "watts_std": round(wstd,4), "fps": round(fps,3), "infer_fps": round(infer_fps,3),
        "frames": n_frames, "infers": n_infer, "measure_s": round(elapsed,1),
        "temp_start": round(temp_start,2), "temp_end": round(temp_end,2),
        "n_power_samples": len(watts), "csv": os.path.basename(csv_path),
    }
    print("SUMMARY " + json.dumps(summary))

if __name__ == "__main__":
    main()
