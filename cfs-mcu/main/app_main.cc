// app_main.cc — cfs-mcu entry point.
//
// Boots the camera (autodetect), the TFLM person-detection interpreter, and the
// serial command task, then runs the capture -> controller -> (maybe) inference
// loop paced to 30 fps. Every reported number originates here and is emitted
// over serial (STATS), which the host driver logs to CSV — no fabricated data.
#include "cfs_runtime.h"
#include "app_camera.h"
#include "controller.h"
#include "serial_cmd.h"
#include "ina219.h"
#include "meas.h"

#include "esp_log.h"
#include "esp_timer.h"
#include "esp_heap_caps.h"
#include "esp_psram.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"

static const char *TAG = "cfs_main";

// ---- Vendored model (see main/model/) --------------------------------------
extern const unsigned char g_person_detect_model_data[];
extern const int           g_person_detect_model_data_len;

// ---- Model settings (MLPerf-Tiny person detection, 96x96 int8) --------------
static const int kNumCols = 96, kNumRows = 96;
static const int kImgSize = kNumCols * kNumRows;   // == CFS_IMG_SIZE
static const int kPersonIndex    = 1;              // output index for "person"
static const int kNotAPersonIndex = 0;             // polarity confirmed by test 2

// ---- Shared runtime state ---------------------------------------------------
cfs_runtime_t g_rt;
SemaphoreHandle_t g_rt_mutex;

void cfs_rt_reset_stats(void)
{
    cfs_ctrl_reset();
    cfs_rt_lock();
    g_rt.frames_total = 0;
    g_rt.opens_total  = 0;
    g_rt.infer_count  = 0;
    g_rt.infer_us_sum = 0;
    g_rt.infer_us_max = 0;
    g_rt.window_frames = 0;
    g_rt.window_opens  = 0;
    g_rt.window_start_us = esp_timer_get_time();   // for honest windowed fps
    cfs_rt_unlock();
}

// ---- TFLM interpreter (statically sized arena in PSRAM) ---------------------
static const size_t kArenaSize = 160 * 1024;   // person_detection headroom
static uint8_t *s_arena = nullptr;

static tflite::MicroInterpreter *s_interp = nullptr;
static TfLiteTensor *s_input = nullptr;
static TfLiteTensor *s_output = nullptr;

static bool tflm_setup(void)
{
    const tflite::Model *model = tflite::GetModel(g_person_detect_model_data);
    if (model->version() != TFLITE_SCHEMA_VERSION) {
        ESP_LOGE(TAG, "model schema %lu != supported %d",
                 (unsigned long)model->version(), TFLITE_SCHEMA_VERSION);
        return false;
    }

    s_arena = (uint8_t *)heap_caps_malloc(kArenaSize, MALLOC_CAP_SPIRAM);
    if (!s_arena) {
        ESP_LOGE(TAG, "arena alloc %u failed (PSRAM?)", (unsigned)kArenaSize);
        return false;
    }

    // Op set for the MobileNetV1 person-detection graph.
    static tflite::MicroMutableOpResolver<6> resolver;
    resolver.AddAveragePool2D();
    resolver.AddConv2D();
    resolver.AddDepthwiseConv2D();
    resolver.AddReshape();
    resolver.AddSoftmax();
    resolver.AddFullyConnected();

    static tflite::MicroInterpreter interp(model, resolver, s_arena, kArenaSize);
    s_interp = &interp;
    if (s_interp->AllocateTensors() != kTfLiteOk) {
        ESP_LOGE(TAG, "AllocateTensors failed");
        return false;
    }
    s_input  = s_interp->input(0);
    s_output = s_interp->output(0);
    ESP_LOGI(TAG, "TFLM ready: arena=%uKB used=%uB in=%dx%dx%d",
             (unsigned)(kArenaSize / 1024),
             (unsigned)s_interp->arena_used_bytes(),
             s_input->dims->data[1], s_input->dims->data[2],
             (s_input->dims->size > 3 ? s_input->dims->data[3] : 1));
    return true;
}

