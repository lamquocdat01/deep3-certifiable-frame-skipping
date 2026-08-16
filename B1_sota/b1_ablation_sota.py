#!/usr/bin/env python3
"""B1 (R2.4) — Ablation (refresh x gate) + trace-driven SOTA-style baselines.

All policies run causally on the REAL per-video timelines (frame_scores.parquet:
score s_t = the deployed cheap gate signal, g_t = detectability indicator).
Events = (onset, duration) from events_gated.csv.

REV 2026-08-13 (B5): the 10 dataset=="VIRAT" timelines in frame_scores.parquet are
the stale 500-frame all-in-event stub dumps that verify_event_count.py drops
everywhere else in the paper; they carry no events in the cleaned events_gated.csv
yet still inflated N_FRAMES, and the miss denominator was hardcoded to the
pre-cleanup 3723. Both are fixed here: VIRAT is filtered from BOTH inputs and the
denominator is derived from the loaded event table. The run is now on the same
121 videos / 3,713 events as Setup, Table I and verify_event_count.py.

Policies
  periodic(R)          : open iff t % R == 0                       [oblivious, certified]
  random(a)            : open iff U_t < a                          [oblivious]
  gate_only(theta)     : open iff s_t > theta                      [content-aware, NO certificate]
  gate_refresh(theta)  : open iff s_t > theta or hard R=5 refresh  [deployed structure]
  glimpse(delta)       : open iff |s_t - s_lastopen| > delta       [Glimpse-style change trigger]
  reducto(phi)         : open iff diff_t > causal rolling (1-phi)-quantile of past diffs
                         (window 100) — Reducto-style adaptive differencing
  framehopper(K)       : at each open, skip k = K*(1 - rank(s_t)) frames
                         (rank via causal running quantiles) — FrameHopper-style skip table

Each policy is calibrated (bisection on its scalar parameter) to pooled target
activations. Metrics: event miss rate (all / D>=5), latency p99 & max (detected),
MAX CLOSED-RUN across all videos (the structural worst-case certificate), activation.
"""
import json
import os
import numpy as np
import pandas as pd

R = 5
rng = np.random.default_rng(3)

# Paths relative to this file, so the script runs from any cwd.
# Was hardcoded /home/claude/... .
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROC = os.path.join(ROOT, '..', 'certifiable-frame-skipping', 'data', 'processed')

STUB = 'VIRAT'   # the 10 placeholder timelines; see the module docstring

fs = pd.read_parquet(os.path.join(PROC, 'frame_scores.parquet'))
eg = pd.read_csv(os.path.join(PROC, 'events_gated.csv'))

# --- REV (B5): drop the stub dataset from BOTH inputs, before anything is counted.
# The source parquet/CSV on disk are left untouched; this is a load-time filter.
fs = fs[fs['dataset'] != STUB].copy()
eg = eg[eg['dataset'] != STUB].copy()

N_EVENTS = len(eg)                       # was a hardcoded 3723
N_TIMELINES = fs.groupby(['dataset', 'video']).ngroups

print(f"population: {N_TIMELINES} timelines | {len(fs)} frames | {N_EVENTS} events")
assert (N_TIMELINES, len(fs), N_EVENTS) == (121, 166589, 3713), (
    f"unexpected population {(N_TIMELINES, len(fs), N_EVENTS)}; "
    "expected (121, 166589, 3713) -- STOP")

videos = []
for (ds, vid), g in fs.groupby(['dataset', 'video']):
    g = g.sort_values('frame')
    fmin = int(g['frame'].min())
    evs = eg[(eg['dataset'] == ds) & (eg['video'] == vid)][['onset', 'duration']].values.astype(int)
    evs[:, 0] -= fmin                     # map onset into timeline index space
    assert (evs[:, 0] >= 0).all() and (evs[:, 0] < len(g)).all()
    videos.append({"ds": ds, "vid": vid, "s": g['score'].values.astype(float),
                   "events": evs})
N_FRAMES = sum(len(v['s']) for v in videos)

# every event row must have landed on a timeline -- no silent drops
_matched = sum(len(v['events']) for v in videos)
assert _matched == N_EVENTS, f"{_matched} events matched to timelines vs {N_EVENTS} rows"
print(f"loaded: {len(videos)} timelines | {N_FRAMES} frames | {_matched} events matched")

# ---------------- policies: return boolean open mask ----------------
def pol_periodic(v, R_):
    m = np.zeros(len(v['s']), bool); m[::max(1, int(round(R_)))] = True; return m

def pol_random(v, a):
    return rng.random(len(v['s'])) < a

def pol_gate_only(v, th):
    return v['s'] > th

