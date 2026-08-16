// meas.cc — see meas.h
#include "meas.h"
#include "ina219.h"

#include "nvs.h"
#include "nvs_flash.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>
#include <stdio.h>
#include <ctype.h>
#include <math.h>

static const char *TAG = "cfs_meas";

// NVS layout, namespace "cfs_c2b":
//   "arm_m" u8   armed mode (absent => not armed)
//   "arm_s" u32  armed duration in seconds
//   "n"     u32  number of stored summaries
//   "seq"   u32  next run_id (monotonic; CLEAR does not reset it)
//   "r00".."r63" blob  cfs_meas_summary_t
static const char *NS       = "cfs_c2b";
static const char *K_ARM_M  = "arm_m";
static const char *K_ARM_S  = "arm_s";
static const char *K_COUNT  = "n";
static const char *K_SEQ    = "seq";

static bool s_ready = false;

static void rec_key(int idx, char *out, size_t n) { snprintf(out, n, "r%02d", idx); }

// Power sampler, defined after the arm/store code it hooks into.
static void power_start(uint32_t seconds);
static void power_harvest(cfs_meas_summary_t *s);

esp_err_t cfs_meas_init(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "nvs needs erase (%s) — erasing", esp_err_to_name(err));
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nvs_flash_init failed: %s", esp_err_to_name(err));
        return err;
    }
    s_ready = true;
    ESP_LOGI(TAG, "NVS ready: %d stored run(s), next run_id=%lu",
             cfs_meas_count(), (unsigned long)cfs_meas_next_run_id());
    return ESP_OK;
}

// ---- name mapping -----------------------------------------------------------

const char *cfs_meas_mode_name(cfs_meas_mode_t m)
{
    switch (m) {
        case CFS_MEAS_IDLE_SKIP: return "idle-skip";
        case CFS_MEAS_GATE:      return "gate";
        case CFS_MEAS_ACTIVE:    return "active";
        case CFS_MEAS_CTRL_K10:  return "ctrl-k10";
        case CFS_MEAS_CTRL_K5:   return "ctrl-k5";
        case CFS_MEAS_CTRL_K2:   return "ctrl-k2";
        default:                 return "none";
    }
}

cfs_meas_mode_t cfs_meas_mode_from_name(const char *s)
{
    if (!s) return CFS_MEAS_NONE;
    char b[16];
    strncpy(b, s, sizeof(b) - 1);
    b[sizeof(b) - 1] = 0;
    for (char *p = b; *p; ++p) *p = (char)tolower((unsigned char)*p);
    for (int i = 0; i < CFS_MEAS_MODE_COUNT; ++i) {
        if (strcmp(b, cfs_meas_mode_name((cfs_meas_mode_t)i)) == 0)
            return (cfs_meas_mode_t)i;
    }
    return CFS_MEAS_NONE;
}

void cfs_meas_apply(cfs_meas_mode_t m, cfs_ctrl_params_t *p, bool *infer_enabled)
{
    // Every branch reuses a C2a-verified controller path; only the inference
    // enable is new. theta is deliberately left at whatever the operator set,
    // so a gate run measured here uses the same threshold C2a accepted.
    switch (m) {
        case CFS_MEAS_IDLE_SKIP:
            p->mode = CFS_MODE_IDLE_SKIP;   // pure CLOSED, gate not computed
            *infer_enabled = false;
            break;
        case CFS_MEAS_GATE:
            p->mode = CFS_MODE_GATE;        // motion gate + R-refresh, R=10
            p->R    = 10;
            *infer_enabled = false;         // gate cost without inference cost
            break;
        case CFS_MEAS_ACTIVE:
            p->mode = CFS_MODE_ACTIVE;      // a = 1
            *infer_enabled = true;
            break;
        case CFS_MEAS_CTRL_K10:
            p->mode = CFS_MODE_SWEEP; p->sweep_k = 10; *infer_enabled = true; break;
        case CFS_MEAS_CTRL_K5:
            p->mode = CFS_MODE_SWEEP; p->sweep_k = 5;  *infer_enabled = true; break;
        case CFS_MEAS_CTRL_K2:
            p->mode = CFS_MODE_SWEEP; p->sweep_k = 2;  *infer_enabled = true; break;
        default:
            *infer_enabled = true;
            break;
    }
}

