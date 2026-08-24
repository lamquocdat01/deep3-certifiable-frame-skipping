#!/usr/bin/env python3
"""c2b_dryrun.py — execute the C2b Setup-item-1 acceptance on PC power.

This is the C2b Setup item-1 acceptance for the USB-meter protocol,
automated end to end so it costs one command when the board is connected:

  (a) arm `MEASURE idle-skip 30 on-boot`, reboot, DUMP -> exactly one new
      summary row, fps in the C2a idle ballpark
  (b) same for `active`   (fps ~ 12-14)
      and  for `ctrl-k5`  (opens/frames ~ 0.2)
  (c) C2a regression probe: plain `MODE idle` still gives fps ~ 22.5,
      open_frac ~ 0.10, max_closed_run == R-1

Nothing here needs the power meter. The board is on PC USB the whole time.

    python c2b_dryrun.py --port COM4
    python c2b_dryrun.py --port COM4 --keep      # do not CLEAR at the start

Writes a full transcript to C2_mcu/logs/ and prints PASS/FAIL per check.
"""

import argparse
import csv
import datetime
import json
import os
import sys
import time

import serial

BAUD = 115200

# Expectations. Ranges are deliberately loose: this is a "did the plumbing
# work" check, not a measurement. The tight numbers live in C2A_REPORT.
EXPECT = {
    "idle-skip": {"fps": (18.0, 31.0), "open_frac": (0.0, 0.0001), "infer": 0},
    "active":    {"fps": (11.0, 15.0), "open_frac": (0.99, 1.0001)},
    "ctrl-k5":   {"fps": (16.0, 23.0), "open_frac": (0.18, 0.22)},
}
C2A_IDLE = {"fps": (20.0, 24.5), "open_frac": (0.09, 0.115), "max_closed_run": 9}


class Board:
    def __init__(self, port, transcript):
        self.ser = serial.Serial(port, BAUD, timeout=1.0)
        self.transcript = transcript

    def _log(self, text):
        self.transcript.write(text)
        self.transcript.flush()

    def send(self, line):
        self._log("\n>>> %s\n" % line)
        print(">>> %s" % line)
        self.ser.reset_input_buffer()
        self.ser.write((line + "\n").encode())
        self.ser.flush()

    def collect(self, seconds, until=None):
        """Read lines for `seconds`, stopping early if `until` matches one."""
        out = []
        t_end = time.time() + seconds
        while time.time() < t_end:
            raw = self.ser.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", "replace").rstrip()
            out.append(line)
            self._log(line + "\n")
            if until and until in line:
                break
        return out

    def reboot(self):
        """Hardware reset via DTR/RTS, the same sequence esptool uses."""
        self._log("\n--- reboot (DTR/RTS reset) ---\n")
        print("--- rebooting board ---")
        self.ser.setDTR(False)
        self.ser.setRTS(True)
        time.sleep(0.15)
        self.ser.setRTS(False)
        time.sleep(0.15)
        self.ser.setDTR(False)

    def close(self):
        self.ser.close()


def parse_stats(lines):
    for line in reversed(lines):
        i = line.find("STATS {")
        if i >= 0:
            try:
                return json.loads(line[i + len("STATS "):])
            except json.JSONDecodeError:
                continue
    return None


def parse_dump(lines):
    body = []
    for line in lines:
        i = line.find("DUMP,")
        if i >= 0:
            body.append(line[i + len("DUMP,"):])
    if len(body) < 2:
        return []
    return list(csv.DictReader(body))


def check(name, value, lo_hi, results, fmt="%.4f"):
    lo, hi = lo_hi
    ok = value is not None and lo <= value <= hi
    shown = (fmt % value) if value is not None else "None"
    print("    [%s] %-16s = %s   (expect %.4g..%.4g)"
          % ("PASS" if ok else "FAIL", name, shown, lo, hi))
    results.append((name, ok))
    return ok


