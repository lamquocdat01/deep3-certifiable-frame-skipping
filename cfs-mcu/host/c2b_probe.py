#!/usr/bin/env python3
"""c2b_probe.py — send serial commands to cfs-mcu and log every byte returned.

Built for C2b step A (INA219 bring-up): the evidence for "the chip ACKs" is raw
serial output, so this driver does nothing clever — it sends the commands you
name and tees the board's replies to stdout and to a log file verbatim.

  python c2b_probe.py --port COM4 --out ../../C2_mcu/logs/probe.txt \
      --cmd "POWER PROBE" --cmd "POWER SCAN" --settle 3

  # 10 s of live streaming (POWER LIVE runs on the board for <secs>)
  python c2b_probe.py --port COM4 --out ../../C2_mcu/logs/live.txt \
      --cmd "POWER LIVE 10" --settle 13

Opening the port toggles DTR/RTS, which resets the board, so we wait out the
boot before sending anything. Exit code 0 = commands sent and output captured;
it makes no judgement about whether the readings are good.
"""
import argparse
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial not installed. Run: python -m pip install -r requirements.txt")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--cmd", action="append", required=True,
                    help="command to send (repeatable, in order)")
    ap.add_argument("--settle", type=float, default=3.0,
                    help="seconds to keep reading after each command")
    ap.add_argument("--boot-wait", type=float, default=3.0,
                    help="seconds to wait after opening (board resets)")
    ap.add_argument("--out", help="write the full transcript here")
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=0.2)
    buf = []

    def pump(seconds):
        t_end = time.time() + seconds
        while time.time() < t_end:
            data = ser.read(4096)
            if data:
                text = data.decode(errors="replace")
                sys.stdout.write(text)
                sys.stdout.flush()
                buf.append(text)

    print(f"[open {args.port} @ {args.baud}; waiting {args.boot_wait}s for boot]")
    pump(args.boot_wait)

    for c in args.cmd:
        banner = f"\n===== SEND: {c} =====\n"
        sys.stdout.write(banner)
        buf.append(banner)
        ser.write((c + "\n").encode())
        ser.flush()
        pump(args.settle)

    ser.close()

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write("".join(buf))
        print(f"\n[saved -> {args.out}]")


if __name__ == "__main__":
    main()
