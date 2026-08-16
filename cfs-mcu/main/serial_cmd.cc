// serial_cmd.cc — see serial_cmd.h
#include "serial_cmd.h"
#include "cfs_runtime.h"
#include "ina219.h"
#include "meas.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "esp_err.h"
#include "driver/uart.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <ctype.h>
#include <math.h>

static const char *TAG = "cfs_cmd";
#define CFS_LINE_MAX 128

static const char *mode_name(cfs_mode_t m)
{
    switch (m) {
        case CFS_MODE_IDLE:      return "idle";
        case CFS_MODE_ACTIVE:    return "active";
        case CFS_MODE_GATE:      return "gate";
        case CFS_MODE_SWEEP:     return "sweep";
        case CFS_MODE_IDLE_SKIP: return "idle-skip";
        default:                 return "?";
    }
}

void cfs_serial_format_stats(char *buf, int buflen)
{
    cfs_rt_lock();
    uint32_t frames = g_rt.frames_total;
    uint32_t opens  = g_rt.opens_total;
    uint32_t nin    = g_rt.infer_count;
    double mean_us  = nin ? (double)g_rt.infer_us_sum / (double)nin : 0.0;
    uint32_t max_us = g_rt.infer_us_max;
    uint64_t win_start = g_rt.window_start_us;
    int32_t ps      = g_rt.last_person_score;
    int32_t nps     = g_rt.last_noperson_score;
    cfs_mode_t mode = g_rt.params.mode;
    int R           = g_rt.params.R;
    float theta     = g_rt.params.theta;
    int sweep_k     = g_rt.params.sweep_k;
    bool pwr_on     = g_rt.power_sampling;
    bool infer_en   = g_rt.infer_enabled;
    bool parked     = g_rt.parked;
    bool meas_run   = g_rt.meas_running;
    cfs_rt_unlock();

    // Honest achieved fps = frames processed / wall-clock since last reset.
    double win_s = (double)(esp_timer_get_time() - (int64_t)win_start) / 1e6;
    float fps = (win_s > 0.0) ? (float)(frames / win_s) : 0.0f;
    double open_frac = frames ? (double)opens / (double)frames : 0.0;
    int max_closed   = cfs_ctrl_max_closed_run();
    size_t heap_free = esp_get_free_heap_size();
    size_t psram_free = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);

    cfs_ina219_reading_t pr;
    cfs_ina219_get(&pr);

    // Single-line, machine-parseable JSON prefixed with "STATS ".
    snprintf(buf, buflen,
        "STATS {\"mode\":\"%s\",\"R\":%d,\"theta\":%.2f,\"sweep_k\":%d,"
        "\"fps\":%.2f,\"open_frac\":%.4f,\"frames\":%lu,\"opens\":%lu,"
        "\"infer_count\":%lu,\"infer_us_mean\":%.1f,\"infer_us_max\":%lu,"
        "\"max_closed_run\":%d,\"person\":%ld,\"noperson\":%ld,"
        "\"heap_free\":%u,\"psram_free\":%u,"
        "\"power_on\":%d,\"ina219\":%d,\"power_mw_mean\":%.2f,\"power_samples\":%lu,"
        "\"infer_enabled\":%d,\"parked\":%d,\"meas_running\":%d,\"stored_runs\":%d}",
        mode_name(mode), R, theta, sweep_k,
        fps, open_frac, (unsigned long)frames, (unsigned long)opens,
        (unsigned long)nin, mean_us, (unsigned long)max_us,
        max_closed, (long)ps, (long)nps,
        (unsigned)heap_free, (unsigned)psram_free,
        pwr_on ? 1 : 0, pr.available ? 1 : 0, pr.mean_mw,
        (unsigned long)pr.samples,
        infer_en ? 1 : 0, parked ? 1 : 0, meas_run ? 1 : 0, cfs_meas_count());
}

static void to_lower(char *s) { for (; *s; ++s) *s = (char)tolower((unsigned char)*s); }

