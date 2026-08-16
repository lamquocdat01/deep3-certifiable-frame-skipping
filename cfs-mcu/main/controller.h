// controller.h — the paper's R-refresh frame-skipping policy, ported to the MCU.
//
// Per frame the controller decides OPEN (run inference) or CLOSED (skip). Three
// runtime modes plus a sweep mode drive the activation fraction, which the
// power model E(a) is validated against in C2b.
#pragma once
#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    CFS_MODE_IDLE = 0,   // capture + skip, open only on hard R-refresh -> a≈1/R
    CFS_MODE_ACTIVE,     // inference every frame -> a≈1.0
    CFS_MODE_GATE,       // motion gate + R-refresh safety net
    CFS_MODE_SWEEP,      // duty-cycle sweep: open every k-th frame -> a≈1/k
    // C2b measurement floor: capture + downscale ONLY. The motion gate is not
    // computed (no mean-abs-diff, no previous-frame copy) and the decision is
    // always CLOSED, so the measured power is the pure capture baseline that
    // E_idle is defined against. Appended last so the C2a enum values above are
    // unchanged and existing logs stay comparable.
    CFS_MODE_IDLE_SKIP,
} cfs_mode_t;

typedef struct {
    cfs_mode_t mode;
    int  R;              // hard refresh period (frames)
    float theta;         // motion gate threshold (mean-abs-diff in luma units)
    int  sweep_k;        // sweep period when mode==SWEEP
} cfs_ctrl_params_t;

// Reset controller state (call once at boot and whenever mode/params change if
// you want a clean max-closed-run measurement).
void cfs_ctrl_reset(void);

// Decide OPEN/CLOSED for the current frame. `luma96` is the current 96x96 frame
// (used by the motion gate); pass NULL to skip motion evaluation. Updates the
// internal closed-run bookkeeping. Returns true == OPEN (run inference).
bool cfs_ctrl_decide(const cfs_ctrl_params_t *p, const uint8_t *luma96);

// Diagnostics for STATS / firmware assertions.
int  cfs_ctrl_max_closed_run(void);   // longest run of consecutive CLOSED frames
int  cfs_ctrl_frames_since_open(void);

#ifdef __cplusplus
}
#endif
