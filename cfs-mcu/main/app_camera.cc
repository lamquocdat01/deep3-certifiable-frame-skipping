// app_camera.cc — see app_camera.h
#include "app_camera.h"
#include "camera_pins.h"
#include "esp_camera.h"
#include "esp_log.h"
#include <string.h>

static const char *TAG = "cfs_cam";

static const char *s_pinmap_name = "none";
static const char *s_sensor_name = "unknown";
static camera_fb_t *s_fb = nullptr;

static camera_config_t make_config(const cfs_cam_pinmap_t *p)
{
    camera_config_t c = {};
    c.pin_pwdn = p->pin_pwdn;
    c.pin_reset = p->pin_reset;
    c.pin_xclk = p->pin_xclk;
    c.pin_sccb_sda = p->pin_sccb_sda;
    c.pin_sccb_scl = p->pin_sccb_scl;
    c.pin_d7 = p->pin_d7;
    c.pin_d6 = p->pin_d6;
    c.pin_d5 = p->pin_d5;
    c.pin_d4 = p->pin_d4;
    c.pin_d3 = p->pin_d3;
    c.pin_d2 = p->pin_d2;
    c.pin_d1 = p->pin_d1;
    c.pin_d0 = p->pin_d0;
    c.pin_vsync = p->pin_vsync;
    c.pin_href = p->pin_href;
    c.pin_pclk = p->pin_pclk;

    c.xclk_freq_hz = 20000000;
    c.ledc_timer = LEDC_TIMER_0;
    c.ledc_channel = LEDC_CHANNEL_0;

    // Capture 96x96 grayscale directly — matches the model input, so no resize.
    c.pixel_format = PIXFORMAT_GRAYSCALE;
    c.frame_size = FRAMESIZE_96X96;
    c.jpeg_quality = 12;
    c.fb_count = 2;
    c.fb_location = CAMERA_FB_IN_PSRAM;   // needs Octal PSRAM (see sdkconfig)
    c.grab_mode = CAMERA_GRAB_LATEST;
    return c;
}

static const char *sensor_pid_name(int pid)
{
    switch (pid) {
        case OV2640_PID: return "OV2640";
        case OV3660_PID: return "OV3660";
        case OV5640_PID: return "OV5640";
        case OV7725_PID: return "OV7725";
        default:         return "unknown";
    }
}

esp_err_t cfs_camera_init(void)
{
    for (int i = 0; i < CFS_CAM_CANDIDATE_COUNT; ++i) {
        const cfs_cam_pinmap_t *p = CFS_CAM_CANDIDATES[i];
        ESP_LOGI(TAG, "trying pin map [%d/%d]: %s", i + 1,
                 CFS_CAM_CANDIDATE_COUNT, p->name);

        camera_config_t cfg = make_config(p);
        esp_err_t err = esp_camera_init(&cfg);
        if (err != ESP_OK) {
            ESP_LOGW(TAG, "  init failed on %s: 0x%x (%s)", p->name, err,
                     esp_err_to_name(err));
            esp_camera_deinit();
            continue;
        }

        sensor_t *s = esp_camera_sensor_get();
        if (!s) {
            ESP_LOGW(TAG, "  sensor_get() null on %s", p->name);
            esp_camera_deinit();
            continue;
        }
        s_pinmap_name = p->name;
        s_sensor_name = sensor_pid_name(s->id.PID);
        ESP_LOGI(TAG, "camera OK: pinmap=%s sensor=%s (PID=0x%02x)",
                 s_pinmap_name, s_sensor_name, s->id.PID);

        // Sensor-specific tweaks for a 96x96 grayscale wake-word style view.
        if (s->id.PID == OV3660_PID) {
            s->set_brightness(s, 1);
            s->set_saturation(s, -2);
        }
        s->set_vflip(s, 0);
        s->set_hmirror(s, 0);
        return ESP_OK;
    }
    ESP_LOGE(TAG, "no candidate pin map initialised the camera — STOP: "
                  "check FPC seating, PSRAM=Octal, and report init errors");
    return ESP_FAIL;
}

const uint8_t *cfs_camera_capture(void)
{
    s_fb = esp_camera_fb_get();
    if (!s_fb) {
        ESP_LOGW(TAG, "fb_get failed");
        return nullptr;
    }
    // GRAYSCALE 96x96 => exactly CFS_IMG_SIZE luma bytes.
    if (s_fb->len < (size_t)CFS_IMG_SIZE) {
        ESP_LOGW(TAG, "short frame: len=%u", (unsigned)s_fb->len);
        esp_camera_fb_return(s_fb);
        s_fb = nullptr;
        return nullptr;
    }
    return s_fb->buf;
}

void cfs_camera_return(void)
{
    if (s_fb) {
        esp_camera_fb_return(s_fb);
        s_fb = nullptr;
    }
}

const char *cfs_camera_pinmap_name(void) { return s_pinmap_name; }
const char *cfs_camera_sensor_name(void) { return s_sensor_name; }