// ---- Boot banner (acceptance test 1) ---------------------------------------
static void print_banner(void)
{
    size_t psram_total = 0;
#if CONFIG_SPIRAM
    psram_total = esp_psram_get_size();
#endif
    ESP_LOGI(TAG, "================ cfs-mcu boot ================");
    ESP_LOGI(TAG, "PSRAM total: %u bytes (%.1f MB) mode=%s",
             (unsigned)psram_total, psram_total / (1024.0 * 1024.0),
#if CONFIG_SPIRAM_MODE_OCT
             "Octal(OPI)"
#else
             "Quad(QPI) -- WRONG for N16R8, camera may fail"
#endif
    );
    ESP_LOGI(TAG, "PSRAM free : %u bytes",
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
    ESP_LOGI(TAG, "Camera     : pinmap=%s sensor=%s",
             cfs_camera_pinmap_name(), cfs_camera_sensor_name());
    ESP_LOGI(TAG, "Model      : person_detection, %d bytes",
             g_person_detect_model_data_len);
    ESP_LOGI(TAG, "==============================================");
}

extern "C" void app_main(void)
{
    g_rt_mutex = xSemaphoreCreateMutex();

    // Defaults: idle mode, R=10, theta=8.0, sweep_k=10.
    g_rt.params.mode    = CFS_MODE_IDLE;
    g_rt.params.R       = 10;
    g_rt.params.theta   = 8.0f;
    g_rt.params.sweep_k = 10;
    g_rt.power_sampling = false;
    g_rt.infer_enabled  = true;
    g_rt.parked         = false;
    g_rt.meas_running   = false;
    g_rt.meas_mode      = (uint8_t)CFS_MEAS_NONE;
    g_rt.fps = 0.0f;
    cfs_rt_reset_stats();

    if (cfs_camera_init() != ESP_OK) {
        ESP_LOGE(TAG, "CAMERA INIT FAILED — STOP. Report the init errors above "
                      "and a photo of the board's FPC connector to the user.");
        // Halt loudly rather than emit meaningless data.
        while (true) { vTaskDelay(pdMS_TO_TICKS(1000)); }
    }

    if (!tflm_setup()) {
        ESP_LOGE(TAG, "TFLM SETUP FAILED — STOP.");
        while (true) { vTaskDelay(pdMS_TO_TICKS(1000)); }
    }

    cfs_ina219_init();          // inert unless CONFIG_CFS_HAS_INA219
    cfs_meas_init();            // NVS for the C2b boot-armed protocol
    print_banner();
    cfs_serial_start();

    // ---- C2b: was a measurement run armed before the power cycle? -----------
    // Consumed one-shot (see cfs_meas_take_arm): the arm record is erased and
    // committed before the run begins.
    {
        cfs_meas_mode_t mm = CFS_MEAS_NONE;
        uint32_t secs = 0;
        if (cfs_meas_take_arm(&mm, &secs)) {
            cfs_ctrl_params_t p;
            bool infer = true;
            cfs_rt_lock();
            p = g_rt.params;
            cfs_rt_unlock();
            cfs_meas_apply(mm, &p, &infer);

            int64_t now = esp_timer_get_time();
            cfs_rt_lock();
            g_rt.params        = p;
            g_rt.infer_enabled = infer;
            g_rt.parked        = false;
            g_rt.meas_running  = true;
            g_rt.meas_mode     = (uint8_t)mm;
            g_rt.meas_start_us = (uint64_t)now;
            g_rt.meas_end_us   = (uint64_t)now + (uint64_t)secs * 1000000ULL;
            cfs_rt_unlock();
            cfs_rt_reset_stats();

            ESP_LOGI(TAG, "MEASURE armed run starting: mode=%s secs=%lu "
                          "(R=%d theta=%.2f k=%d infer=%d) run_id=%lu",
                     cfs_meas_mode_name(mm), (unsigned long)secs,
                     p.R, p.theta, p.sweep_k, infer ? 1 : 0,
                     (unsigned long)cfs_meas_next_run_id());
            printf("MEASURE start mode=%s secs=%lu run_id=%lu\n",
                   cfs_meas_mode_name(mm), (unsigned long)secs,
                   (unsigned long)cfs_meas_next_run_id());
        } else {
            ESP_LOGI(TAG, "no boot-armed measurement (MEASURE <mode> <secs> "
                          "on-boot to arm)");
        }
    }

    ESP_LOGI(TAG, "entering loop (default MODE idle R=10). Send HELP over serial.");

    const int64_t kFramePeriodUs = 33333;   // 30 fps target

    for (;;) {
        int64_t t_start = esp_timer_get_time();

        // ---- parked: post-run low-activity idle -----------------------------
        // After a boot-armed run completes the board must stop doing work so
        // the meter's trailing samples are unambiguous and so the operator can
        // unplug at leisure. No capture, no gate, no inference.
        cfs_rt_lock();
        bool parked = g_rt.parked;
        cfs_rt_unlock();
        if (parked) {
            vTaskDelay(pdMS_TO_TICKS(200));
            continue;
        }

        const uint8_t *luma = cfs_camera_capture();
        if (!luma) {
            cfs_camera_return();
            vTaskDelay(pdMS_TO_TICKS(5));
            continue;
        }

        cfs_ctrl_params_t params;
        bool power_on, infer_enabled;
        cfs_rt_lock();
        params        = g_rt.params;
        power_on      = g_rt.power_sampling;
        infer_enabled = g_rt.infer_enabled;
        cfs_rt_unlock();

        bool open = cfs_ctrl_decide(&params, luma);

        uint32_t infer_us = 0;
        int32_t person = 0, noperson = 0;
        bool did_infer = false;
        // `open` is still recorded when inference is disabled: the activation
        // fraction a = opens/frames is a property of the controller, not of
        // whether the detector was allowed to run. The C2b `gate` mode relies
        // on exactly this to price the gate separately from the detector.
        if (open && infer_enabled) {
            for (int i = 0; i < kImgSize; ++i)
                s_input->data.int8[i] = (int8_t)((int)luma[i] - 128);
            int64_t t0 = esp_timer_get_time();
            TfLiteStatus st = s_interp->Invoke();
            int64_t t1 = esp_timer_get_time();
            if (st == kTfLiteOk) {
                infer_us = (uint32_t)(t1 - t0);
                person   = s_output->data.int8[kPersonIndex];
                noperson = s_output->data.int8[kNotAPersonIndex];
                did_infer = true;
            } else {
                ESP_LOGW(TAG, "Invoke failed");
            }
        }

        if (power_on) cfs_ina219_sample();

        cfs_camera_return();

        // ---- stats update ----
        cfs_rt_lock();
        g_rt.frames_total++;
        if (open) g_rt.opens_total++;
        if (did_infer) {
            g_rt.infer_count++;
            g_rt.infer_us_sum += infer_us;
            if (infer_us > g_rt.infer_us_max) g_rt.infer_us_max = infer_us;
            g_rt.last_person_score    = person;
            g_rt.last_noperson_score  = noperson;
        }
        // fps is computed honestly in STATS as frames_total / wall-time.
        cfs_rt_unlock();

        // ---- soft controller invariant check (idle/sweep) ----
        if ((params.mode == CFS_MODE_IDLE || params.mode == CFS_MODE_SWEEP)) {
            int Reff = (params.mode == CFS_MODE_SWEEP) ? params.sweep_k : params.R;
            int mcr = cfs_ctrl_max_closed_run();
            if (mcr > Reff - 1) {
                ESP_LOGW(TAG, "INVARIANT: max_closed_run=%d > R-1=%d",
                         mcr, Reff - 1);
            }
        }

        // ---- C2b: boot-armed run reached its duration? ----------------------
        cfs_rt_lock();
        bool finish = g_rt.meas_running &&
                      (uint64_t)esp_timer_get_time() >= g_rt.meas_end_us;
        cfs_meas_summary_t summary = {};
        if (finish) {
            summary.mode        = g_rt.meas_mode;
            summary.frames      = g_rt.frames_total;
            summary.opens       = g_rt.opens_total;
            summary.infer_count = g_rt.infer_count;
            summary.elapsed_ms  = (uint32_t)(((uint64_t)esp_timer_get_time() -
                                              g_rt.meas_start_us) / 1000ULL);
            g_rt.meas_running = false;
            g_rt.parked       = true;   // drop to low-activity idle
        }
        if (finish) summary.max_closed_run = cfs_ctrl_max_closed_run();
        cfs_rt_unlock();

        if (finish) {
            // The frame buffer was already returned above, so no camera
            // resource is held while NVS is written.
            esp_err_t err = cfs_meas_store(&summary);
            double secs = summary.elapsed_ms / 1000.0;
            double fps  = (secs > 0.0) ? summary.frames / secs : 0.0;
            if (err == ESP_OK) {
                ESP_LOGI(TAG, "MEASURE done run_id=%lu mode=%s frames=%lu "
                              "opens=%lu infer=%lu elapsed_ms=%lu fps=%.2f",
                         (unsigned long)summary.run_id,
                         cfs_meas_mode_name((cfs_meas_mode_t)summary.mode),
                         (unsigned long)summary.frames,
                         (unsigned long)summary.opens,
                         (unsigned long)summary.infer_count,
                         (unsigned long)summary.elapsed_ms, fps);
                printf("MEASURE done run_id=%lu mode=%s frames=%lu opens=%lu "
                       "infer=%lu elapsed_ms=%lu fps=%.2f (parked)\n",
                       (unsigned long)summary.run_id,
                       cfs_meas_mode_name((cfs_meas_mode_t)summary.mode),
                       (unsigned long)summary.frames,
                       (unsigned long)summary.opens,
                       (unsigned long)summary.infer_count,
                       (unsigned long)summary.elapsed_ms, fps);
            } else {
                // Loud and unambiguous: a lost summary means the meter window it
                // pairs with is unusable, so the operator must know immediately.
                ESP_LOGE(TAG, "MEASURE STORE FAILED: %s — this run has NO "
                              "record and must be repeated", esp_err_to_name(err));
                printf("MEASURE store_failed err=%s\n", esp_err_to_name(err));
            }
            continue;
        }

        // ---- pace to 30 fps when inference latency allows ----
        int64_t elapsed = esp_timer_get_time() - t_start;
        int64_t remain  = kFramePeriodUs - elapsed;
        if (remain > 1000) {
            vTaskDelay(pdMS_TO_TICKS((remain) / 1000));
        } else {
            taskYIELD();   // free-run: report achieved fps honestly
        }
    }
}