static void handle_line(char *line)
{
    // Tokenize (keeps key=val tokens intact).
    char *tok[8];
    int ntok = 0;
    char *save = nullptr;
    for (char *t = strtok_r(line, " \t", &save); t && ntok < 8;
         t = strtok_r(nullptr, " \t", &save)) {
        tok[ntok++] = t;
    }
    if (ntok == 0) return;

    char cmd[16];
    strncpy(cmd, tok[0], sizeof(cmd) - 1);
    cmd[sizeof(cmd) - 1] = 0;
    to_lower(cmd);

    if (strcmp(cmd, "mode") == 0 && ntok >= 2) {
        char m[16];
        strncpy(m, tok[1], sizeof(m) - 1); m[sizeof(m) - 1] = 0; to_lower(m);
        cfs_mode_t nm;
        if      (strcmp(m, "idle") == 0)      nm = CFS_MODE_IDLE;
        else if (strcmp(m, "active") == 0)    nm = CFS_MODE_ACTIVE;
        else if (strcmp(m, "gate") == 0)      nm = CFS_MODE_GATE;
        else if (strcmp(m, "sweep") == 0)     nm = CFS_MODE_SWEEP;
        else if (strcmp(m, "idle-skip") == 0) nm = CFS_MODE_IDLE_SKIP;
        else { printf("ERR unknown mode '%s'\n", m); return; }

        int k = -1;
        for (int i = 2; i < ntok; ++i)
            if (strncasecmp(tok[i], "k=", 2) == 0) k = atoi(tok[i] + 2);

        cfs_rt_lock();
        g_rt.params.mode = nm;
        if (nm == CFS_MODE_SWEEP && k > 0) g_rt.params.sweep_k = k;
        // An interactive MODE always returns the board to plain C2a behaviour:
        // inference re-enabled, un-parked, and any in-flight boot-armed run
        // abandoned. This is what makes the C2a regression probe meaningful.
        g_rt.infer_enabled = true;
        g_rt.parked        = false;
        g_rt.meas_running  = false;
        cfs_rt_unlock();
        // The power sampler belongs to the abandoned run; it must not outlive it
        // and go on driving the I2C bus behind an interactive session.
        cfs_meas_power_abort();
        cfs_rt_reset_stats();
        printf("OK mode=%s sweep_k=%d\n", mode_name(nm),
               (nm == CFS_MODE_SWEEP) ? (k > 0 ? k : 0) : 0);

    } else if (strcmp(cmd, "set") == 0) {
        cfs_rt_lock();
        for (int i = 1; i < ntok; ++i) {
            if (strncasecmp(tok[i], "R=", 2) == 0)
                g_rt.params.R = atoi(tok[i] + 2);
            else if (strncasecmp(tok[i], "THETA=", 6) == 0)
                g_rt.params.theta = (float)atof(tok[i] + 6);
        }
        int R = g_rt.params.R; float th = g_rt.params.theta;
        cfs_rt_unlock();
        cfs_rt_reset_stats();
        printf("OK R=%d THETA=%.2f\n", R, th);

    // ---- C2b boot-armed measurement protocol -------------------------------
    } else if (strcmp(cmd, "measure") == 0) {
        if (ntok < 2) {
            printf("ERR usage: MEASURE <mode> <seconds> on-boot | MEASURE off | "
                   "MEASURE status\n");
            return;
        }
        char a[16];
        strncpy(a, tok[1], sizeof(a) - 1); a[sizeof(a) - 1] = 0; to_lower(a);

        if (strcmp(a, "off") == 0) {
            esp_err_t err = cfs_meas_disarm();
            printf(err == ESP_OK ? "OK MEASURE disarmed\n"
                                 : "ERR MEASURE disarm failed\n");
            return;
        }
        if (strcmp(a, "status") == 0) {
            cfs_meas_mode_t am; uint32_t as;
            if (cfs_meas_peek_arm(&am, &as))
                printf("MEASURE armed mode=%s secs=%lu stored=%d next_run_id=%lu\n",
                       cfs_meas_mode_name(am), (unsigned long)as,
                       cfs_meas_count(), (unsigned long)cfs_meas_next_run_id());
            else
                printf("MEASURE not-armed stored=%d next_run_id=%lu\n",
                       cfs_meas_count(), (unsigned long)cfs_meas_next_run_id());
            return;
        }

        cfs_meas_mode_t mm = cfs_meas_mode_from_name(a);
        if (mm == CFS_MEAS_NONE) {
            printf("ERR unknown measure mode '%s' (idle-skip|gate|active|"
                   "ctrl-k10|ctrl-k5|ctrl-k2)\n", a);
            return;
        }
        if (ntok < 3) { printf("ERR missing <seconds>\n"); return; }
        int secs = atoi(tok[2]);
        if (secs < 1 || secs > 3600) {
            printf("ERR seconds out of range (1..3600)\n");
            return;
        }
        // The literal `on-boot` is required, not optional: it is the only thing
        // distinguishing "arm across a power cycle" from a typo, and arming by
        // accident costs a whole meter session to notice.
        bool on_boot = false;
        for (int i = 3; i < ntok; ++i) {
            char t[16];
            strncpy(t, tok[i], sizeof(t) - 1); t[sizeof(t) - 1] = 0; to_lower(t);
            if (strcmp(t, "on-boot") == 0) on_boot = true;
        }
        if (!on_boot) {
            printf("ERR missing 'on-boot' keyword — MEASURE only arms across a "
                   "power cycle\n");
            return;
        }
        if (cfs_meas_count() >= CFS_MEAS_MAX_RUNS) {
            printf("ERR summary store full (%d) — DUMP then CLEAR first\n",
                   CFS_MEAS_MAX_RUNS);
            return;
        }
        esp_err_t err = cfs_meas_arm(mm, (uint32_t)secs);
        if (err != ESP_OK) {
            printf("ERR MEASURE arm failed: %s\n", esp_err_to_name(err));
            return;
        }
        printf("OK MEASURE armed mode=%s secs=%d run_id=%lu — power-cycle the "
               "board to run\n", cfs_meas_mode_name(mm), secs,
               (unsigned long)cfs_meas_next_run_id());

    } else if (strcmp(cmd, "dump") == 0) {
        int n = cfs_meas_count();
        printf("DUMP begin n=%d\n", n);
        // The v1 columns keep their order and position; the v2 power columns are
        // appended, so any existing parser keyed on the old header still works.
        printf("DUMP,run_id,mode,frames,opens,infer_count,elapsed_ms,fps,"
               "open_frac,max_closed_run,mean_mw,mean_v,mean_ma,power_samples\n");
        for (int i = 0; i < n; ++i) {
            cfs_meas_summary_t s;
            esp_err_t err = cfs_meas_get(i, &s);
            if (err != ESP_OK) {
                // Includes a stored v1 record: refused, never reinterpreted.
                printf("DUMP,ERR,idx=%d,%s\n", i, esp_err_to_name(err));
                continue;
            }
            double secs = s.elapsed_ms / 1000.0;
            double fps  = (secs > 0.0) ? s.frames / secs : 0.0;
            double of   = s.frames ? (double)s.opens / (double)s.frames : 0.0;
            printf("DUMP,%lu,%s,%lu,%lu,%lu,%lu,%.2f,%.4f,%ld,"
                   "%.2f,%.4f,%.2f,%lu\n",
                   (unsigned long)s.run_id,
                   cfs_meas_mode_name((cfs_meas_mode_t)s.mode),
                   (unsigned long)s.frames, (unsigned long)s.opens,
                   (unsigned long)s.infer_count, (unsigned long)s.elapsed_ms,
                   fps, of, (long)s.max_closed_run,
                   s.mean_mw, s.mean_v, s.mean_ma,
                   (unsigned long)s.power_samples);

            // Warnings go on their own "DUMPWARN," lines — deliberately NOT
            // "DUMP," — so they can never be parsed as CSV data rows.
            if (s.power_samples == 0) {
                printf("DUMPWARN,run_id=%lu,no_power_data,"
                       "run_not_longer_than_warmup_or_sensor_absent\n",
                       (unsigned long)s.run_id);
                continue;
            }
            uint32_t expect = cfs_meas_power_expected(s.elapsed_ms);
            if (expect > 0) {
                double dev = fabs((double)s.power_samples - (double)expect) /
                             (double)expect;
                if (dev > 0.05)
                    printf("DUMPWARN,run_id=%lu,sample_shortfall,got=%lu,"
                           "expect=%lu,dev=%.1f%%\n", (unsigned long)s.run_id,
                           (unsigned long)s.power_samples,
                           (unsigned long)expect, dev * 100.0);
            }
            // P ~= V x I across three independent registers. mean_v [V] x
            // mean_ma [mA] is already mW. Compared on magnitude: the POWER
            // register is unsigned, so a reversed-polarity hookup shows up as a
            // negative mean_ma against a positive mean_mw, which this catches
            // via the sign line below rather than by inflating the deviation.
            double pvi = (double)s.mean_v * (double)s.mean_ma;
            double ref = fabs((double)s.mean_mw);
            if (ref > 1.0) {
                double dev = fabs(fabs(pvi) - ref) / ref;
                if (dev > 0.02)
                    printf("DUMPWARN,run_id=%lu,p_vs_vi_mismatch,mean_mw=%.2f,"
                           "v_times_i=%.2f,dev=%.1f%%\n",
                           (unsigned long)s.run_id, s.mean_mw, pvi, dev * 100.0);
            }
            if (s.mean_ma < 0.0f)
                printf("DUMPWARN,run_id=%lu,negative_mean_current,mean_ma=%.2f,"
                       "current_flowed_VIN-_to_VIN+\n",
                       (unsigned long)s.run_id, s.mean_ma);
        }
        printf("DUMP end\n");

    } else if (strcmp(cmd, "clear") == 0) {
        int n = cfs_meas_count();
        esp_err_t err = cfs_meas_clear();
        if (err == ESP_OK)
            printf("OK CLEAR erased=%d (run ids stay monotonic; next=%lu)\n",
                   n, (unsigned long)cfs_meas_next_run_id());
        else
            printf("ERR CLEAR failed: %s\n", esp_err_to_name(err));

    } else if (strcmp(cmd, "stats") == 0) {
        char buf[768];   // grew with the C2b measurement fields
        cfs_serial_format_stats(buf, sizeof(buf));
        printf("%s\n", buf);

    } else if (strcmp(cmd, "power") == 0 && ntok >= 2) {
        char a[16];
        strncpy(a, tok[1], sizeof(a) - 1); a[sizeof(a) - 1] = 0; to_lower(a);

        // ---- C2b step A: prove the chip talks -----------------------------
        if (strcmp(a, "probe") == 0) {
            uint16_t cfg = 0;
            esp_err_t err = cfs_ina219_probe_config(&cfg);
            if (err == ESP_OK) {
                printf("PROBE addr=0x%02X sda=%d scl=%d reg0x00=0x%04X "
                       "por_expect=0x%04X ack=1 init_readback=0x%04X\n",
                       cfs_ina219_cfg_addr(), cfs_ina219_cfg_sda(),
                       cfs_ina219_cfg_scl(), cfg, CFS_INA219_CONFIG_POR,
                       cfs_ina219_init_config());
            } else {
                printf("PROBE addr=0x%02X sda=%d scl=%d ack=0 err=0x%x (%s)\n",
                       cfs_ina219_cfg_addr(), cfs_ina219_cfg_sda(),
                       cfs_ina219_cfg_scl(), err, esp_err_to_name(err));
            }
            return;
        }

        if (strcmp(a, "scan") == 0) {
            uint8_t found[16];
            int n = cfs_ina219_scan(found, (int)(sizeof(found)));
            if (n < 0) { printf("SCAN ERR i2c bus unavailable\n"); return; }
            printf("SCAN sda=%d scl=%d range=0x08..0x77 count=%d\n",
                   cfs_ina219_cfg_sda(), cfs_ina219_cfg_scl(), n);
            int shown = (n < (int)sizeof(found)) ? n : (int)sizeof(found);
            for (int i = 0; i < shown; ++i)
                printf("SCAN found=0x%02X\n", found[i]);
            printf("SCAN done\n");
            return;
        }

        if (strcmp(a, "pins") == 0) {
            int spu = -1, spd = -1, cpu = -1, cpd = -1;
            esp_err_t err = cfs_ina219_pin_test(&spu, &spd, &cpu, &cpd);
            if (err != ESP_OK) {
                printf("PINS ERR 0x%x (%s)\n", err, esp_err_to_name(err));
                return;
            }
            printf("PINS sda_gpio=%d pu=%d pd=%d | scl_gpio=%d pu=%d pd=%d\n",
                   cfs_ina219_cfg_sda(), spu, spd,
                   cfs_ina219_cfg_scl(), cpu, cpd);
            printf("PINS legend pu=1,pd=0 floating | pu=1,pd=1 held-HIGH(ok) | "
                   "pu=0,pd=0 held-LOW(short)\n");
            printf("PINS note i2c bus torn down — reboot before POWER PROBE\n");
            return;
        }

        if (strcmp(a, "live") == 0) {
            if (!cfs_ina219_available()) {
                printf("ERR INA219 not available — run POWER PROBE / POWER SCAN\n");
                return;
            }
            int secs = (ntok >= 3) ? atoi(tok[2]) : 10;
            if (secs <= 0 || secs > 120) secs = 10;
            // Own the I2C bus for the duration: keep the capture loop's
            // sampler off so only this task touches the device.
            cfs_rt_lock();
            bool prev = g_rt.power_sampling;
            g_rt.power_sampling = false;
            cfs_rt_unlock();

            // Diagnostic only. With the PC attached, its VBUS feeds the board
            // inside the shunt's span, so nothing read here is a measurement of
            // anything — an official number comes only from a boot-armed run.
            // Cadence matches the measurement path so this also exercises it.
            printf("LIVE start secs=%d addr=0x%02X interval_ms=%d "
                   "(diagnostic only, NOT a measurement — a measurement run is "
                   "MEASURE <mode> <secs> on-boot with the PC unplugged)\n",
                   secs, cfs_ina219_cfg_addr(), CFS_MEAS_SAMPLE_MS);
            cfs_ina219_start();          // mean reflects only this live window
            int64_t t0 = esp_timer_get_time();
            int64_t t_end = t0 + (int64_t)secs * 1000000;
            while (esp_timer_get_time() < t_end) {
                cfs_ina219_sample();
                cfs_ina219_reading_t r;
                cfs_ina219_get(&r);
                printf("LIVE t=%.2f bus_v=%.3f current_ma=%.1f power_mw=%.1f "
                       "raw_bus=0x%04X raw_cur=0x%04X raw_pow=0x%04X err=0x%x\n",
                       (double)(esp_timer_get_time() - t0) / 1e6,
                       r.bus_v, r.current_ma, r.power_mw,
                       r.raw_bus, r.raw_cur, r.raw_pow, r.last_err);
                vTaskDelay(pdMS_TO_TICKS(CFS_MEAS_SAMPLE_MS));
            }
            printf("LIVE done\n");
            cfs_rt_lock();
            g_rt.power_sampling = prev;
            cfs_rt_unlock();
            return;
        }

        bool on = (strcmp(a, "on") == 0);
        if (on && !cfs_ina219_available()) {
            printf("ERR no INA219 configured (build with CONFIG_CFS_HAS_INA219 "
                   "and wire C2b hardware)\n");
            return;
        }
        cfs_rt_lock();
        g_rt.power_sampling = on;
        cfs_rt_unlock();
        if (on) cfs_ina219_start(); else cfs_ina219_stop();
        printf("OK power=%s\n", on ? "on" : "off");

    } else if (strcmp(cmd, "help") == 0) {
        printf("CMDS: MODE idle|active|gate|sweep|idle-skip [k=N] | "
               "SET R=N THETA=F | STATS | "
               "POWER on|off|probe|scan|live [secs] | HELP\n");
        printf("C2b: MEASURE <idle-skip|gate|active|ctrl-k10|ctrl-k5|ctrl-k2> "
               "<seconds> on-boot | MEASURE off | MEASURE status | DUMP | CLEAR\n");
    } else {
        printf("ERR unknown cmd '%s' (try HELP)\n", cmd);
    }
}

static void serial_task(void *arg)
{
    // Install a plain UART0 RX driver for reliable line input across IDF v5.x.
    uart_driver_install(UART_NUM_0, 512, 0, 0, nullptr, 0);
    ESP_LOGI(TAG, "serial command interface ready @115200 (type HELP)");

    char line[CFS_LINE_MAX];
    int len = 0;
    uint8_t ch;
    for (;;) {
        int n = uart_read_bytes(UART_NUM_0, &ch, 1, pdMS_TO_TICKS(100));
        if (n <= 0) continue;
        if (ch == '\r' || ch == '\n') {
            if (len > 0) {
                line[len] = 0;
                handle_line(line);
                len = 0;
            }
        } else if (len < CFS_LINE_MAX - 1) {
            line[len++] = (char)ch;
        } else {
            len = 0;   // overflow: drop the line
        }
    }
}

void cfs_serial_start(void)
{
    xTaskCreate(serial_task, "cfs_serial", 4096, nullptr, 5, nullptr);
}
