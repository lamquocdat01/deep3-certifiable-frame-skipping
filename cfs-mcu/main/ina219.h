// ina219.h — INA219 I2C power-sensor driver for C2b energy measurement.
//
// Behind CONFIG_CFS_HAS_INA219. When the option is OFF, all functions are
// harmless no-ops and cfs_ina219_available() returns false, so `POWER on`
// reports "no sensor configured". When ON, samples bus voltage / current /
// power over I2C (default GPIO1=SDA, GPIO2=SCL, addr 0x40) and accumulates a
// running mean between POWER on/off for the E_idle / E_active protocol.
//
// C2b step A additions: cfs_ina219_probe_config() reads config register 0x00
// back off the chip (power-on default 0x399F) so bring-up can prove the chip
// ACKs, and cfs_ina219_scan() walks the whole 7-bit address space to diagnose
// a no-ACK (the classic cause being SDA/SCL swapped).
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define CFS_INA219_CONFIG_POR 0x399F   // datasheet power-on reset value of reg 0x00

// Operating config written at init (firmware v2). Differs from the POR value in
// the two ADC fields only:
//
//   BRNG 13    = 1     32 V bus range              (as POR)
//   PG   12:11 = 11    gain /8, +-320 mV           (as POR)
//   BADC 10:7  = 1111  128-sample average, 68.10 ms   (POR: 0011 = 1 sample, 532 us)
//   SADC 6:3   = 1111  128-sample average, 68.10 ms   (POR: 0011 = 1 sample, 532 us)
//   MODE 2:0   = 111   shunt+bus continuous        (as POR)
//
// Why averaging is mandatory here: the board's load is bursty at frame rate. A
// 532 us point sample taken from firmware locks onto a fixed phase of the frame
// period and biases the mean systematically. Each register read now returns the
// integral over 68.10 ms instead, which removes the phase-alignment problem in
// principle rather than by hoping the sampler drifts. A full shunt+bus cycle is
// 136.2 ms, so the sampling loop reads every CFS_MEAS_SAMPLE_MS (140 ms) — just
// past one cycle, so no conversion is read twice and none is skipped.
#define CFS_INA219_CONFIG_RUN 0x3FFF

typedef struct {
    float bus_v;        // last bus voltage (V)
    float current_ma;   // last current (mA)
    float power_mw;     // last power (mW)
    float mean_mw;      // mean power since last cfs_ina219_start() (mW)
    // mean_v and mean_ma exist so P ~= V x I can be checked after the fact.
    // power_mw comes from the chip's own POWER register (derived from the
    // CALIBRATION register), while bus_v and current_ma come from two other
    // registers — three quantities from independent paths. A disagreement worse
    // than ~2 % means arithmetic overflow or a bad calibration, and without
    // storing V and I that check is unavailable. There is no reference load
    // resistor on this bench, so this is the only cross-check available.
    float mean_v;       // mean bus voltage since last cfs_ina219_start() (V)
    float mean_ma;      // mean current since last cfs_ina219_start() (mA)
    uint32_t samples;   // sample count since start (failed reads not counted)
    bool available;     // sensor probed OK
    uint16_t raw_bus;   // last raw register 0x02 (bring-up evidence)
    uint16_t raw_cur;   // last raw register 0x04
    uint16_t raw_pow;   // last raw register 0x03
    esp_err_t last_err; // result of the last register read
} cfs_ina219_reading_t;

esp_err_t cfs_ina219_init(void);         // I2C + calibration; no-op if disabled
bool      cfs_ina219_available(void);
void      cfs_ina219_start(void);        // begin a measurement accumulation
void      cfs_ina219_stop(void);
void      cfs_ina219_sample(void);       // take one sample, fold into mean
void      cfs_ina219_get(cfs_ina219_reading_t *out);

// --- C2b step A bring-up helpers -------------------------------------------
// Direct read of config register 0x00. ESP_OK => the chip ACKed its address.
esp_err_t cfs_ina219_probe_config(uint16_t *cfg_out);
// Config value read back at init (0 if init never got that far).
uint16_t  cfs_ina219_init_config(void);
// Walk addresses 0x08..0x77, store every ACKing address in out[], return the
// count (or -1 if the I2C bus itself could not be brought up).
int       cfs_ina219_scan(uint8_t *out, int max_out);
// Compile-time pin/address config, readable when the driver is disabled too
// (returns -1 / 0 in that case) so serial_cmd need not be #ifdef'd.
int       cfs_ina219_cfg_sda(void);
int       cfs_ina219_cfg_scl(void);
int       cfs_ina219_cfg_addr(void);

// Electrical triage for a total no-ACK: tear the I2C bus down and read the two
// pins as plain GPIOs, once with the internal pull-up and once with the
// internal pull-down. Interpretation (per line):
//   pu=1 pd=0 -> floating: nothing is connected / module unpowered & no pull-ups
//   pu=1 pd=1 -> held HIGH externally: module powered, its pull-ups are working
//   pu=0 pd=0 -> held LOW externally: shorted to GND or clamped by a dead module
// Destroys the I2C bus: the board must be rebooted before POWER PROBE again.
esp_err_t cfs_ina219_pin_test(int *sda_pu, int *sda_pd, int *scl_pu, int *scl_pd);

#ifdef __cplusplus
}
#endif
