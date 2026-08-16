// ina219.cc — see ina219.h. Whole driver is gated on CONFIG_CFS_HAS_INA219.
#include "ina219.h"
#include "sdkconfig.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>

static const char *TAG = "cfs_ina219";
static cfs_ina219_reading_t s_r;
static double s_mw_accum = 0.0;
static double s_v_accum  = 0.0;
static double s_ma_accum = 0.0;

// The accumulators are touched by the measurement sampling task (meas.cc) and,
// for diagnostics, by the capture loop / POWER LIVE. Those never overlap in
// practice — a boot-armed run has no serial attached — but the arithmetic is a
// few instructions, so guarding it costs nothing and removes the question.
static portMUX_TYPE s_accum_mux = portMUX_INITIALIZER_UNLOCKED;

#ifdef CONFIG_CFS_HAS_INA219
// ---------------------------------------------------------------------------
// Active driver (C2b hardware present)
// ---------------------------------------------------------------------------
#include "driver/i2c_master.h"
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define INA219_REG_CONFIG      0x00
#define INA219_REG_BUSVOLTAGE  0x02
#define INA219_REG_POWER       0x03
#define INA219_REG_CURRENT     0x04
#define INA219_REG_CALIBRATION 0x05

static i2c_master_bus_handle_t s_bus = nullptr;
static i2c_master_dev_handle_t s_dev = nullptr;
static bool s_bus_ok = false;
static uint16_t s_init_config = 0;

// Calibration for a 0.1 ohm shunt, 3.2 A full scale (matches the INA219 module
// and the board's <0.8 A draw). current_LSB = 0.1 mA/bit; power_LSB = 2 mW/bit.
static const float CURRENT_LSB_MA = 0.1f;
static const float POWER_LSB_MW   = 2.0f;
static const uint16_t CAL_VALUE   = 4096;

// 100 kHz, not 400 kHz: the ESP32-S3 internal pull-ups are weak (~45 kOhm), and
// at 400 kHz the SDA/SCL rise time cannot be met if the INA219 breakout has no
// pull-up resistors of its own. Standard mode is the tolerant choice for
// bring-up; the sample rate this driver needs (>= 5 Hz) is nowhere near the
// bus limit either way.
#define INA219_SCL_HZ 100000

// Bring the bus up on its own, so an address scan is still possible when the
// sensor never ACKed (the FAIL path of C2b step A needs exactly that).
static esp_err_t bus_ensure(void)
{
    if (s_bus_ok) return ESP_OK;
    i2c_master_bus_config_t bus_cfg = {};
    bus_cfg.i2c_port = -1;                         // auto
    bus_cfg.sda_io_num = (gpio_num_t)CONFIG_CFS_INA219_SDA_GPIO;
    bus_cfg.scl_io_num = (gpio_num_t)CONFIG_CFS_INA219_SCL_GPIO;
    bus_cfg.clk_source = I2C_CLK_SRC_DEFAULT;
    bus_cfg.glitch_ignore_cnt = 7;
    bus_cfg.flags.enable_internal_pullup = true;
    esp_err_t err = i2c_new_master_bus(&bus_cfg, &s_bus);
    if (err != ESP_OK) { ESP_LOGE(TAG, "bus init 0x%x", err); return err; }
    s_bus_ok = true;
    return ESP_OK;
}

static esp_err_t reg_write(uint8_t reg, uint16_t val)
{
    if (!s_dev) return ESP_ERR_INVALID_STATE;
    uint8_t buf[3] = { reg, (uint8_t)(val >> 8), (uint8_t)(val & 0xFF) };
    return i2c_master_transmit(s_dev, buf, sizeof(buf), 100);
}

static esp_err_t reg_read(uint8_t reg, uint16_t *val)
{
    if (!s_dev) return ESP_ERR_INVALID_STATE;
    uint8_t out[2] = {0};
    esp_err_t err = i2c_master_transmit_receive(s_dev, &reg, 1, out, 2, 100);
    if (err == ESP_OK) *val = ((uint16_t)out[0] << 8) | out[1];
    return err;
}

