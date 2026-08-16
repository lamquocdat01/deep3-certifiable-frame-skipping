// camera_pins.h — candidate pin maps for ESP32-S3-CAM WROOM-1 style boards.
//
// The firmware tries candidate A first, then candidate B, and records which one
// initialised the sensor (see app_camera.cc / STATS "pinmap"). Both maps leave
// GPIO1/GPIO2 free for the INA219 I2C bus (C2b) — verified against the data
// pins below.
//
// Candidate A — GOOUUU ESP32-S3-CAM (primary; documented at
//   github.com/profharris/GOOUUU_ESP32-S3-CAM).
// Candidate B — Freenove ESP32-S3-WROOM CAM (fallback).
//
// NOTE: on many of these boards the two maps are identical; they are kept
// separate so autodetect still reports the source that worked, and so a board
// whose map differs only needs its numbers changed in one place.
#pragma once

typedef struct {
    const char *name;
    int pin_pwdn;
    int pin_reset;
    int pin_xclk;
    int pin_sccb_sda;   // SIOD
    int pin_sccb_scl;   // SIOC
    int pin_d7;         // Y9
    int pin_d6;         // Y8
    int pin_d5;         // Y7
    int pin_d4;         // Y6
    int pin_d3;         // Y5
    int pin_d2;         // Y4
    int pin_d1;         // Y3
    int pin_d0;         // Y2
    int pin_vsync;
    int pin_href;
    int pin_pclk;
} cfs_cam_pinmap_t;

// Candidate A: GOOUUU ESP32-S3-CAM
static const cfs_cam_pinmap_t CFS_CAM_GOOUUU = {
    .name = "GOOUUU_ESP32S3_CAM",
    .pin_pwdn = -1,  .pin_reset = -1,
    .pin_xclk = 15,
    .pin_sccb_sda = 4, .pin_sccb_scl = 5,
    .pin_d7 = 16, .pin_d6 = 17, .pin_d5 = 18, .pin_d4 = 12,
    .pin_d3 = 10, .pin_d2 = 8,  .pin_d1 = 9,  .pin_d0 = 11,
    .pin_vsync = 6, .pin_href = 7, .pin_pclk = 13,
};

// Candidate B: Freenove ESP32-S3-WROOM CAM
static const cfs_cam_pinmap_t CFS_CAM_FREENOVE = {
    .name = "Freenove_ESP32S3_WROOM_CAM",
    .pin_pwdn = -1,  .pin_reset = -1,
    .pin_xclk = 15,
    .pin_sccb_sda = 4, .pin_sccb_scl = 5,
    .pin_d7 = 16, .pin_d6 = 17, .pin_d5 = 18, .pin_d4 = 12,
    .pin_d3 = 10, .pin_d2 = 8,  .pin_d1 = 9,  .pin_d0 = 11,
    .pin_vsync = 6, .pin_href = 7, .pin_pclk = 13,
};

// Ordered list of candidates to try.
static const cfs_cam_pinmap_t *const CFS_CAM_CANDIDATES[] = {
    &CFS_CAM_GOOUUU,
    &CFS_CAM_FREENOVE,
};
static const int CFS_CAM_CANDIDATE_COUNT =
    sizeof(CFS_CAM_CANDIDATES) / sizeof(CFS_CAM_CANDIDATES[0]);
