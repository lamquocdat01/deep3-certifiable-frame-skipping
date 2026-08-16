# VIRAT re-dump → VIRAT-P variant (R2.5, low-event-density)

**Status: RESOLVED via a new parallel variant `VIRAT-P`. No committed artifact modified; no ASMAG source touched; no detections recomputed.**

**Paper:** *Certifiable Worst-Case Detection Latency…* (IoT-J IoT-68470-2026, Reviewer 2 comment 5).
**Date:** 2026-07-16. **Machine:** PC (CPU). **ASMAG src commit:** `cc3475eab80e27a3c407b5fd56db9ea67ebce45a` (matches README pin `cc3475ea`; working tree clean — verified `git status` empty after all work).

---

## 0. Paper-facing conclusion (the headline)

> **Event density is a property of the *event definition*, not of the scene.** Under the pipeline's committed label `g_t = 1 ⇔ the frame has ≥1 detection box` (class-agnostic), **no** dataset is sparse — VIRAT 1.00, BMC 0.97, LASIESTA 0.79, CDnet 0.70 — because surveillance scenes contain **persistent objects** (parked vehicles, standing people) that the always-on detector fires on every frame. Sparsity appears only when "event" is defined as an **activity of interest**. Re-labelling VIRAT's events as *person present at conf ≥ 0.7* (**VIRAT-P**) yields a genuinely sparse timeline (**ρ_ev = 0.42**, per-video 0.01–0.80) on which the worst-case certificate still holds (D≥R misses: **9 → 0** under the leak-then-fix shield).

---

## 1. Root cause of the old dump gap (two layers)

1. **Stale path + a 500-frame in-event-only detection set.** `configs/default.yaml:detections_root` points at a folder that **moved** to `…/THS Programing/zz/…/detections_cpu`. Its `VIRAT/*.json` contain only **frames 1–500, all with boxes**, so `dump_gate_scores.py` (which covers exactly `frames[0].frame … frames[-1].frame`, `g_t = has-box`) produced 10×500 = 5,000 VIRAT rows, all `g_t=1`. *The dump code is correct — it faithfully covered an all-in-event 500-frame input.*
2. **Even the full-timeline detections are ρ_ev ≈ 1.0.** A full set exists (`…/detections_cpu_virat_full/VIRAT`, 41,823 frames matching the raw clips), but 41,822/41,823 frames have ≥1 box → `has-box` ρ_ev = **1.0000**. The 10 clips are event-segment clips and the always-on YOLO fires on persistent objects throughout. So re-dumping alone does not create out-of-event frames — hence the **VIRAT-P** event re-definition (§2), which the author approved.

---

## 2. VIRAT-P definition & method

- **Source detections:** `detections_cpu_virat_full/VIRAT` (full timelines, 41,823 frames), `detections_root` overridden **in-memory** (no config edit).
- **New event label:** `g_t = 1 ⇔ the frame has ≥1 box with class == 0 (person) AND conf ≥ 0.7` (primary). Sensitivity at conf ∈ {0.5, 0.8}.
- **Gate score S_t is UNCHANGED / deployment-faithful:** the deployed `ASMAGPlusGate` runs once over each full timeline with its committed temporal-persistence feedback (`has-box`); `o_t` uses the same `refresh`+`reuse_cap` logic. **Only the evaluation label g_t is redefined** — this cleanly isolates "density = event-definition" from any controller change. (S_t range [0.199, 0.850], mean 0.441.)
- **Constants (read from asmag-trc, unchanged):** T_refresh=15, W_maxskip=4, **R=5**, τ=0.55.

---

## 3. Per-video frame counts & ρ_ev (VIRAT-P, conf ≥ 0.7)

