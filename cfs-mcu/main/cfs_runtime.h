// cfs_runtime.h — shared runtime state between the inference loop (app_main)
// and the serial command task. Access under g_rt_mutex.
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "controller.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

typedef struct {
    // --- control knobs (written by serial, read by loop) ---
    cfs_ctrl_params_t params;
    bool power_sampling;        // POWER on/off

    // --- C2b boot-armed measurement (see meas.h) ---
    bool     infer_enabled;     // false in the idle-skip / gate measurement modes
    bool     parked;            // post-run low-activity idle: no capture, no work
    bool     meas_running;      // a boot-armed run is in progress
    uint8_t  meas_mode;         // cfs_meas_mode_t of that run
    uint64_t meas_start_us;
    uint64_t meas_end_us;

    // --- live statistics (written by loop, read by serial STATS) ---
    uint32_t frames_total;      // frames processed since last reset
    uint32_t opens_total;       // OPEN decisions since last reset
    uint32_t infer_count;       // inferences actually run
    uint64_t infer_us_sum;      // sum of inference latencies (us)
    uint32_t infer_us_max;      // max inference latency (us)
    int32_t  last_person_score; // int8, last inference
    int32_t  last_noperson_score;
    float    fps;               // achieved fps (EWMA)
    uint64_t window_start_us;   // for open-fraction windowing
    uint32_t window_frames;
    uint32_t window_opens;
} cfs_runtime_t;

extern cfs_runtime_t g_rt;
extern SemaphoreHandle_t g_rt_mutex;

static inline void cfs_rt_lock(void)   { xSemaphoreTake(g_rt_mutex, portMAX_DELAY); }
static inline void cfs_rt_unlock(void) { xSemaphoreGive(g_rt_mutex); }

// Reset the statistics window and controller (called on mode/param changes).
void cfs_rt_reset_stats(void);
