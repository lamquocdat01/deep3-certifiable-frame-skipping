#!/usr/bin/env python3
"""log_um24c.py — Bluetooth logger for the RD UM24C inline USB power meter (C2b).

The C2b measurement rule is that the board is NEVER connected to the PC while a
run is in progress: the board is powered from a charger through the meter, and
the PC talks only to the *meter*, over Bluetooth SPP. This script is that PC
side.

    charger 5V --> [UM24C] --> USB-C --> ESP32-S3          (power path)
                      |
                      +--- Bluetooth SPP ---> PC (this script)   (data path)

Usage
-----
Log a real run (meter paired, SPP port e.g. COM7)::

    python log_um24c.py --port COM7 --label idle-skip_run1 --seconds 330

Test the whole pipeline with no hardware at all::

    python log_um24c.py --simulate --label demo --seconds 60

Analyse an existing log (mean W over the kept window, and mJ/frame if the
firmware fps is supplied)::

    python log_um24c.py --analyze <csv> --fps 22.54
    python log_um24c.py --analyze <csv> --dump dump.csv --run-id 3

Output
------
One CSV per run in ``C2_mcu/c2b_meter_logs/`` with columns
``iso_time,volts,amps,watts``; the filename is ``<label>_<arm time>.csv``.

**Simulated runs are written to ``c2b_meter_logs/simulated/`` and every line is
tagged SIMULATED.** They exist only to exercise this code path. They are not a
measurement and must never be cited by a report or by the manuscript.

Instrument
----------
RD UM24C: 0.001 A current resolution, 0.01 V voltage resolution, ~2 Hz internal
refresh. Polling faster than ~2 Hz returns repeated registers, so the default
poll rate here is 1 Hz — comfortably below the refresh rate and matching the
USB-meter logging protocol used for the C2b runs.

Requires ``pyserial``; uses ``rdserialtool`` (``pip install rdserialtool``) to
decode frames when it is importable, and falls back to the built-in decoder
below otherwise. ``--simulate`` requires neither.
"""

import argparse
import csv
import datetime
import math
import os
import random
import statistics
import sys
import time

# --- meter constants ---------------------------------------------------------

UM24C_MODEL_ID = 0x0963
UM_POLL_BYTE = b"\xf0"
UM_FRAME_LEN = 130

# UM24C register scaling (UM25C differs — do not reuse these for a UM25C).
UM24C_VOLT_DIV = 100.0     # raw counts -> volts   (0.01 V resolution)
UM24C_AMP_DIV = 1000.0     # raw counts -> amps    (0.001 A resolution)
UM24C_WATT_DIV = 1000.0    # raw counts -> watts   (mW register)

# Plausibility gates from the C2b measurement protocol. Outside these, STOP and
# diagnose — do not "fix" a log by trimming it.
GATE_VOLT = (4.7, 5.3)
GATE_WATT = (0.2, 2.5)

DEFAULT_DISCARD_S = 30.0   # boot transient + warm-up


# --- decoding ----------------------------------------------------------------

def decode_frame_builtin(buf):
    """Decode a 130-byte UM24C reply. Returns (volts, amps, watts).

    Layout (big-endian), stable across UM24C firmware revisions:
        0..1   model id (0x0963)
        2..3   voltage, 0.01 V units
        4..5   current, 0.001 A units
        6..9   power,   0.001 W units
    """
    if len(buf) < 10:
        raise ValueError("short frame: %d bytes" % len(buf))
    model = int.from_bytes(buf[0:2], "big")
    if model != UM24C_MODEL_ID:
        raise ValueError(
            "model id 0x%04x is not a UM24C (0x%04x). Scaling differs between "
            "UM-series meters; refusing to guess." % (model, UM24C_MODEL_ID))
    volts = int.from_bytes(buf[2:4], "big") / UM24C_VOLT_DIV
    amps = int.from_bytes(buf[4:6], "big") / UM24C_AMP_DIV
    watts = int.from_bytes(buf[6:10], "big") / UM24C_WATT_DIV
    return volts, amps, watts


