# Certifiable Worst-Case Detection Latency for Energy-Efficient Frame-Skipping at the Edge

Evaluation harness, measurement logs and microcontroller firmware for the
manuscript *"Certifiable Worst-Case Detection Latency for Energy-Efficient
Frame-Skipping at the Edge"* (IEEE Internet of Things Journal, manuscript
IoT-68470-2026).

Single author: Lam Quoc Dat, School of Business and Technology (FSB), FPT
University, Ho Chi Minh City, Vietnam · ORCID 0009-0004-5432-9343.

---

## What is here, and what it reproduces

Every number, figure and table in the paper that is not a closed-form
theoretical quantity is produced by one of the scripts below. Figure numbers are
the numbers **as printed in the paper**; the file names on disk kept their
working numbers from the revision (e.g. `fig11_sota_certificates.pdf` is
Figure 10).

| Paper artifact | Produced by | Output on disk |
|---|---|---|
| Fig. 2 — phase robustness, perturbation band | `A1_phase/sim_phase.py` | `A1_phase/a1_results.json` → `figures/fig8_phase_robustness.pdf` |
| Fig. 3 — alignment threshold `q_in*(q_out)`, per-dataset operating points | `A2_gate/analyze_alignment.py` | `A2_gate/a2_results.json` → `figures/fig9_alignment_threshold.pdf` |
| Sec. V-B — dependence-robust budgets (88.0 % → 97.3 % coverage) | `A3_clustering/analyze_clustering.py` | `A3_clustering/a3_results.json` |
| Sec. V-C — detector-composition bounds | `A4_detector/analyze_detector.py` | `A4_detector/a4_results.json` |
| **Table IV** — ablation and baselines at matched activation, and Fig. 10 | `B1_sota/b1_ablation_sota.py`, then `B1_sota/make_table4.py` | `B1_sota/b1_results.json`, `B1_sota/b1_table.csv`, `table4_ablation.tex`, `figures/fig11_sota_certificates.pdf` |
| Fig. 11 — advantage vs. event density (76 % → 1 %), VIRAT-P point | `B2_density/b2_dilution.py` | `B2_density/b2_results.json` → `figures/fig10_density_advantage.pdf` |
| **Table III** rows for the Jetson Orin Nano; `W(a) = 4.94 + 6.92a`, `R² = 0.999` | `C1_orin/c1_run.py`, `c1_orchestrate.py`, `c1b_orchestrate.py`, `analyze_c1.py`, `analyze_c1b.py` | `C1_orin/c1_orin_results.csv`, `computed_values*.json`, raw rails in `c1_power_logs/`, `c1b_power_logs/` |
| **Table III** row for the ESP32-S3; κ = 269; on-device refresh certificate | firmware in `cfs-mcu/`, host tools in `cfs-mcu/host/`, logs in `C2_mcu/logs/` and `C2_mcu/c2b_meter_logs/` | `C2_mcu/logs/acceptance_stats.csv`, `scores_person.csv`, `scores_wall.csv`, INA219 campaign CSV |
| Fig. 12 — price of certifiability vs. κ | `figures/make_revision_figures.py` | `figures/fig12_kappa_price.pdf` |

`figures/make_revision_figures.py` renders Figs. 2, 3, 10, 11 and 12 from the
JSON/CSV results above; it does not recompute them.

## Data you need

* **Not needed for most results.** The scheduling results (Table IV, Figs. 2, 3,
  10, 11) run from committed per-event tables — `frame_scores.parquet`,
  `events_gated.csv`, `events_durations.csv` — produced once from the source
  videos. Point `PROC` in `B1_sota/b1_ablation_sota.py` and
  `figures/make_revision_figures.py` at that directory.
* **Raw video** is needed only to regenerate those tables. All footage comes
  from publicly released surveillance benchmarks distributed for research use:
  CDnet2014, LASIESTA, BMC, and the VIRAT ground-camera sequences. No new data
  were collected, no identity recognition was performed, and every analysis is
  at the frame level over object classes rather than over individuals.