def run_measure(board, mode, seconds, results):
    print("\n=== %s: arm %d s, reboot, run, DUMP ===" % (mode, seconds))
    board.send("MEASURE %s %d on-boot" % (mode, seconds))
    board.collect(2.0)

    board.send("MEASURE status")
    status = board.collect(2.0)
    armed = any("MEASURE armed" in ln and mode in ln for ln in status)
    print("    [%s] %-16s" % ("PASS" if armed else "FAIL", "armed in NVS"))
    results.append(("%s: armed" % mode, armed))

    before = dump_rows(board)
    board.reboot()
    # boot (~2 s) + the run + NVS write + slack
    board.collect(seconds + 12.0, until="MEASURE done")
    after = dump_rows(board)

    new = [r for r in after if r not in before]
    exactly_one = len(new) == 1
    print("    [%s] %-16s = %d new row(s)"
          % ("PASS" if exactly_one else "FAIL", "one summary", len(new)))
    results.append(("%s: one summary row" % mode, exactly_one))
    if not exactly_one:
        return None

    row = new[0]
    print("    row: %s" % row)
    mode_ok = row["mode"] == mode
    print("    [%s] %-16s = %s" % ("PASS" if mode_ok else "FAIL", "mode", row["mode"]))
    results.append(("%s: mode recorded" % mode, mode_ok))

    exp = EXPECT[mode]
    check("%s fps" % mode, float(row["fps"]), exp["fps"], results, "%.2f")
    check("%s open_frac" % mode, float(row["open_frac"]), exp["open_frac"],
          results)
    if "infer" in exp:
        got = int(row["infer_count"])
        ok = got == exp["infer"]
        print("    [%s] %-16s = %d   (expect %d)"
              % ("PASS" if ok else "FAIL", "infer_count", got, exp["infer"]))
        results.append(("%s: infer_count" % mode, ok))
    return row


def dump_rows(board):
    board.send("DUMP")
    return parse_dump(board.collect(6.0, until="DUMP end"))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", required=True, help="board serial port, e.g. COM4")
    ap.add_argument("--seconds", type=int, default=30,
                    help="run length for each armed mode (default 30)")
    ap.add_argument("--keep", action="store_true",
                    help="do not CLEAR stored summaries before starting")
    ap.add_argument("--logdir", default=None)
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    logdir = args.logdir or os.path.normpath(
        os.path.join(here, "..", "..", "C2_mcu", "logs"))
    os.makedirs(logdir, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
    logpath = os.path.join(logdir, "c2b_fw2_dryrun_%s.txt" % stamp)

    results = []
    with open(logpath, "w", encoding="utf-8") as transcript:
        board = Board(args.port, transcript)
        try:
            board.reboot()
            board.collect(6.0)

            board.send("HELP")
            help_lines = board.collect(2.0)
            has_cmds = any("MEASURE" in ln for ln in help_lines)
            print("[%s] firmware exposes MEASURE/DUMP/CLEAR"
                  % ("PASS" if has_cmds else "FAIL"))
            results.append(("HELP lists C2b commands", has_cmds))

            if not args.keep:
                board.send("CLEAR")
                board.collect(3.0)

            for mode in ("idle-skip", "active", "ctrl-k5"):
                run_measure(board, mode, args.seconds, results)

            # --- (c) C2a regression probe -------------------------------------
            print("\n=== C2a regression probe: MODE idle, R=10 ===")
            board.send("SET R=10 THETA=8.0")
            board.collect(2.0)
            board.send("MODE idle")
            board.collect(2.0)
            time.sleep(20)          # let the window accumulate
            board.send("STATS")
            st = parse_stats(board.collect(3.0))
            if st is None:
                print("    [FAIL] no STATS line")
                results.append(("C2a probe: STATS", False))
            else:
                print("    %s" % json.dumps(st))
                check("c2a fps", st["fps"], C2A_IDLE["fps"], results, "%.2f")
                check("c2a open_frac", st["open_frac"], C2A_IDLE["open_frac"],
                      results)
                mcr_ok = st["max_closed_run"] == C2A_IDLE["max_closed_run"]
                print("    [%s] %-16s = %d   (expect %d == R-1)"
                      % ("PASS" if mcr_ok else "FAIL", "max_closed_run",
                         st["max_closed_run"], C2A_IDLE["max_closed_run"]))
                results.append(("C2a probe: max_closed_run == R-1", mcr_ok))
                un_parked = (st["parked"] == 0 and st["infer_enabled"] == 1
                             and st["meas_running"] == 0)
                print("    [%s] %-16s (parked=0 infer_enabled=1 meas_running=0)"
                      % ("PASS" if un_parked else "FAIL", "state restored"))
                results.append(("C2a probe: state restored by MODE", un_parked))
        finally:
            board.close()

    npass = sum(1 for _, ok in results if ok)
    print("\n" + "=" * 60)
    for name, ok in results:
        print("  %-45s %s" % (name, "PASS" if ok else "FAIL"))
    print("=" * 60)
    print("%d/%d checks passed" % (npass, len(results)))
    print("transcript: %s" % logpath)
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
