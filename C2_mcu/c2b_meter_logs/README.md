# c2b_meter_logs — measurement of record for the ESP32-S3 energy constants

One CSV per run, written by `cfs-mcu/host/log_um24c.py`:

| column | meaning |
|---|---|
| `iso_time` | host wall clock of the sample |
| `volts` | meter bus voltage (UM24C, 0.01 V resolution) |
| `amps` | meter current (UM24C, 0.001 A resolution) |
| `watts` | meter power register |

Filename is `<run label>_<arm time>.csv`, e.g. `active_run2_20260802T101500.csv`.

Firmware `DUMP` captures (fps and activation counters for the same runs) live
alongside them as `dump_<date>.csv`.

## `simulated/`

**Everything under `simulated/` is invented.** It was generated with
`log_um24c.py --simulate` to exercise the CSV → mean W → mJ/frame pipeline
before the meter arrived. Those files are prefixed `SIMULATED_` and every
analysis line they produce is tagged.

They are **not** a measurement and are **never** cited by `C2B_REPORT.md`, the
response letter, or the manuscript. The two `[TBD-C2b]` cells in Table 3 and the
⟨X⟩/⟨Y⟩ placeholders in the response letter stay visibly unfilled until real
meter runs exist in this directory.