esp_err_t cfs_ina219_init(void)
{
    memset(&s_r, 0, sizeof(s_r));
    esp_err_t err = bus_ensure();
    if (err != ESP_OK) return err;

    i2c_device_config_t dev_cfg = {};
    dev_cfg.dev_addr_length = I2C_ADDR_BIT_LEN_7;
    dev_cfg.device_address = CONFIG_CFS_INA219_ADDR;
    dev_cfg.scl_speed_hz = INA219_SCL_HZ;
    err = i2c_master_bus_add_device(s_bus, &dev_cfg, &s_dev);
    if (err != ESP_OK) { ESP_LOGE(TAG, "add dev 0x%x", err); return err; }

    // Does the chip ACK at all? Read reg 0x00 BEFORE writing it, so the value
    // we report is the chip's own power-on default (0x399F) and not an echo of
    // what we just wrote.
    uint16_t por = 0;
    esp_err_t rerr = reg_read(INA219_REG_CONFIG, &por);
    if (rerr != ESP_OK) {
        ESP_LOGE(TAG, "no ACK at 0x%02x reading CONFIG (err 0x%x) — sensor "
                      "absent or SDA/SCL swapped", CONFIG_CFS_INA219_ADDR, rerr);
        s_r.last_err = rerr;
        return rerr;
    }
    ESP_LOGI(TAG, "CONFIG(0x00) power-on readback = 0x%04X (expect 0x%04X)",
             por, CFS_INA219_CONFIG_POR);
    s_init_config = por;

    // Config: 32V range, /8 gain, 128-sample averaged ADC, continuous shunt+bus.
    // The POR read above is untouched — it is the bring-up evidence in
    // C2B_REPORT.md §A.8 and must keep reporting 0x399F.
    if (reg_write(INA219_REG_CONFIG, CFS_INA219_CONFIG_RUN) != ESP_OK) {
        ESP_LOGE(TAG, "config write failed (sensor absent?)");
        return ESP_FAIL;
    }
    uint16_t verify = 0;
    if (reg_read(INA219_REG_CONFIG, &verify) != ESP_OK ||
        verify != CFS_INA219_CONFIG_RUN) {
        ESP_LOGE(TAG, "config verify failed: wrote 0x%04X read 0x%04X",
                 CFS_INA219_CONFIG_RUN, verify);
        return ESP_FAIL;
    }
    // A silently failed CALIBRATION write is the worst possible outcome: the
    // CURRENT and POWER registers would then read a constant zero, which looks
    // like a measurement rather than like a fault. Fail loudly instead.
    esp_err_t cerr = reg_write(INA219_REG_CALIBRATION, CAL_VALUE);
    if (cerr != ESP_OK) {
        ESP_LOGE(TAG, "CALIBRATION write failed (0x%x, %s) — CURRENT/POWER "
                      "registers would read zero; not marking sensor ready",
                 cerr, esp_err_to_name(cerr));
        return cerr;
    }
    s_r.available = true;
    ESP_LOGI(TAG, "INA219 ready: SDA=%d SCL=%d addr=0x%02x config=0x%04X",
             CONFIG_CFS_INA219_SDA_GPIO, CONFIG_CFS_INA219_SCL_GPIO,
             CONFIG_CFS_INA219_ADDR, verify);
    return ESP_OK;
}

bool cfs_ina219_available(void) { return s_r.available; }

void cfs_ina219_sample(void)
{
    if (!s_r.available) return;
    uint16_t raw_bus = 0, raw_pow = 0, raw_cur = 0;
    esp_err_t e1 = reg_read(INA219_REG_BUSVOLTAGE, &raw_bus);
    esp_err_t e2 = reg_read(INA219_REG_POWER, &raw_pow);
    esp_err_t e3 = reg_read(INA219_REG_CURRENT, &raw_cur);
    s_r.last_err = (e1 != ESP_OK) ? e1 : ((e2 != ESP_OK) ? e2 : e3);
    s_r.raw_bus = raw_bus;
    s_r.raw_pow = raw_pow;
    s_r.raw_cur = raw_cur;
    s_r.bus_v      = (float)((raw_bus >> 3) * 4) / 1000.0f;   // LSB 4mV, bits[15:3]
    s_r.current_ma = (int16_t)raw_cur * CURRENT_LSB_MA;
    s_r.power_mw   = raw_pow * POWER_LSB_MW;

    // A read that errored carries no information, so it is not folded into the
    // mean and does not increment `samples`. That keeps the sample count an
    // honest denominator, and it makes a starved or faulting bus visible as a
    // sample-count shortfall instead of as a quietly biased average.
    if (s_r.last_err != ESP_OK) return;

    taskENTER_CRITICAL(&s_accum_mux);
    s_mw_accum += s_r.power_mw;
    s_v_accum  += s_r.bus_v;
    s_ma_accum += s_r.current_ma;
    s_r.samples++;
    s_r.mean_mw = (float)(s_mw_accum / (double)s_r.samples);
    s_r.mean_v  = (float)(s_v_accum  / (double)s_r.samples);
    s_r.mean_ma = (float)(s_ma_accum / (double)s_r.samples);
    taskEXIT_CRITICAL(&s_accum_mux);
}

esp_err_t cfs_ina219_probe_config(uint16_t *cfg_out)
{
    if (bus_ensure() != ESP_OK) return ESP_ERR_INVALID_STATE;
    if (!s_dev) {
        i2c_device_config_t dev_cfg = {};
        dev_cfg.dev_addr_length = I2C_ADDR_BIT_LEN_7;
        dev_cfg.device_address = CONFIG_CFS_INA219_ADDR;
        dev_cfg.scl_speed_hz = INA219_SCL_HZ;
        esp_err_t e = i2c_master_bus_add_device(s_bus, &dev_cfg, &s_dev);
        if (e != ESP_OK) return e;
    }
    uint16_t v = 0;
    esp_err_t err = reg_read(INA219_REG_CONFIG, &v);
    if (err == ESP_OK && cfg_out) *cfg_out = v;
    return err;
}