| video | frames | in-event (g=1) | **ρ_ev** | deployed events | missed |
|---|---:|---:|---:|---:|---:|
| VIRAT_S_000002 | 9074 | 6639 | 0.732 | 230 | 44 |
| VIRAT_S_000200_00_000100_000171 | 2113 | 219 | 0.104 | 33 | 8 |
| VIRAT_S_000200_01_000226_000268 | 1258 | 16 | 0.013 | 3 | 0 |
| VIRAT_S_000200_03_000657_000899 | 7242 | 5786 | 0.799 | 106 | 12 |
| VIRAT_S_000200_05_001525_001575 | 1481 | 90 | 0.061 | 22 | 8 |
| VIRAT_S_000200_06_001693_001824 | 3906 | 965 | 0.247 | 157 | 40 |
| VIRAT_S_000201_00_000018_000380 | 10833 | 3080 | 0.284 | 420 | 77 |
| VIRAT_S_000201_02_000590_000623 | 980 | 79 | 0.081 | 20 | 5 |
| VIRAT_S_000201_03_000640_000672 | 942 | 67 | 0.071 | 14 | 0 |
| VIRAT_S_000201_05_001081_001215 | 3994 | 679 | 0.170 | 114 | 24 |
| **TOTAL / overall** | **41,823** | **17,620** | **0.4213** | **1119** | **218** |

**ρ_ev(VIRAT-P) = 0.4213 ≪ 1.0** (the class-agnostic value) and below 0.5 — VIRAT-P is a natively-sparse validation case.

## 4. F_D statistics (VIRAT-P, conf ≥ 0.7)

`data/processed/events_durations_viratp.csv` — **1119 events** (vs the 10 all-clip "events" in the committed set):

| n_events | D_min | median | mean E[D] | D_max | CV | tail |
|---:|---:|---:|---:|---:|---:|---|
| 1119 | 1 | 3 | 15.75 | 2111 | 6.99 | heavy-tailed (CV≫1.5) |

Heavy-tailed, dominated by short person-appearances (median 3 frames) with a long tail (max 2111). D_min = 1 ⇒ certifiable-zero-miss point a_r = 1/D_min = 1.0.

## 5. q_in / q_out at θ = 0.55

| | q_in = P(S_t>θ \| g=1) | q_out = P(S_t>θ \| g=0) |
|---|---:|---:|
| **VIRAT-P (conf ≥ 0.7)** | **0.306** | **0.399** |

**q_out > q_in** — the motion gate fires *more* on non-person frames than on person frames. Cause: VIRAT persons are often static/loitering (low motion → low S_t), while much of the "out-of-event" motion is **vehicles**. The motion gate is **anti-aligned** with the person-event definition. This is the sparse-dataset counterpoint to the motion-aligned CDnet case.

## 6. Frontier ε(a) = E_D[(1 − a·D)₊] on VIRAT-P's F_D

| a | R = round(1/a) | ε(a) |
|---:|---:|---:|
| 0.0156 | 64 | 0.877 |
| 0.0312 | 32 | 0.783 |
| 0.0625 | 16 | 0.643 |
| 0.1250 | 8 | 0.476 |
| **0.2000** | **5 (deployed R)** | **0.356** |
| 0.2500 | 4 | 0.300 |
| 0.5000 | 2 | 0.140 |

Certifiable operating point (zero miss on all observed events): a_r = 1/D_min = 1/1 = **1.0** (single-frame person blips force full activation to certify *every* event; the meaningful certificate is on **D ≥ R**, §8).

## 7. Gated content-aware family — (a, miss) sweep (`tau_sweep_viratp.csv`)

Same format/method as the committed `tau_sweep.csv` (π_θ: `open iff S_t>θ OR refresh OR reuse_cap`; ε on the same g_t-run durations; 40 θ × {deployed, fixed}). Deployed reuse, pooled VIRAT-P:

| θ | a (energy) | gated_miss | ε(a) | margin | ratio |
|---:|---:|---:|---:|---:|---:|
| 0.198 | 1.000 | 0.000 | 0.000 | 0.000 | ∞ |
| 0.200 | 0.875 | 0.024 | 0.035 | +0.011 | 1.45 |
| 0.259 | 0.752 | 0.063 | 0.070 | +0.006 | 1.10 |
| 0.322 | 0.627 | 0.147 | 0.105 | −0.042 | 0.71 |
| 0.501 | 0.505 | 0.245 | 0.139 | −0.106 | 0.57 |
| 0.701 | 0.381 | 0.303 | 0.205 | −0.098 | 0.68 |
| 0.772 | 0.256 | 0.343 | 0.295 | −0.048 | 0.86 |

