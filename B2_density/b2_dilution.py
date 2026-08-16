#!/usr/bin/env python3
"""B2 (R2.5) — Low-event-density evaluation by timeline dilution.

Method: stretch each real timeline by inserting background segments
(resampled contiguous out-of-event score blocks from the SAME video, so the
gate sees realistic background statistics) at random out-of-event positions,
sweeping the pooled in-event density rho from native (~0.77) down to 0.01.
Event durations are untouched, so the frontier eps(a) = E[(1-aD)+] is
IDENTICAL across densities — what changes is where policies can sit on it.

At each density we trace the gated family pi_theta (gate OR hard R=5 refresh)
across thresholds, giving (activation, miss) pairs, and compare to eps(a) at
the same activation. We also record the A2 binary-channel model's PREDICTED
advantage at each density (same measured q_in/q_out channel, new rho_ev) —
testing the theory's forecast that content-awareness pays off as events
become rare.

VIRAT is excluded here (its committed frame dump contains no out-of-event
frames to resample); it is reinstated separately as a natively sparse dataset.
"""
import json
import numpy as np
import pandas as pd

R = 5
THETAS = [0.35, 0.45, 0.5, 0.54, 0.55, 0.57, 0.6, 0.7, 0.85]
DENSITIES = [None, 0.5, 0.25, 0.10, 0.05, 0.01]   # None = native
rng = np.random.default_rng(21)

fs = pd.read_parquet('/home/claude/a2_gate/frame_scores.parquet')
eg = pd.read_csv('/home/claude/a2_gate/events_gated.csv')

videos = []
for (ds, vid), g in fs.groupby(['dataset', 'video']):
    if ds == 'VIRAT':
        continue
    g = g.sort_values('frame')
    fmin = int(g['frame'].min())
    evs = eg[(eg['dataset'] == ds) & (eg['video'] == vid)][['onset', 'duration']].values.astype(int)
    evs[:, 0] -= fmin
    s = g['score'].values.astype(np.float32)
    gt = g['g_t'].values.astype(bool)
    videos.append({"ds": ds, "s": s, "gt": gt, "events": evs})

dur = np.concatenate([v['events'][:, 1] for v in videos]).astype(float)
N_EV = len(dur)
def eps(a): return float(np.maximum(0.0, 1.0 - a * dur).mean())

# dataset-pooled background score pool (fallback for videos with little background)
bg_pool = {}
for ds in set(v['ds'] for v in videos):
    pool = np.concatenate([v['s'][~v['gt']] for v in videos if v['ds'] == ds and (~v['gt']).sum() > 0])
    bg_pool[ds] = pool

def dilute(v, rho_target):
    """Insert background blocks at random out-of-event positions."""
    s, gt, evs = v['s'], v['gt'], v['events']
    n_in = int(gt.sum())
    if n_in == 0 or rho_target is None:
        return s, evs
    L_extra = int(n_in / rho_target - len(s))
    if L_extra <= 0:
        return s, evs
    own_bg = s[~gt]
    pool = own_bg if len(own_bg) >= 50 else bg_pool[v['ds']]
    # sample background as contiguous blocks (preserve autocorrelation)
    blocks = []
    got = 0
    while got < L_extra:
        blen = min(int(rng.integers(50, 400)), L_extra - got)
        start = int(rng.integers(0, max(1, len(pool) - blen)))
        blocks.append(pool[start:start + blen]); got += blen
    # insertion points: random out-of-event frame indices (avoid splitting events);
    # fully in-event videos get background prepended/appended instead
    out_idx = np.flatnonzero(~gt)
    cand = out_idx if len(out_idx) > 0 else np.array([-1, len(s) - 1])
    ins_pos = np.sort(rng.choice(cand, size=len(blocks), replace=True))
    # build new timeline + shift onsets
    parts, new_evs, prev = [], evs.copy(), 0
    shift = np.zeros(len(s) + 1, dtype=np.int64)
    for pos, blk in zip(ins_pos, blocks):
        shift[pos + 1:] += len(blk)
    for i, pos in enumerate(ins_pos):
        parts.append(s[prev:pos + 1]); parts.append(blocks[i]); prev = pos + 1
    parts.append(s[prev:])
    s2 = np.concatenate(parts)
    new_evs[:, 0] = evs[:, 0] + shift[evs[:, 0]]
    return s2, new_evs