uint16_t cfs_ina219_init_config(void) { return s_init_config; }

int cfs_ina219_scan(uint8_t *out, int max_out)
{
    if (bus_ensure() != ESP_OK) return -1;
    int n = 0;
    for (uint8_t a = 0x08; a <= 0x77; ++a) {
        if (i2c_master_probe(s_bus, a, 50) == ESP_OK) {
            if (out && n < max_out) out[n] = a;
            n++;
        }
    }
    return n;
}

static int read_pin_with(gpio_num_t pin, bool pullup)
{
    gpio_config_t io = {};
    io.pin_bit_mask = 1ULL << (int)pin;
    io.mode = GPIO_MODE_INPUT;
    io.pull_up_en   = pullup ? GPIO_PULLUP_ENABLE : GPIO_PULLUP_DISABLE;
    io.pull_down_en = pullup ? GPIO_PULLDOWN_DISABLE : GPIO_PULLDOWN_ENABLE;
    io.intr_type = GPIO_INTR_DISABLE;
    gpio_config(&io);
    vTaskDelay(pdMS_TO_TICKS(20));    // let the RC of the line settle
    return gpio_get_level(pin);
}

esp_err_t cfs_ina219_pin_test(int *sda_pu, int *sda_pd, int *scl_pu, int *scl_pd)
{
    // Release the pins from the I2C peripheral first, else we read its idea of
    // the line rather than the wire's.
    if (s_dev) { i2c_master_bus_rm_device(s_dev); s_dev = nullptr; }
    if (s_bus) { i2c_del_master_bus(s_bus); s_bus = nullptr; }
    s_bus_ok = false;
    s_r.available = false;

    const gpio_num_t sda = (gpio_num_t)CONFIG_CFS_INA219_SDA_GPIO;
    const gpio_num_t scl = (gpio_num_t)CONFIG_CFS_INA219_SCL_GPIO;
    gpio_reset_pin(sda);
    gpio_reset_pin(scl);

    if (sda_pu) *sda_pu = read_pin_with(sda, true);
    if (scl_pu) *scl_pu = read_pin_with(scl, true);
    if (sda_pd) *sda_pd = read_pin_with(sda, false);
    if (scl_pd) *scl_pd = read_pin_with(scl, false);
    return ESP_OK;
}

int cfs_ina219_cfg_sda(void)  { return CONFIG_CFS_INA219_SDA_GPIO; }
int cfs_ina219_cfg_scl(void)  { return CONFIG_CFS_INA219_SCL_GPIO; }
int cfs_ina219_cfg_addr(void) { return CONFIG_CFS_INA219_ADDR; }

#else
// ---------------------------------------------------------------------------
// Inert stub (C2b hardware not yet present) — compiles, does nothing.
// ---------------------------------------------------------------------------
esp_err_t cfs_ina219_init(void)
{
    memset(&s_r, 0, sizeof(s_r));
    s_r.available = false;
    ESP_LOGI(TAG, "INA219 disabled (CONFIG_CFS_HAS_INA219 off) — C2b pending");
    return ESP_OK;
}
bool cfs_ina219_available(void) { return false; }
void cfs_ina219_sample(void) {}
esp_err_t cfs_ina219_probe_config(uint16_t *cfg_out)
{
    (void)cfg_out;
    return ESP_ERR_NOT_SUPPORTED;
}
uint16_t cfs_ina219_init_config(void) { return 0; }
int cfs_ina219_scan(uint8_t *out, int max_out)
{
    (void)out; (void)max_out;
    return -1;
}
int cfs_ina219_cfg_sda(void)  { return -1; }
int cfs_ina219_cfg_scl(void)  { return -1; }
int cfs_ina219_cfg_addr(void) { return 0; }
esp_err_t cfs_ina219_pin_test(int *sda_pu, int *sda_pd, int *scl_pu, int *scl_pd)
{
    (void)sda_pu; (void)sda_pd; (void)scl_pu; (void)scl_pd;
    return ESP_ERR_NOT_SUPPORTED;
}
#endif  // CONFIG_CFS_HAS_INA219

// Shared (mode-independent) accumulation control.
void cfs_ina219_start(void)
{
    taskENTER_CRITICAL(&s_accum_mux);
    s_mw_accum  = 0.0;
    s_v_accum   = 0.0;
    s_ma_accum  = 0.0;
    s_r.samples = 0;
    s_r.mean_mw = 0.0f;
    s_r.mean_v  = 0.0f;
    s_r.mean_ma = 0.0f;
    taskEXIT_CRITICAL(&s_accum_mux);
}
void cfs_ina219_stop(void) { /* mean stays latched for readout */ }

void cfs_ina219_get(cfs_ina219_reading_t *out)
{
    if (out) *out = s_r;
}
