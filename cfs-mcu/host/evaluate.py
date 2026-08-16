#!/usr/bin/env python3
"""evaluate.py — host-side driver for the cfs-mcu firmware.

Connects to the ESP32-S3 over serial, drives controller modes, polls STATS for
N seconds per mode, and writes a CSV. This is the same driver C2b will reuse
with the INA219 power columns (already present in STATS, zero until hardware).

Examples
--------
  # list serial ports
  python evaluate.py --list

  # acceptance run: active / idle / sweep k=10,5,2, 20 s each, to CSV
  python evaluate.py --port COM4 --acceptance --seconds 20 \
      --csv ../../C2_mcu/logs/acceptance_stats.csv

  # log raw person/no-person scores for 20 s (test 2: person vs wall)
  python evaluate.py --port COM4 --mode active --seconds 20 \
      --raw-log ../../C2_mcu/logs/scores_person.csv
"""
import argparse
import csv
import json
import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("pyserial not installed. Run: python -m pip install pyserial")

STATS_KEYS = [
    "mode", "R", "theta", "sweep_k", "fps", "open_frac", "frames", "opens",
    "infer_count", "infer_us_mean", "infer_us_max", "max_closed_run",
    "person", "noperson", "heap_free", "psram_free",
    "power_on", "ina219", "power_mw_mean", "power_samples",
]


def list_serial_ports():
    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports found.")
        return
    for p in ports:
        print(f"  {p.device:8s} {p.description}")


def open_serial(port, baud=115200):
    # Opening the port toggles DTR/RTS, which resets the board on these
    # auto-reset designs. Wait for the ~1.3 s boot before sending commands.
    ser = serial.Serial(port, baud, timeout=1)
    time.sleep(2.5)
    ser.reset_input_buffer()
    return ser


def send(ser, line, verbose=True):
    if verbose:
        print(f">>> {line}")
    ser.write((line + "\n").encode())
    ser.flush()


def read_stats(ser, timeout=2.0):
    """Send STATS and return the parsed dict, or None on timeout/parse error."""
    send(ser, "STATS", verbose=False)
    deadline = time.time() + timeout
    while time.time() < deadline:
        raw = ser.readline().decode(errors="replace").strip()
        if raw.startswith("STATS "):
            try:
                return json.loads(raw[len("STATS "):])
            except json.JSONDecodeError:
                return None
    return None


def collect(ser, seconds, period=0.5, writer=None, tag=""):
    """Poll STATS for `seconds`, optionally write each row. Return last stats."""
    t_end = time.time() + seconds
    last = None
    while time.time() < t_end:
        st = read_stats(ser)
        if st:
            last = st
            if writer:
                row = {k: st.get(k, "") for k in STATS_KEYS}
                row["tag"] = tag
                row["host_time"] = round(time.time(), 3)
                writer.writerow(row)
        time.sleep(period)
    return last


def set_mode(ser, mode, k=None, R=None, theta=None):
    if R is not None or theta is not None:
        parts = []
        if R is not None:
            parts.append(f"R={R}")
        if theta is not None:
            parts.append(f"THETA={theta}")
        send(ser, "SET " + " ".join(parts))
        time.sleep(0.2)
    cmd = f"MODE {mode}"
    if k is not None:
        cmd += f" k={k}"
    send(ser, cmd)
    time.sleep(0.3)


def summarize(tag, st):
    if not st:
        print(f"[{tag}] no STATS received")
        return
    print(f"[{tag}] fps={st['fps']:.1f} open_frac={st['open_frac']:.3f} "
          f"infer={st['infer_count']} mean_us={st['infer_us_mean']:.0f} "
          f"max_us={st['infer_us_max']} max_closed={st['max_closed_run']} "
          f"person={st['person']} noperson={st['noperson']} "
          f"psram_free={st['psram_free']}")


def make_writer(path):
    f = open(path, "w", newline="")
    w = csv.DictWriter(f, fieldnames=STATS_KEYS + ["tag", "host_time"])
    w.writeheader()
    return f, w


def run_acceptance(ser, seconds, csv_path):
    f, w = make_writer(csv_path)
    print(f"Writing acceptance CSV -> {csv_path}")
    plan = [
        ("active", dict(mode="active")),
        ("idle_R10", dict(mode="idle", R=10)),
        ("sweep_k10", dict(mode="sweep", k=10)),
        ("sweep_k5", dict(mode="sweep", k=5)),
        ("sweep_k2", dict(mode="sweep", k=2)),
    ]
    for tag, kw in plan:
        set_mode(ser, **kw)
        time.sleep(1.0)  # let the window fill
        st = collect(ser, seconds, writer=w, tag=tag)
        summarize(tag, st)
    f.close()
    print("Acceptance run complete.")


def run_single(ser, mode, k, R, theta, seconds, csv_path, raw_log):
    set_mode(ser, mode, k=k, R=R, theta=theta)
    writer = None
    fcsv = None
    if csv_path:
        fcsv, writer = make_writer(csv_path)
    fraw = None
    if raw_log:
        fraw = open(raw_log, "w", newline="")
        raww = csv.writer(fraw)
        raww.writerow(["host_time", "person", "noperson", "infer_count", "fps"])
    t_end = time.time() + seconds
    last = None
    while time.time() < t_end:
        st = read_stats(ser)
        if st:
            last = st
            if writer:
                row = {kk: st.get(kk, "") for kk in STATS_KEYS}
                row["tag"] = mode
                row["host_time"] = round(time.time(), 3)
                writer.writerow(row)
            if fraw:
                raww.writerow([round(time.time(), 3), st["person"],
                               st["noperson"], st["infer_count"], st["fps"]])
        time.sleep(0.3)
    summarize(mode, last)
    if fcsv:
        fcsv.close()
    if fraw:
        fraw.close()


def main():
    ap = argparse.ArgumentParser(description="cfs-mcu host evaluation driver")
    ap.add_argument("--list", action="store_true", help="list serial ports and exit")
    ap.add_argument("--port", help="serial port, e.g. COM4")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--acceptance", action="store_true",
                    help="run active/idle/sweep acceptance sequence")
    ap.add_argument("--mode", choices=["idle", "active", "gate", "sweep"])
    ap.add_argument("--k", type=int, help="sweep period k")
    ap.add_argument("--R", type=int, help="refresh period R")
    ap.add_argument("--theta", type=float, help="motion gate threshold")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--csv", help="write per-poll STATS rows to this CSV")
    ap.add_argument("--raw-log", help="write person/noperson scores to this CSV")
    args = ap.parse_args()

    if args.list:
        list_serial_ports()
        return
    if not args.port:
        ap.error("--port is required (or use --list)")

    ser = open_serial(args.port, args.baud)
    print(f"Connected to {args.port} @ {args.baud}")
    send(ser, "HELP")
    time.sleep(0.3)

    try:
        if args.acceptance:
            run_acceptance(ser, args.seconds, args.csv or "acceptance_stats.csv")
        elif args.mode:
            run_single(ser, args.mode, args.k, args.R, args.theta,
                       args.seconds, args.csv, args.raw_log)
        else:
            # just stream STATS
            st = collect(ser, args.seconds)
            summarize("stream", st)
    finally:
        ser.close()


if __name__ == "__main__":
    main()