// ---- arm record -------------------------------------------------------------

esp_err_t cfs_meas_arm(cfs_meas_mode_t m, uint32_t seconds)
{
    if (!s_ready) return ESP_ERR_INVALID_STATE;
    nvs_handle_t h;
    esp_err_t err = nvs_open(NS, NVS_READWRITE, &h);
    if (err != ESP_OK) return err;
    err = nvs_set_u8(h, K_ARM_M, (uint8_t)m);
    if (err == ESP_OK) err = nvs_set_u32(h, K_ARM_S, seconds);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    return err;
}

esp_err_t cfs_meas_disarm(void)
{
    if (!s_ready) return ESP_ERR_INVALID_STATE;
    nvs_handle_t h;
    esp_err_t err = nvs_open(NS, NVS_READWRITE, &h);
    if (err != ESP_OK) return err;
    // ESP_ERR_NVS_NOT_FOUND simply means "was not armed" — not an error here.
    esp_err_t e1 = nvs_erase_key(h, K_ARM_M);
    esp_err_t e2 = nvs_erase_key(h, K_ARM_S);
    (void)e1; (void)e2;
    err = nvs_commit(h);
    nvs_close(h);
    return err;
}

bool cfs_meas_peek_arm(cfs_meas_mode_t *m, uint32_t *seconds)
{
    if (!s_ready) return false;
    nvs_handle_t h;
    if (nvs_open(NS, NVS_READONLY, &h) != ESP_OK) return false;
    uint8_t mm = 0; uint32_t ss = 0;
    bool ok = (nvs_get_u8(h, K_ARM_M, &mm) == ESP_OK) &&
              (nvs_get_u32(h, K_ARM_S, &ss) == ESP_OK);
    nvs_close(h);
    if (!ok || mm >= CFS_MEAS_MODE_COUNT || ss == 0) return false;
    if (m)       *m = (cfs_meas_mode_t)mm;
    if (seconds) *seconds = ss;
    return true;
}

bool cfs_meas_take_arm(cfs_meas_mode_t *m, uint32_t *seconds)
{
    if (!cfs_meas_peek_arm(m, seconds)) return false;
    // Clear and commit BEFORE the caller starts the run: a brownout or a crash
    // partway through must not leave the board re-arming on every boot.
    esp_err_t err = cfs_meas_disarm();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "could not clear arm record (%s) — refusing to run so the "
                      "board cannot loop", esp_err_to_name(err));
        return false;
    }
    // The sampler is started from here, and harvested from cfs_meas_store(),
    // because those are the two points the run's owner already calls. app_main
    // is C2a-accepted code and is deliberately left untouched by firmware v2.
    power_start(seconds ? *seconds : 0);
    return true;
}

// ---- power sampling task (v2) ----------------------------------------------
//
// A dedicated FreeRTOS task, NOT a call from the frame loop. Sampling from the
// capture loop would tie every sample to a fixed point in the frame period —
// the exact phase-locking that CFS_INA219_CONFIG_RUN's 68.1 ms averaging is
// there to defeat. An independent task at a period coprime to nothing in
// particular, reading integrals rather than points, is the honest arrangement.
//
//   run starts -> wait CFS_MEAS_DISCARD_MS (warm-up, discarded)
//              -> cfs_ina219_start()   (accumulators zeroed here, so the
//                                       warm-up contributes nothing)
//              -> every CFS_MEAS_SAMPLE_MS: cfs_ina219_sample()
//              -> stopped by cfs_meas_store() -> means harvested into the record

static TaskHandle_t   s_pow_task   = nullptr;
static volatile bool  s_pow_stop   = false;
static volatile bool  s_pow_window = false;   // the post-warm-up window ran

uint32_t cfs_meas_power_expected(uint32_t elapsed_ms)
{
    if (elapsed_ms <= CFS_MEAS_DISCARD_MS) return 0;
    return (elapsed_ms - CFS_MEAS_DISCARD_MS) / CFS_MEAS_SAMPLE_MS;
}