def decode_frame_rdserial(buf):
    """Decode via rdserialtool if it is installed. Returns None if unavailable."""
    try:
        import rdserial.um  # noqa: F401  (part of the rdserialtool distribution)
    except ImportError:
        return None
    try:
        r = rdserial.um.Response(buf)
        return float(r.volts), float(r.amps), float(r.watts)
    except Exception as exc:                      # pragma: no cover - device path
        raise ValueError("rdserial could not decode the frame: %s" % exc)


def decode_frame(buf, prefer_rdserial=True):
    if prefer_rdserial:
        out = decode_frame_rdserial(buf)
        if out is not None:
            return out
    return decode_frame_builtin(buf)


def rdserial_available():
    try:
        import rdserial.um  # noqa: F401
        return True
    except ImportError:
        return False


# --- sampling sources --------------------------------------------------------

class MeterSource:
    """Polls a real UM24C over a Bluetooth SPP serial port."""

    kind = "UM24C"

    def __init__(self, port, baud=9600, timeout=3.0):
        import serial  # imported lazily so --simulate needs no pyserial install
        self.ser = serial.Serial(port, baud, timeout=timeout)
        self.port = port
        # The meter answers a poll with a full frame; drain anything stale first.
        self.ser.reset_input_buffer()

    def read(self):
        self.ser.reset_input_buffer()
        self.ser.write(UM_POLL_BYTE)
        self.ser.flush()
        buf = self.ser.read(UM_FRAME_LEN)
        if len(buf) < UM_FRAME_LEN:
            raise IOError("meter returned %d/%d bytes — check the SPP pairing "
                          "and that the meter is powered" % (len(buf), UM_FRAME_LEN))
        return decode_frame(buf)

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


class SimulatedSource:
    """Synthetic 5 V / 100 mA source with noise, quantised like a real UM24C.

    Exists so the CSV -> mean W -> mJ/frame pipeline can be exercised before the
    meter arrives. Values are invented and are labelled as such everywhere.
    """

    kind = "SIMULATED"

    def __init__(self, seed=20260731, volts=5.0, amps=0.100):
        self.rng = random.Random(seed)
        self.v0 = volts
        self.a0 = amps

    def read(self):
        v = self.v0 + self.rng.gauss(0.0, 0.010)
        a = self.a0 + self.rng.gauss(0.0, 0.004)
        # Quantise to the instrument's real resolution so the downstream stats
        # see the same granularity they will see on hardware.
        v = round(v * UM24C_VOLT_DIV) / UM24C_VOLT_DIV
        a = round(a * UM24C_AMP_DIV) / UM24C_AMP_DIV
        w = round(v * a * UM24C_WATT_DIV) / UM24C_WATT_DIV
        return v, a, w


# --- logging -----------------------------------------------------------------

def default_outdir(script_dir):
    # cfs-mcu/host/ -> Revision_IoTJ/C2_mcu/c2b_meter_logs
    return os.path.normpath(
        os.path.join(script_dir, "..", "..", "C2_mcu", "c2b_meter_logs"))


