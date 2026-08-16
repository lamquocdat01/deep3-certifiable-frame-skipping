// meas.h — boot-armed measurement runs for C2b (USB power-meter protocol).
//
// During a C2b measurement the PC is DISCONNECTED (the board is powered from a
// charger through the inline USB meter, and the no-simultaneous-connections rule
// forbids a second USB link). The firmware therefore has to carry the run
// configuration across a power cycle and keep the results until the PC comes
// back:
//
//   1. PC connected:  MEASURE <mode> <seconds> on-boot   -> {mode,secs} to NVS
//   2. power-cycle onto charger+meter: the run executes automatically, then a
//      summary {run_id, mode, frames, opens, infer_count, elapsed_ms,
//      max_closed_run} is written to NVS and the board parks in a low-activity
//      idle (no capture, no inference).
//   3. PC reconnected: DUMP prints every stored summary as CSV; CLEAR erases.
//
// FIRMWARE v2 (2026-07-31): the firmware now DOES sample power itself.
//
// The original design deliberately left watts to an external meter. That is no
// longer viable as the primary path: the INA219 came up (C2B_REPORT.md §A.8)
// and became the main instrument, and there is no way to have the board sample
// its own consumption while the PC is attached. The CH343 USB-serial bridge
// draws from VBUS *inside* the shunt's span (~10-20 mA active against a ~40-60
// mA idle board), which is a two-digit percentage error landing squarely on
// E_idle — the term kappa depends on. Boot-arming exists precisely so the run
// happens with the PC unplugged, so the sampling has to happen on-board.
//
// See PROMPT_C2b_INA219_step1_firmware.md. The external-meter path still works
// unchanged; a meter simply ignores the new columns.
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
#include "controller.h"

#ifdef __cplusplus
extern "C" {
#endif

// Measurement modes. These are the E(a) sweep points of the C2b protocol; each
// maps onto an already-verified C2a controller path (see cfs_meas_apply).
typedef enum {
    CFS_MEAS_IDLE_SKIP = 0,   // capture + downscale only: no gate, no inference
    CFS_MEAS_GATE      = 1,   // motion gate computed every frame, no inference
    CFS_MEAS_ACTIVE    = 2,   // inference every frame                  (a = 1)
    CFS_MEAS_CTRL_K10  = 3,   // full controller, k = 10               (a = 0.1)
    CFS_MEAS_CTRL_K5   = 4,   // full controller, k = 5                (a = 0.2)
    CFS_MEAS_CTRL_K2   = 5,   // full controller, k = 2                (a = 0.5)
    CFS_MEAS_MODE_COUNT,
    CFS_MEAS_NONE      = 0xFF,
} cfs_meas_mode_t;

// One completed run. Written to NVS as an opaque blob; version-tagged so a
// firmware change cannot silently reinterpret old records.
// v1 -> v2: the four power fields below were appended. Every v1 field keeps its
// name, type and position, so the only thing that changes for a reader is the
// record length. The version tag exists for exactly this situation: a stored v1
// record must be refused by cfs_meas_get(), never reinterpreted as a v2 record
// whose power columns would then be garbage.
#define CFS_MEAS_REC_VERSION 2
typedef struct {
    uint16_t version;         // CFS_MEAS_REC_VERSION
    uint16_t mode;            // cfs_meas_mode_t
    uint32_t run_id;          // monotonic, never reused (survives CLEAR)
    uint32_t frames;          // frames processed during the run
    uint32_t opens;           // OPEN decisions  -> a = opens / frames
    uint32_t infer_count;     // inferences actually executed
    uint32_t elapsed_ms;      // wall-clock length of the run
    int32_t  max_closed_run;  // longest CLOSED run (certificate invariant)
    // --- v2: on-board INA219 power, over the post-warm-up window only --------
    float    mean_mw;         // mean power   (mW), 0 if never sampled
    float    mean_v;          // mean bus V   (V),  0 if never sampled
    float    mean_ma;         // mean current (mA), 0 if never sampled
    uint32_t power_samples;   // samples folded into those means; 0 = no power data
} cfs_meas_summary_t;

// Ring of stored summaries. 64 × 44 B = 2,816 B, comfortably inside the 24 KB
// nvs partition; the full C2b campaign is 12 runs.
#define CFS_MEAS_MAX_RUNS 64

// --- power sampling window ---------------------------------------------------
// The first 30 s of every run are discarded: the protocol's warm-up, during
// which the board is settling and the supply is stabilising. Accumulation only
// starts afterwards, so a run must be longer than this to yield any power data
// at all (a 30 s dry-run run legitimately stores power_samples = 0).
#define CFS_MEAS_DISCARD_MS 30000
// 140 ms > the 136.2 ms full shunt+bus conversion cycle at 128-sample
// averaging, so consecutive reads return consecutive integrals: no conversion
// is read twice, none is skipped. See CFS_INA219_CONFIG_RUN in ina219.h.
#define CFS_MEAS_SAMPLE_MS  140

// Bring up NVS. Safe to call once, early in app_main, before cfs_meas_*.
esp_err_t cfs_meas_init(void);

// Name <-> enum. cfs_meas_mode_from_name returns CFS_MEAS_NONE if unrecognised.
const char      *cfs_meas_mode_name(cfs_meas_mode_t m);
cfs_meas_mode_t  cfs_meas_mode_from_name(const char *s);

// Translate a measurement mode into the controller parameters and the inference
// enable that realise it. `p` is modified in place (R/theta not touched unless
// the mode fixes them), so the caller's existing theta survives.
void cfs_meas_apply(cfs_meas_mode_t m, cfs_ctrl_params_t *p, bool *infer_enabled);

// --- boot-arm record (one-shot) ---------------------------------------------
esp_err_t cfs_meas_arm(cfs_meas_mode_t m, uint32_t seconds);
esp_err_t cfs_meas_disarm(void);
// Non-destructive read (for MEASURE status).
bool cfs_meas_peek_arm(cfs_meas_mode_t *m, uint32_t *seconds);
// Read AND erase, atomically committed before the run starts. Erasing first is
// deliberate: a brownout mid-run must not leave the board re-running forever.
// v2: on success this also spawns the power-sampling task for `*seconds`.
bool cfs_meas_take_arm(cfs_meas_mode_t *m, uint32_t *seconds);

// Abandon an in-flight power sampling task without storing anything. Called
// when an interactive MODE command abandons a boot-armed run, so the sampler
// cannot outlive the run it belongs to.
void cfs_meas_power_abort(void);
// Expected sample count for a run of `elapsed_ms`, i.e. the post-warm-up window
// divided by the cadence. Used to flag a CPU-starved sampler.
uint32_t cfs_meas_power_expected(uint32_t elapsed_ms);

// --- stored summaries --------------------------------------------------------
// Assigns s->run_id from the monotonic counter and appends. Returns
// ESP_ERR_NO_MEM when the ring is full (CLEAR to make room).
// v2: also stops the power-sampling task and fills s->mean_mw / mean_v /
// mean_ma / power_samples from it, so the caller needs no knowledge of the
// sampler. If no power window ran, those four fields are left at zero — never
// filled with a substitute value.
esp_err_t cfs_meas_store(cfs_meas_summary_t *s);
int       cfs_meas_count(void);
esp_err_t cfs_meas_get(int idx, cfs_meas_summary_t *out);
// Erases stored summaries. Does NOT reset the run_id counter, so run ids stay
// unique for the whole campaign and a DUMP can never be confused with an
// earlier one.
esp_err_t cfs_meas_clear(void);
uint32_t  cfs_meas_next_run_id(void);

#ifdef __cplusplus
}
#endif
