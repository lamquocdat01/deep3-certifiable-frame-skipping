// app_camera.h — camera bring-up: autodetect pin map + sensor (OV2640/OV3660),
// capture 96x96 grayscale frames for the person-detection model.
#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

#define CFS_IMG_W 96
#define CFS_IMG_H 96
#define CFS_IMG_SIZE (CFS_IMG_W * CFS_IMG_H)

// Initialise the camera, trying each candidate pin map until the sensor probes.
// On success records the pin map name and sensor model (see accessors below).
esp_err_t cfs_camera_init(void);

// Grab one frame. Returns pointer to CFS_IMG_SIZE bytes of 8-bit luma (owned by
// the driver until cfs_camera_return()). NULL on failure.
const uint8_t *cfs_camera_capture(void);
void cfs_camera_return(void);

const char *cfs_camera_pinmap_name(void);   // e.g. "GOOUUU_ESP32S3_CAM"
const char *cfs_camera_sensor_name(void);   // e.g. "OV2640" / "OV3660"

#ifdef __cplusplus
}
#endif
