# cfs-mcu — ESP32-S3 firmware bring-up (Reviewer 2, comment 1)

TinyML person detection behind the paper's **R-refresh frame-skipping**
controller on an **ESP32-S3 CAM WROOM-1 N16R8** (16 MB flash, 8 MB Octal PSRAM),
with a host-side evaluation driver. Power measurement (INA219) is C2b — the
driver and serial command are already here behind a compile-time flag, inert
until the hardware arrives.

Paper: *Certifiable Worst-Case Detection Latency…* (IoT-J IoT-68470-2026).

---

## Layout

```
cfs-mcu/
  CMakeLists.txt          project
  sdkconfig.defaults      esp32s3, flash 16MB QIO, PSRAM Octal(OPI), 1ms tick
  partitions.csv          3 MB app / 1 MB spiffs
  main/
    app_main.cc           boot + capture→controller→inference loop (30 fps)
    app_camera.*          autodetect pin map + sensor (OV2640/OV3660), 96x96 gray
    camera_pins.h         GOOUUU (primary) + Freenove (fallback) maps
    controller.*          R-refresh + motion gate (the paper's policy)
    serial_cmd.*          MODE / SET / STATS / POWER over UART0 @115200
    ina219.*              INA219 driver, gated on CONFIG_CFS_HAS_INA219
    cfs_runtime.h         shared state
    model/                vendored TFLM model (fetched, see README_MODEL.md)
    Kconfig.projbuild     CFS_HAS_INA219 + INA219 pins/addr
  host/
    evaluate.py           pyserial driver → CSV (C2b adds power columns)
    requirements.txt
```

---

## Build / flash / monitor

Prereq: **ESP-IDF v5.x** exported in the shell (`idf.py --version` works) and the
board on a COM port (here **COM4**, CH343 USB-serial).

```powershell
cd cfs-mcu
idf.py set-target esp32s3          # first time: downloads managed components
idf.py reconfigure                 # populate managed_components/
powershell -ExecutionPolicy Bypass -File main/model/fetch_model.ps1
idf.py build
idf.py -p COM4 flash monitor       # Ctrl-] to exit monitor
```

Boot log must show **PSRAM 8 MB Octal(OPI)** and the detected camera model
(acceptance test 1). If the camera fails to init, the classic cause on N16R8 is
**PSRAM set to Quad instead of Octal** — check `sdkconfig` first
(`CONFIG_SPIRAM_MODE_OCT=y`).

---

## Serial command interface (115200, newline-terminated)

| Command | Effect |
|---|---|
| `MODE idle` | capture + skip, open only on hard R-refresh → open-fraction ≈ 1/R |
| `MODE active` | inference every frame → open-fraction ≈ 1.0 |
| `MODE gate` | motion gate (frame diff θ) + R-refresh safety net |
| `MODE sweep k=<n>` | duty-cycle: open every n-th frame → open-fraction ≈ 1/n |
| `SET R=<n> THETA=<f>` | set refresh period / motion threshold |
| `STATS` | one `STATS {json}` line: fps, open_frac, infer_count, mean/max infer µs, max_closed_run, person/noperson score, heap/PSRAM free, power |
| `POWER on\|off` | enable INA219 sampling (needs C2b build+hardware) |
| `HELP` | list commands |

`STATS` emits a single JSON line prefixed `STATS ` for the host parser; all
other output is human-readable log.

---

## Controller notes (the paper's policy)

- **Hard R-refresh** uses `frames_since_open >= R` (pre-incremented), **not `>`**.
  `>` lets the closed run reach `R` (leaking one extra skipped frame) — the
  "leak-then-fix" bug corrected in the camera-ready. With `>=` the max closed
  run is exactly `R-1` and the open fraction is exactly `1/R`. See
  `controller.cc`; the firmware logs a WARN if the invariant is ever violated,
  and `STATS.max_closed_run` lets the host assert it.
- **Motion gate**: mean-absolute-difference of the current vs previous 96×96
  luma frame; OPEN if `MAD > θ` (default θ=8.0) OR the R-refresh fires.

---

## Host driver

```powershell
cd cfs-mcu/host
python -m pip install -r requirements.txt
python evaluate.py --list                       # find the port
python evaluate.py --port COM4 --acceptance --seconds 20 \
    --csv ../../C2_mcu/logs/acceptance_stats.csv
# person-vs-wall score logging (acceptance test 2):
python evaluate.py --port COM4 --mode active --seconds 20 \
    --raw-log ../../C2_mcu/logs/scores_person.csv
```

---

## Pin map used

Autodetected at boot; the firmware tries **GOOUUU** then **Freenove** and prints
`Camera: pinmap=<name> sensor=<model>`. Both candidate maps leave **GPIO1/GPIO2
free** for the INA219 I2C bus, so no INA219 pin change is expected.

> **Deviation log (fill from the boot log):**
> - Pin map that worked: `__________`
> - Sensor detected: `OV2640 / OV3660 = __________`
> - INA219 GPIO change (if any): `none expected — GPIO1/2 free in both maps`

---

## INA219 (C2b, pending hardware)

Compiled inert. To enable once wired: `idf.py menuconfig` →
*CFS-MCU configuration* → enable **INA219 power sensor present**, set SDA/SCL
(default GPIO1/GPIO2) and address (0x40). `POWER on` then accumulates mean mW,
reported in `STATS.power_mw_mean`. Wiring: see
`Revision_IoTJ/HuongDan_LapMach_MCU.md`.

---

## Acceptance checklist → evidence

1. Boot log shows PSRAM 8 MB Octal + camera model → save monitor log to `C2_mcu/logs/`.
2. Person vs empty wall: scores separate visibly → `scores_person.csv` / `scores_wall.csv`.
3. Controller: active open_frac≈1.0; idle open_frac≈1/R with max_closed_run==R−1;
   sweep k=10/5/2 → 0.1/0.2/0.5 → `acceptance_stats.csv`.
4. Fill `Revision_IoTJ/C2_mcu/C2A_REPORT.md` from the logs. **No number that is
   not traceable to a serial log under `C2_mcu/logs/`.**
