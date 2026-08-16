#!/usr/bin/env python3
"""capture_scores.py — person-vs-wall score capture (C2a acceptance test 2).

Speaks the same STATS protocol as evaluate.py, but built for a capture you run
with the camera aimed by hand, so it adds the three things that matters for:

  * one live progress line per second, so an aimed-by-hand run is visibly alive
  * a hard abort if no STATS parses for >5 s (it never hangs waiting on a dead
    port — it reports and exits non-zero)
  * a mean/std summary printed at the end of each run

The CSV schema is identical to `evaluate.py --raw-log`, so the two are
interchangeable as evidence:

    host_time, person, noperson, infer_count, fps

`person`/`noperson` are the raw int8 output-tensor values at kPersonIndex=1 /
kNotAPersonIndex=0. They are exact negatives of each other, so `person > 0`
means person-present. Statistics are computed on the raw int8 `person` value.

Note: opening the port toggles DTR/RTS, which resets the board on this
auto-reset design. Keep the camera aimed through the ~2.5 s boot wait.

Examples
--------
  # confirm the board answers STATS before committing to a capture
  python capture_scores.py --port COM4 --probe

  # test 2, 20 s per scene, forcing MODE active so every frame is inferred
  python capture_scores.py --port COM4 --tag person --seconds 20 \
      --raw-log ../../C2_mcu/logs/scores_person.csv
  python capture_scores.py --port COM4 --tag wall --seconds 20 \
      --raw-log ../../C2_mcu/logs/scores_wall.csv

Exit codes: 0 = capture completed, 2 = probe failed, 3 = capture aborted
(stalled port or zero scores). Non-zero always means "do not trust a CSV".
"""
import argparse
import csv
import json
import statistics
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial not installed. Run: python -m pip install -r requirements.txt")

STALL_LIMIT = 5.0  # seconds with no parsed STATS before we give up


def open_serial(port, baud=115200):
    # Opening toggles DTR/RTS -> board resets. Wait out the ~1.3 s boot.
    ser = serial.Serial(port, baud, timeout=1)
    time.sleep(2.5)
    ser.reset_input_buffer()
    return ser


def send(ser, line):
    ser.write((line + "\n").encode())
    ser.flush()


def read_stats(ser, timeout=2.0):
    """Send STATS and return the parsed dict, or None on timeout/parse error."""
    send(ser, "STATS")
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = ser.readline().decode(errors="replace").strip()
        if raw.startswith("STATS "):
            try:
                return json.loads(raw[len("STATS "):])
            except json.JSONDecodeError:
                return None
    return None


def norm(int8_score):
    """int8 output tensor value -> [0,1] readability figure (q+128)/255."""
    return (int8_score + 128) / 255.0


def probe(ser):
    for attempt in range(1, 4):
        st = read_stats(ser)
        if st:
            print("STATS OK ->", json.dumps(st, separators=(",", ":")))
            return 0
        print(f"  no STATS on attempt {attempt}")
    print("PROBE FAILED: board did not answer STATS", file=sys.stderr)
    return 2


def capture(ser, tag, seconds, raw_log):
    send(ser, "MODE active")   # every frame inferred, no controller gating
    time.sleep(0.5)
    ser.reset_input_buffer()

    f = open(raw_log, "w", newline="")
    w = csv.writer(f)
    w.writerow(["host_time", "person", "noperson", "infer_count", "fps"])

    t0 = time.time()
    t_end = t0 + seconds
    last_ok = t0
    next_tick = t0 + 1.0
    scores = []          # every sample, whole run
    bucket = []          # samples inside the current 1 s display window
    last_infer = None

    try:
        while time.time() < t_end:
            st = read_stats(ser)
            now = time.time()
            if st:
                last_ok = now
                ps = int(st["person"])
                nps = int(st["noperson"])
                w.writerow([round(now, 3), ps, nps,
                            st["infer_count"], st["fps"]])
                f.flush()   # CSV stays valid even if the run is interrupted
                scores.append(ps)
                bucket.append(ps)
                last_infer = st["infer_count"]
            elif now - last_ok > STALL_LIMIT:
                print(f"\nABORT: no STATS for {now - last_ok:.1f} s "
                      f"(> {STALL_LIMIT:.0f} s limit) — stopping, not hanging.",
                      file=sys.stderr)
                f.close()
                return None

            if now >= next_tick:
                elapsed = int(round(next_tick - t0))
                if bucket:
                    m = statistics.fmean(bucket)
                    print(f"[{tag} {elapsed:02d}/{int(seconds)}s] "
                          f"score={m:+.1f}  p={norm(m):.2f}  "
                          f"n={len(bucket)}  infer={last_infer}", flush=True)
                else:
                    print(f"[{tag} {elapsed:02d}/{int(seconds)}s] "
                          f"score=--  (no sample this second)", flush=True)
                bucket = []
                next_tick += 1.0

            time.sleep(0.2)
    finally:
        f.close()

    if not scores:
        print("ABORT: captured zero scores.", file=sys.stderr)
        return None

    mean = statistics.fmean(scores)
    sd = statistics.stdev(scores) if len(scores) > 1 else 0.0
    print(f"\n== {tag}: n={len(scores)} mean={mean:+.2f} std={sd:.2f} "
          f"min={min(scores)} max={max(scores)} -> {raw_log}")
    return {"tag": tag, "n": len(scores), "mean": mean, "std": sd,
            "min": min(scores), "max": max(scores)}


def main():
    ap = argparse.ArgumentParser(
        description="person-vs-wall score capture for C2a acceptance test 2")
    ap.add_argument("--port", required=True, help="serial port, e.g. COM4")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--probe", action="store_true",
                    help="send STATS once and exit; use before a capture")
    ap.add_argument("--tag", default="person", help="label for progress lines")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--raw-log", help="output CSV (required for a capture run)")
    args = ap.parse_args()

    ser = open_serial(args.port, args.baud)
    print(f"Connected to {args.port} @ {args.baud}", flush=True)
    try:
        if args.probe:
            sys.exit(probe(ser))
        if not args.raw_log:
            ap.error("--raw-log is required for a capture run")
        res = capture(ser, args.tag, args.seconds, args.raw_log)
        sys.exit(0 if res else 3)
    finally:
        ser.close()


if __name__ == "__main__":
    main()