def gate_refresh_metrics(s, evs, th):
    """Exact pi_theta via gate-open positions + arithmetic refresh chains."""
    gates = np.flatnonzero(s > th)
    n = len(s)
    # activation: gate opens + refresh opens between consecutive gate opens
    anchors = np.r_[-1, gates]
    nxt = np.r_[gates, n]
    gaps = nxt - anchors - 1
    n_refresh = int((gaps // R).sum())
    a = (len(gates) + n_refresh) / n
    miss = 0; lat_ok = 0
    for onset, D in evs:
        end = onset + D - 1
        j = np.searchsorted(gates, onset)
        first_gate = gates[j] if j < len(gates) else n
        g0 = gates[j - 1] if j > 0 else -1
        k = int(np.ceil((onset - g0) / R))
        c = g0 + R * max(k, 1)
        first_open = min(first_gate, c if c < first_gate else first_gate)
        if first_open > end:
            miss += 1
    return a, miss / N_EV

# native-density verification against the B1 loop implementation
def loop_check(th):
    tot_open, tot_frames, miss = 0, 0, 0
    for v in videos:
        s = v['s']; m_last = -1
        opens = np.zeros(len(s), bool)
        for t in range(len(s)):
            if s[t] > th or (t - m_last) >= R:
                opens[t] = True; m_last = t
        tot_open += opens.sum(); tot_frames += len(s)
        for onset, D in v['events']:
            if not opens[onset:onset + D].any():
                miss += 1
    return tot_open / tot_frames, miss / N_EV

a_fast = m_fast = None
res_native = [gate_refresh_metrics(v['s'], v['events'], 0.55) for v in videos]
a_fast = sum(r[0] * len(v['s']) for r, v in zip(res_native, videos)) / sum(len(v['s']) for v in videos)
m_fast = sum(r[1] for r in res_native)
a_loop, m_loop = loop_check(0.55)
print(f"VERIFY fast vs loop @theta=0.55: a {a_fast:.4f} vs {a_loop:.4f} | miss {m_fast:.4f} vs {m_loop:.4f}")

# A2 channel parameters (pooled, 3 datasets)
q_in = float((fs[(fs['g_t'] == 1) & (fs['dataset'] != 'VIRAT')]['score'] > 0.55).mean())
q_out = float((fs[(fs['g_t'] == 0) & (fs['dataset'] != 'VIRAT')]['score'] > 0.55).mean())

out = {"q_in": round(q_in, 4), "q_out": round(q_out, 4), "densities": []}
for rho in DENSITIES:
    diluted = [dilute(v, rho) for v in videos]
    n_frames = sum(len(s) for s, _ in diluted)
    rho_actual = sum(int(v['gt'].sum()) for v in videos) / n_frames
    curve = []
    for th in THETAS:
        A, M = 0, 0.0
        for (s, evs) in diluted:
            a_v, m_v = gate_refresh_metrics(s, evs, th)
            A += a_v * len(s); M += m_v
        a = A / n_frames
        e = eps(a)
        curve.append({"theta": th, "a": round(a, 4), "miss": round(M, 4),
                      "eps": round(e, 4),
                      "advantage": round(e / M, 3) if M > 0 else None})
    # deployed-theta energy story
    dep = [c for c in curve if c["theta"] == 0.55][0]
    # A2 model prediction at this rho: a(q) and predicted advantage
    a_pred = 1 / R + (1 - 1 / R) * (rho_actual * q_in + (1 - rho_actual) * q_out)
    Pg_pred = float((np.maximum(0, 1 - dur / R) * (1 - q_in) ** dur).mean())
    out["densities"].append({
        "rho_target": rho if rho else "native", "rho_actual": round(rho_actual, 4),
        "frames": int(n_frames), "curve": curve,
        "deployed_theta": dep,
        "model": {"a_pred": round(a_pred, 4), "eps_at_a_pred": round(eps(a_pred), 4),
                  "Pg_pred": round(Pg_pred, 4),
                  "advantage_pred": round(eps(a_pred) / Pg_pred, 3) if Pg_pred > 0 else None},
    })
    best = max((c for c in curve if c["advantage"]), key=lambda c: c["advantage"])
    print(f"rho={str(rho):>6} (actual {rho_actual:.3f}, {n_frames/1e6:.2f}M fr) "
          f"deployed: a={dep['a']:.3f} miss={dep['miss']:.4f} eps={dep['eps']:.4f} "
          f"adv={dep['advantage']} | best adv={best['advantage']} @a={best['a']:.2f} "
          f"| model adv={out['densities'][-1]['model']['advantage_pred']}")

json.dump(out, open('/home/claude/b2_density/b2_results.json', 'w'), indent=1)
print("saved b2_results.json")
