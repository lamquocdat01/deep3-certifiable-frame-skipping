#!/usr/bin/env python3
"""capture_boot.py — reset the ESP32-S3 and capture the boot log for N seconds.

Used to grab the boot banner (PSRAM size + camera model, acceptance test 1)
non-interactively, since `idf.py monitor` is interactive.

  python capture_boot.py --port COM4 --seconds 12 \
      --out ../../C2_mcu/logs/boot_monitor.txt
"""
import argparse
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("pyserial not installed. Run: python -m pip install pyserial")


def reset_board(ser):
    # ESP32 auto-reset: pulse DTR/RTS. EN is driven by these lines on most boards.
    ser.setDTR(False)
    ser.setRTS(True)   # EN low -> reset
    time.sleep(0.1)
    ser.setRTS(False)  # release EN
    time.sleep(0.05)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--seconds", type=float, default=12.0)
    ap.add_argument("--out", help="write captured log to this file")
    args = ap.parse_args()

    ser = serial.Serial(args.port, args.baud, timeout=0.2)
    reset_board(ser)
    ser.reset_input_buffer()

    buf = []
    t_end = time.time() + args.seconds
    print(f"Capturing {args.seconds}s from {args.port}...")
    while time.time() < t_end:
        data = ser.read(4096)
        if data:
            text = data.decode(errors="replace")
            sys.stdout.write(text)
            sys.stdout.flush()
            buf.append(text)
    ser.close()

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write("".join(buf))
        print(f"\n[saved -> {args.out}]")


if __name__ == "__main__":
    main()
