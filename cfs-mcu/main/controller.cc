// controller.cc — see controller.h
#include "controller.h"
#include "app_camera.h"    // CFS_IMG_SIZE
#include <stdlib.h>
#include <string.h>

static int  s_frames_since_open = 1000000;  // force an OPEN on the very first frame
static int  s_cur_closed_run    = 0;
static int  s_max_closed_run    = 0;
static bool s_have_prev         = false;
static uint8_t s_prev[CFS_IMG_SIZE];

void cfs_ctrl_reset(void)
{
    s_frames_since_open = 1000000;
    s_cur_closed_run = 0;
    s_max_closed_run = 0;
    s_have_prev = false;
}

// Mean absolute difference of two 96x96 luma frames (0..255 scale).
static float mean_abs_diff(const uint8_t *a, const uint8_t *b)
{
    uint32_t acc = 0;
    for (int i = 0; i < CFS_IMG_SIZE; ++i) {
        int d = (int)a[i] - (int)b[i];
        acc += (d < 0) ? -d : d;
    }
    return (float)acc / (float)CFS_IMG_SIZE;
}

bool cfs_ctrl_decide(const cfs_ctrl_params_t *p, const uint8_t *luma96)
{
    // --- C2b idle-skip floor -------------------------------------------------
    // Return before touching the frame at all: no mean-abs-diff, no prev-frame
    // memcpy, never OPEN. Bookkeeping still advances so STATS stays honest (the
    // closed run grows without bound here by construction, which is why the
    // R-1 invariant check in app_main excludes this mode).
    if (p->mode == CFS_MODE_IDLE_SKIP) {
        s_frames_since_open++;
        s_cur_closed_run++;
        if (s_cur_closed_run > s_max_closed_run) s_max_closed_run = s_cur_closed_run;
        return false;
    }

    bool motion = false;
    if (luma96) {
        if (s_have_prev) {
            motion = mean_abs_diff(luma96, s_prev) > p->theta;
        }
        memcpy(s_prev, luma96, CFS_IMG_SIZE);
        s_have_prev = true;
    }

    // Effective hard-refresh period. Sweep overrides R with sweep_k so the
    // duty cycle is exactly 1/k (acceptance test 3).
    int R = (p->mode == CFS_MODE_SWEEP) ? p->sweep_k : p->R;
    if (R < 1) R = 1;

    // Count the current frame as elapsed-since-last-open BEFORE the refresh
    // test, so the period is exactly R (opens at frames 0, R, 2R, ...).
    s_frames_since_open++;

    // --- Hard R-refresh guarantee ---------------------------------------
    // Open when it has been at least R frames since the last OPEN. This uses
    // ">=", NOT ">". The paper's earlier draft used ">", which lets the closed
    // run reach R (leaking one extra skipped frame) before refreshing —
    // the "leak-then-fix" bug fixed in the camera-ready. With ">=" (and the
    // pre-increment above) the maximum closed run is exactly R-1 and the open
    // fraction is exactly 1/R.
    bool hard_refresh = (s_frames_since_open >= R);

    bool open;
    switch (p->mode) {
        case CFS_MODE_ACTIVE:
            open = true;                       // a ≈ 1.0
            break;
        case CFS_MODE_GATE:
            open = motion || hard_refresh;     // event-driven + safety refresh
            break;
        case CFS_MODE_IDLE:
        case CFS_MODE_SWEEP:
        default:
            open = hard_refresh;               // a ≈ 1/R (or 1/k)
            break;
    }

    // --- Bookkeeping ----------------------------------------------------
    if (open) {
        s_frames_since_open = 0;
        s_cur_closed_run = 0;
    } else {
        s_cur_closed_run++;
        if (s_cur_closed_run > s_max_closed_run) {
            s_max_closed_run = s_cur_closed_run;
        }
    }
    return open;
}

int cfs_ctrl_max_closed_run(void)    { return s_max_closed_run; }
int cfs_ctrl_frames_since_open(void) { return s_frames_since_open; }