**Verdict:** across the useful budget range (a ≈ 0.25–0.9) the content-aware gate has **ratio < 1** (margin negative) — it is **worse** than the oblivious periodic frontier at equal energy on VIRAT-P. It only ties/wins near a≈1 (open everything). This mirrors the committed finding for BMC ("never wins") and **reinforces the paper's message: lead with the worst-case certificate, treat content-awareness as a secondary, alignment-dependent result.** On a motion-misaligned sparse dataset, content-awareness provides no advantage.

## 8. Worst-case certificate on VIRAT-P — leak-then-fix (D ≥ R = 5)

| stream | total events | total miss | **D≥R events** | **miss on D≥R** |
|---|---:|---:|---:|---:|
| deployed (`o_t`, reuse cap `fsl > W`) | 1119 | 218 (19.5%) | 473 | **9 (1.90%) — leak** |
| **fixed (`fsl ≥ W`, hard-refresh shield)** | 1119 | 181 (16.2%) | 473 | **0 (0.00%) — certificate restored** |

The Tier-1 certificate (**0 miss for D ≥ R** under the corrected reuse cap) **holds on the natively-sparse VIRAT-P**, just as on the committed datasets. This is the paper's headline result, now demonstrated in the low-event-density regime R2.5 asked for.

## 9. Definition-robustness sensitivity (conf 0.5 / 0.7 / 0.8)

| conf | ρ_ev | n_events | E[D] | median | max | CV | q_in | q_out |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.5 | 0.738 | 1013 | 30.5 | 4 | 5623 | 7.97 | 0.329 | 0.447 |
| **0.7 (primary)** | **0.421** | **1119** | **15.8** | **3** | **2111** | **6.99** | **0.306** | **0.399** |
| 0.8 | 0.186 | 686 | 11.3 | 2 | 568 | 4.23 | 0.292 | 0.375 |

Monotone and stable: tighter person-confidence → sparser ρ_ev, shorter events, and the q_out > q_in anti-alignment persists at every threshold — so the §0/§5/§7 conclusions are **not artifacts of the 0.7 cutoff**.

---

## 10. Commands & files

```
git -C "…/ASMAG_Project_Code" log -1                       # cc3475ea… (recorded)
python scripts/viratp_gatepass.py                          # gate pass over full timelines (~5 min CPU)
python scripts/viratp_analyze.py                           # durations, gated, frontier, tau-sweep, metrics
```
`viratp_gatepass.py` overrides `detections_root → detections_cpu_virat_full` **in memory only**; reuses `run_gate_on_video` from the committed `generate_gate_scores.py` unchanged.

**Delivered (all NEW, parallel; committed artifacts verified unmodified — original 2026-06-09 timestamps intact):**
| file | contents |
|---|---|
| `data/processed/frame_scores_viratp.parquet` | per-frame: dataset, video, frame, score S_t, valid, gate, ot, ot_fixed, g_t(@0.7), g_t_c05, g_t_c08 (41,823 rows) |
| `data/processed/events_durations_viratp.csv` | 1119 VIRAT-P events (dataset, video, event_id, onset, duration) |
| `data/processed/events_gated_viratp.csv` | deployed gated outcome per event (q, caught_by_gate/refresh, missed, latency) |
| `data/processed/tau_sweep_viratp.csv` | (θ, reuse, dataset, a, gated_miss, eps, margin, ratio) — same schema as `tau_sweep.csv` |
| `data/processed/viratp_metrics.json` | ρ_ev, per-video, F_D, q_in/q_out, frontier, certifiable point, sensitivity |
| `scripts/viratp_gatepass.py`, `scripts/viratp_analyze.py` | reproducible generators |

**Environment:** Python 3.11.9, pandas 2.3.3, OpenCV 4.11.0, numpy, scipy, pyarrow. Gate pass 41,823 frames in ~300 s.

**Not done (by design):** the committed `frame_scores.parquet`, `events_durations.csv`, `events_gated.csv`, `tau_sweep.csv` and `cfs.run_all` outputs were **left untouched** — VIRAT-P is delivered as a parallel variant so the existing (has-box) results remain reproducible. To fold VIRAT-P into the paper's tables, point `cfs.run_all` / `sweep_tau.py` at the `_viratp` files (or add `VIRAT-P` as a dataset in a copy of `default.yaml`).