def pol_gate_refresh(v, th):
    s = v['s']; m = np.zeros(len(s), bool); last = -1
    for t in range(len(s)):
        if s[t] > th or (t - last) >= R:
            m[t] = True; last = t
    return m

def pol_glimpse(v, delta):
    s = v['s']; m = np.zeros(len(s), bool); ref = None
    for t in range(len(s)):
        if ref is None or abs(s[t] - ref) > delta:
            m[t] = True; ref = s[t]
    return m

def pol_reducto(v, phi, W=100):
    s = v['s']; d = np.abs(np.diff(s, prepend=s[0]))
    m = np.zeros(len(s), bool); m[0] = True
    thr = 0.0
    for t in range(1, len(s)):
        if t % 20 == 0 and t >= 10:
            lo = max(0, t - W)
            thr = np.quantile(d[lo:t], 1 - phi)
        if d[t] > thr:
            m[t] = True
    return m

def pol_framehopper(v, K):
    s = v['s']; m = np.zeros(len(s), bool)
    hist, t = [], 0
    while t < len(s):
        m[t] = True; hist.append(s[t])
        if len(hist) >= 10:
            rank = np.searchsorted(np.sort(hist[-500:]), s[t]) / min(len(hist), 500)
        else:
            rank = 0.5
        k = int(round(K * (1.0 - rank)))  # low score -> long skip
        t += 1 + max(0, k)
    return m

POLICIES = {
    "periodic": (pol_periodic, 1.05, 64.0, True),     # param = R_ (inverse activation)
    "random": (pol_random, 0.01, 1.0, False),
    "gate_only": (pol_gate_only, -0.2, 1.2, True),    # higher th -> lower a
    "gate_refresh": (pol_gate_refresh, -0.2, 1.2, True),
    "glimpse": (pol_glimpse, 0.0, 1.0, True),
    "reducto": (pol_reducto, 0.001, 1.0, False),
    "framehopper": (pol_framehopper, 0.0, 64.0, True),
}

def run(polfn, param):
    opens, miss, missD5, lats, maxgap, nD5 = 0, 0, 0, [], 0, 0
    for v in videos:
        m = polfn(v, param)
        opens += int(m.sum())
        idx = np.flatnonzero(m)
        gaps = np.diff(np.r_[-1, idx, len(m)]) - 1
        maxgap = max(maxgap, int(gaps.max()) if len(gaps) else len(m))
        for onset, D in v['events']:
            span = m[onset:onset + D]
            if D >= R: nD5 += 1
            if span.any():
                lats.append(int(np.argmax(span)))
            else:
                miss += 1
                if D >= R: missD5 += 1
    a = opens / N_FRAMES
    lat = np.array(lats)
    return {"a": a, "miss": miss / N_EVENTS, "miss_D5": missD5 / max(1, nD5),
            "lat_p99": float(np.quantile(lat, 0.99)) if len(lat) else None,
            "lat_max": int(lat.max()) if len(lat) else None,
            "max_closed_run": maxgap}

def calibrate(name, target_a):
    fn, lo, hi, inverse = POLICIES[name]
    for _ in range(12):
        mid = 0.5 * (lo + hi)
        a = run(fn, mid)["a"]
        if (a > target_a) == inverse:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)

dur = eg['duration'].values.astype(float)
def eps(a): return float(np.maximum(0.0, 1.0 - a * dur).mean())

TARGETS = [0.25, 0.4, 0.6, 0.8]
PERIODIC_R = [4, 3, 2, 1]
rows = []
for name in POLICIES:
    for i, ta in enumerate(TARGETS):
        if name == 'periodic':
            p = PERIODIC_R[i]
        else:
            p = calibrate(name, ta)
        r = run(POLICIES[name][0], p)
        r.update({"policy": name, "target_a": ta, "param": round(p, 4),
                  "eps_at_a": round(eps(r["a"]), 4)})
        r["a"] = round(r["a"], 4); r["miss"] = round(r["miss"], 4)
        r["miss_D5"] = round(r["miss_D5"], 4)
        rows.append(r)
        print(f"{name:13s} a={r['a']:.3f} miss={r['miss']:.4f} "
              f"missD5={r['miss_D5']:.4f} eps={r['eps_at_a']:.4f} "
              f"maxgap={r['max_closed_run']:5d} latmax={r['lat_max']}")

json.dump(rows, open(os.path.join(HERE, 'b1_results.json'), 'w'), indent=1)
pd.DataFrame(rows)[["policy", "target_a", "a", "miss", "miss_D5", "eps_at_a",
                    "lat_p99", "lat_max", "max_closed_run", "param"]] \
  .to_csv(os.path.join(HERE, 'b1_table.csv'), index=False)
print("saved b1_results.json / b1_table.csv")