def log_run(source, label, seconds, rate_hz, outdir):
    simulated = (source.kind == "SIMULATED")
    if simulated:
        outdir = os.path.join(outdir, "simulated")
    os.makedirs(outdir, exist_ok=True)

    arm_time = datetime.datetime.now()
    stamp = arm_time.strftime("%Y%m%dT%H%M%S")
    name = "%s_%s.csv" % (label, stamp)
    if simulated:
        name = "SIMULATED_" + name
    path = os.path.join(outdir, name)

    period = 1.0 / rate_hz
    n_target = int(round(seconds * rate_hz))

    print("[%s] logging '%s' for %g s at %g Hz -> %s"
          % (source.kind, label, seconds, rate_hz, path))
    if simulated:
        print("    *** SIMULATED DATA — invented numbers, not a measurement. ***")

    rows = []
    t0 = time.time()
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["iso_time", "volts", "amps", "watts"])
        for i in range(n_target):
            target = t0 + i * period
            delay = target - time.time()
            if delay > 0:
                time.sleep(delay)
            try:
                volts, amps, watts = source.read()
            except Exception as exc:
                print("ERROR at sample %d: %s" % (i, exc), file=sys.stderr)
                print("Log truncated at %d samples; the run is NOT usable and "
                      "must be repeated." % i, file=sys.stderr)
                break
            iso = datetime.datetime.now().isoformat(timespec="milliseconds")
            w.writerow([iso, "%.3f" % volts, "%.3f" % amps, "%.4f" % watts])
            rows.append((iso, volts, amps, watts))
            fh.flush()
            if (i + 1) % 30 == 0 or i == 0:
                print("    t=%5.1fs  V=%.3f  A=%.3f  W=%.4f"
                      % (time.time() - t0, volts, amps, watts))

    print("[%s] wrote %d samples to %s" % (source.kind, len(rows), path))
    return path


# --- analysis ----------------------------------------------------------------

def read_log(path):
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append((
                datetime.datetime.fromisoformat(row["iso_time"]),
                float(row["volts"]), float(row["amps"]), float(row["watts"])))
    if not out:
        raise ValueError("%s contains no samples" % path)
    return out


def fps_from_dump(dump_path, run_id):
    """Pull fps and counters for one run_id out of a firmware DUMP CSV.

    Accepts the raw serial capture: lines are prefixed 'DUMP,' by the firmware,
    and the surrounding 'DUMP begin/end' lines are ignored.
    """
    with open(dump_path, newline="", encoding="utf-8") as fh:
        lines = [ln.strip() for ln in fh if ln.strip()]
    body = [ln[len("DUMP,"):] for ln in lines if ln.startswith("DUMP,")]
    if not body:
        body = [ln for ln in lines if "," in ln]
    if not body:
        raise ValueError("no CSV rows found in %s" % dump_path)
    reader = csv.DictReader(body)
    for row in reader:
        if int(row["run_id"]) == run_id:
            return row
    raise ValueError("run_id %d not present in %s" % (run_id, dump_path))