* The evaluation population is **121 videos / 3,713 events** across the three
  original datasets; the VIRAT-P variant (10 sequences, 41,823 frames, 1,119
  events) carries the low-density evaluation only. Ten stale 500-frame VIRAT
  stub timelines are filtered at load time in `b1_ablation_sota.py` — that
  filter is why the ablation runs on exactly the population Setup and Table I
  report.

## Event generation detector

The per-frame labels `g_t` behind the 121-video corpus (CDnet2014, LASIESTA,
BMC; 3,713 events) come from always-on detections of **YOLO26s-seg**
(Ultralytics, COCO-trained), run on CPU in FP32 at `imgsz = 640` with confidence
threshold 0.25. The paper's Sec. VII (Setup) names this detector; the hardware
energy table uses YOLOv3-class and YOLO26s workloads as listed there.

## Hardware measurements

* **Jetson Orin Nano 8 GB @ 15 W**, onboard INA3221 on the VDD_IN rail, 10 Hz,
  three 5-minute runs per point, run-to-run spread < 2 %; two detectors
  (YOLOv3-class @ 416², YOLO26s @ 640²) under two runtimes (ONNX Runtime CUDA,
  TensorRT fp16). Raw per-sample CSVs are committed.
* **ESP32-S3 + OV3660**, TFLM MobileNetV1-96 int8. Energy measured with an
  INA219 high-side current-sense amplifier (0.1 Ω shunt) in series with the 5 V
  input to the board (whole-board convention). Sampling is on-device — 128-sample
  hardware averaging (68.1 ms per channel) read every 140 ms — with the host PC
  disconnected for the duration of each run, so the USB-serial bridge draws no
  current inside the sense path. Twelve 330 s runs; the first 30 s of each is
  discarded as warm-up, leaving a five-minute window.
* The refresh certificate is enforced **in firmware** and checked on the device:
  in skip mode the measured open fraction is 1/R with a longest closed run of
  exactly R−1, and an activation sweep reproduces open fractions 0.102, 0.200 and
  0.502 for k = 10, 5, 2 with longest closed runs 9, 4 and 1.

`cfs-mcu/` is an ESP-IDF v5.4.4 project. Build output (`build/`) and the
third-party components pinned by `dependencies.lock` (`managed_components/`) are
not committed; `idf.py build` restores both.

## Environment

Python 3.11 with `numpy`, `pandas`, `pyarrow`, `matplotlib`. Figures are
rendered with the Okabe–Ito palette at IEEE column widths; `matplotlib` uses the
`Agg` backend, so no display is required.

## R1 additions (revision of 16 September 2026)

`R1_additions/` holds the analyses added in the IEEE IoT-J R1 revision, with
their JSON output committed alongside so every number the revised paper prints
can be traced to the script that produced it:

| file | answers | headline |
|---|---|---|
| `analyze_mdep.py` -> `a5_results.json` | reviewer comment on the choice of `m` | the dependence order is structural under the randomized-phase refresh (`m <= 2`, and `m <= R` conservatively), not estimated from autocorrelation; coverage swept over `m` for both policies, plus a mutual-information and a block-permutation test |
| `analyze_relcorr.py` -> `a6_results.json` | reviewer comment on correlated invocation failures | persistence `rho_hat = 0.210 [0.188, 0.232]` measured at the invocation lag; the 95% certificate needs `k = 1` for every `rho` |
| `gum_budget_ina219.json` | author-initiated correction | JCGM 101 re-analysis of the C2b campaign: central values unchanged, intervals widened to 95% Monte-Carlo |
| `make_numbers_r1.py` -> `numbers_r1.json` | — | turns those JSONs into the LaTeX macros the manuscript uses, so no revised number is typed by hand |

See `R1_additions/README_R1.md` for the protocols and for the `DATA` path the
two analysis scripts expect.

## License and citation

Please cite the paper above if you use this harness. Third-party datasets keep
their own licenses and are not redistributed here.