// Sleep in slices so a stop request is honoured promptly.
static bool sleep_until(int64_t t_end_us)
{
    while (esp_timer_get_time() < t_end_us) {
        if (s_pow_stop) return false;
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    return !s_pow_stop;
}

static void power_task(void *arg)
{
    const uint32_t secs = (uint32_t)(uintptr_t)arg;

    if (!cfs_ina219_available()) {
        // Not an abort: the run is still valid as a timing run. It is stored
        // with power_samples = 0 and no invented power values.
        ESP_LOGE(TAG, "power sampling: INA219 unavailable — run will be stored "
                      "with power_samples=0 (no values are invented)");
        s_pow_task = nullptr;
        vTaskDelete(nullptr);
        return;
    }
    if ((uint64_t)secs * 1000ULL <= (uint64_t)CFS_MEAS_DISCARD_MS) {
        ESP_LOGW(TAG, "power sampling: run of %lus does not outlast the %ums "
                      "warm-up discard — no power window, power_samples=0",
                 (unsigned long)secs, (unsigned)CFS_MEAS_DISCARD_MS);
        s_pow_task = nullptr;
        vTaskDelete(nullptr);
        return;
    }

    const int64_t t0 = esp_timer_get_time();
    if (sleep_until(t0 + (int64_t)CFS_MEAS_DISCARD_MS * 1000)) {
        cfs_ina219_start();      // discard everything from the warm-up
        s_pow_window = true;
        ESP_LOGI(TAG, "power sampling: window open, %ums cadence, expect ~%lu "
                      "samples", (unsigned)CFS_MEAS_SAMPLE_MS,
                 (unsigned long)cfs_meas_power_expected(secs * 1000));
        // Hard stop a little past the nominal end, in case the owner never
        // calls store (crash, abandoned run): the task must not outlive the run.
        const int64_t t_hard = t0 + ((int64_t)secs + 5) * 1000000;
        while (!s_pow_stop && esp_timer_get_time() < t_hard) {
            cfs_ina219_sample();
            vTaskDelay(pdMS_TO_TICKS(CFS_MEAS_SAMPLE_MS));
        }
    }
    s_pow_task = nullptr;
    vTaskDelete(nullptr);
}

static void power_start(uint32_t seconds)
{
    if (s_pow_task) cfs_meas_power_abort();
    s_pow_stop   = false;
    s_pow_window = false;
    if (xTaskCreate(power_task, "cfs_power", 3072,
                    (void *)(uintptr_t)seconds, 4, &s_pow_task) != pdPASS) {
        s_pow_task = nullptr;
        ESP_LOGE(TAG, "power sampling: task create failed — run will be stored "
                      "with power_samples=0");
    }
}

// Stop the sampler and wait for it to leave the I2C bus, bounded so a wedged
// task can never hang the run's completion.
static void power_join(void)
{
    s_pow_stop = true;
    for (int i = 0; i < 200 && s_pow_task != nullptr; ++i)
        vTaskDelay(pdMS_TO_TICKS(10));
    if (s_pow_task != nullptr)
        ESP_LOGE(TAG, "power sampling: task did not exit within 2 s");
}

void cfs_meas_power_abort(void)
{
    if (!s_pow_task && !s_pow_window) return;
    power_join();
    s_pow_window = false;
    ESP_LOGW(TAG, "power sampling: aborted, nothing stored");
}

// Harvest into the record. Never substitutes a value: if no window ran, the
// four power fields stay zero and power_samples = 0 says so unambiguously.
static void power_harvest(cfs_meas_summary_t *s)
{
    power_join();
    if (!s_pow_window) {
        s->mean_mw = 0.0f; s->mean_v = 0.0f; s->mean_ma = 0.0f;
        s->power_samples = 0;
        return;
    }
    cfs_ina219_reading_t r;
    cfs_ina219_get(&r);
    s->mean_mw       = r.mean_mw;
    s->mean_v        = r.mean_v;
    s->mean_ma       = r.mean_ma;
    s->power_samples = r.samples;

    // A starved sampler silently shortens the averaging window, so say so.
    uint32_t expect = cfs_meas_power_expected(s->elapsed_ms);
    if (expect > 0) {
        double dev = fabs((double)r.samples - (double)expect) / (double)expect;
        if (dev > 0.05) {
            ESP_LOGE(TAG, "power sampling: %lu samples vs %lu expected (%.1f%% "
                          "off) — sampler was starved; treat this run as suspect",
                     (unsigned long)r.samples, (unsigned long)expect, dev * 100.0);
            printf("MEASURE power_sample_shortfall got=%lu expect=%lu dev=%.1f%%\n",
                   (unsigned long)r.samples, (unsigned long)expect, dev * 100.0);
        }
    }
    s_pow_window = false;
}

// ---- stored summaries -------------------------------------------------------

int cfs_meas_count(void)
{
    if (!s_ready) return 0;
    nvs_handle_t h;
    if (nvs_open(NS, NVS_READONLY, &h) != ESP_OK) return 0;
    uint32_t n = 0;
    if (nvs_get_u32(h, K_COUNT, &n) != ESP_OK) n = 0;
    nvs_close(h);
    if (n > CFS_MEAS_MAX_RUNS) n = CFS_MEAS_MAX_RUNS;
    return (int)n;
}

uint32_t cfs_meas_next_run_id(void)
{
    if (!s_ready) return 1;
    nvs_handle_t h;
    if (nvs_open(NS, NVS_READONLY, &h) != ESP_OK) return 1;
    uint32_t seq = 0;
    if (nvs_get_u32(h, K_SEQ, &seq) != ESP_OK) seq = 1;
    nvs_close(h);
    return seq ? seq : 1;
}

esp_err_t cfs_meas_store(cfs_meas_summary_t *s)
{
    if (!s_ready) return ESP_ERR_INVALID_STATE;
    if (!s)       return ESP_ERR_INVALID_ARG;

    // Stop the sampler and fold its means in before anything is written, so the
    // record is complete or absent — never half-written.
    power_harvest(s);

    nvs_handle_t h;
    esp_err_t err = nvs_open(NS, NVS_READWRITE, &h);
    if (err != ESP_OK) return err;

    uint32_t n = 0;
    if (nvs_get_u32(h, K_COUNT, &n) != ESP_OK) n = 0;
    if (n >= CFS_MEAS_MAX_RUNS) { nvs_close(h); return ESP_ERR_NO_MEM; }

    uint32_t seq = 0;
    if (nvs_get_u32(h, K_SEQ, &seq) != ESP_OK) seq = 1;
    if (seq == 0) seq = 1;

    s->version = CFS_MEAS_REC_VERSION;
    s->run_id  = seq;

    char key[8];
    rec_key((int)n, key, sizeof(key));
    err = nvs_set_blob(h, key, s, sizeof(*s));
    if (err == ESP_OK) err = nvs_set_u32(h, K_COUNT, n + 1);
    if (err == ESP_OK) err = nvs_set_u32(h, K_SEQ, seq + 1);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    return err;
}

esp_err_t cfs_meas_get(int idx, cfs_meas_summary_t *out)
{
    if (!s_ready) return ESP_ERR_INVALID_STATE;
    if (!out || idx < 0 || idx >= CFS_MEAS_MAX_RUNS) return ESP_ERR_INVALID_ARG;
    nvs_handle_t h;
    esp_err_t err = nvs_open(NS, NVS_READONLY, &h);
    if (err != ESP_OK) return err;
    char key[8];
    rec_key(idx, key, sizeof(key));
    size_t len = sizeof(*out);
    err = nvs_get_blob(h, key, out, &len);
    nvs_close(h);
    if (err != ESP_OK) return err;
    if (len != sizeof(*out) || out->version != CFS_MEAS_REC_VERSION)
        return ESP_ERR_INVALID_VERSION;
    return ESP_OK;
}

esp_err_t cfs_meas_clear(void)
{
    if (!s_ready) return ESP_ERR_INVALID_STATE;
    nvs_handle_t h;
    esp_err_t err = nvs_open(NS, NVS_READWRITE, &h);
    if (err != ESP_OK) return err;
    for (int i = 0; i < CFS_MEAS_MAX_RUNS; ++i) {
        char key[8];
        rec_key(i, key, sizeof(key));
        nvs_erase_key(h, key);   // NOT_FOUND is fine
    }
    err = nvs_set_u32(h, K_COUNT, 0);
    if (err == ESP_OK) err = nvs_commit(h);
    nvs_close(h);
    return err;
}