def analyse(path, discard_s, fps=None, dump=None, run_id=None, quiet=False):
    rows = read_log(path)
    t0 = rows[0][0]
    kept = [r for r in rows if (r[0] - t0).total_seconds() >= discard_s]
    simulated = os.path.basename(path).startswith("SIMULATED_") \
        or os.sep + "simulated" + os.sep in path

    print("")
    print("=" * 68)
    print("ANALYSIS: %s" % path)
    if simulated:
        print("*** SIMULATED — these numbers are invented. Never cite them. ***")
    print("=" * 68)
    print("samples total        : %d" % len(rows))
    print("discarded (first %gs) : %d" % (discard_s, len(rows) - len(kept)))
    print("samples kept         : %d" % len(kept))
    if not kept:
        print("NOTHING LEFT after the discard window — run longer.")
        return None

    volts = [r[1] for r in kept]
    watts = [r[3] for r in kept]
    v_mean = statistics.fmean(volts)
    w_mean = statistics.fmean(watts)
    w_std = statistics.stdev(watts) if len(watts) > 1 else 0.0
    span = (kept[-1][0] - kept[0][0]).total_seconds()

    print("window length        : %.1f s" % span)
    print("V mean               : %.4f  (min %.3f, max %.3f)"
          % (v_mean, min(volts), max(volts)))
    print("W mean +/- std       : %.4f +/- %.4f  (min %.4f, max %.4f)"
          % (w_mean, w_std, min(watts), max(watts)))

    ok = True
    if not (GATE_VOLT[0] <= v_mean <= GATE_VOLT[1]):
        print("GATE FAIL: mean V %.3f outside %s — STOP and diagnose"
              % (v_mean, GATE_VOLT))
        ok = False
    if not (GATE_WATT[0] <= w_mean <= GATE_WATT[1]):
        print("GATE FAIL: mean W %.3f outside %s — STOP and diagnose"
              % (w_mean, GATE_WATT))
        ok = False
    if ok:
        print("plausibility gates   : PASS (V in %s, W in %s)"
              % (GATE_VOLT, GATE_WATT))

    if dump is not None and run_id is not None:
        row = fps_from_dump(dump, run_id)
        fps = float(row["fps"])
        print("")
        print("paired firmware run  : run_id=%s mode=%s frames=%s opens=%s "
              "infer=%s elapsed_ms=%s"
              % (row["run_id"], row["mode"], row["frames"], row["opens"],
                 row["infer_count"], row["elapsed_ms"]))
        print("open fraction a      : %s" % row["open_frac"])

    if fps:
        mj_per_frame = w_mean / fps * 1000.0
        print("")
        print("mJ/frame             = W_mean / fps * 1000")
        print("                     = %.4f W / %.2f fps * 1000" % (w_mean, fps))
        print("                     = %.2f mJ/frame" % mj_per_frame)
        if w_std > 0:
            print("  (+/- %.2f mJ/frame from the within-run W spread alone)"
                  % (w_std / fps * 1000.0))
        if simulated:
            print("  *** SIMULATED — illustrates the arithmetic only. ***")
        return mj_per_frame
    return w_mean


# --- main --------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Log / analyse RD UM24C power over Bluetooth for C2b.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="Bluetooth SPP COM port of the UM24C")
    ap.add_argument("--label", default="run",
                    help="run label; becomes the filename prefix")
    ap.add_argument("--seconds", type=float, default=330.0,
                    help="run length (default 330 = 5 min + 30 s discard)")
    ap.add_argument("--rate", type=float, default=1.0,
                    help="poll rate in Hz (default 1.0; meter refreshes ~2 Hz)")
    ap.add_argument("--simulate", action="store_true",
                    help="synthesise 5V/100mA instead of reading a meter; "
                         "output goes to c2b_meter_logs/simulated/")
    ap.add_argument("--outdir", default=None,
                    help="override the output directory")
    ap.add_argument("--analyze", metavar="CSV",
                    help="analyse an existing log instead of recording")
    ap.add_argument("--discard", type=float, default=DEFAULT_DISCARD_S,
                    help="seconds to discard from the start (default 30)")
    ap.add_argument("--fps", type=float, default=None,
                    help="firmware fps for the mJ/frame computation")
    ap.add_argument("--dump", default=None,
                    help="firmware DUMP CSV to take fps from")
    ap.add_argument("--run-id", type=int, default=None,
                    help="run_id to select inside --dump")
    ap.add_argument("--no-analyze", action="store_true",
                    help="record only; skip the analysis pass")
    args = ap.parse_args()

    if args.analyze:
        analyse(args.analyze, args.discard, args.fps, args.dump, args.run_id)
        return 0

    if args.simulate:
        source = SimulatedSource()
    else:
        if not args.port:
            ap.error("--port is required unless --simulate is given")
        print("rdserialtool: %s"
              % ("available (used for decoding)" if rdserial_available()
                 else "NOT installed — using the built-in UM24C decoder "
                      "(pip install rdserialtool to use it)"))
        source = MeterSource(args.port)

    outdir = args.outdir or default_outdir(os.path.dirname(os.path.abspath(__file__)))
    try:
        path = log_run(source, args.label, args.seconds, args.rate, outdir)
    finally:
        if hasattr(source, "close"):
            source.close()

    if not args.no_analyze:
        analyse(path, args.discard, args.fps, args.dump, args.run_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
