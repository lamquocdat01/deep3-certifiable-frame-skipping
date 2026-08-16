# Collect the vendored TFLM person-detection model (see model/README_MODEL.md).
# The model .cc is copied from the esp-tflite-micro example by fetch_model.ps1;
# it is NOT committed here because it is a ~1.9 MB generated array.
# Anchor the glob to CMAKE_CURRENT_LIST_DIR: during ESP-IDF's requirements-
# expansion pass the relative base dir is not main/, so a bare "model/*.cc"
# glob silently matches nothing.
file(GLOB CFS_MODEL_SRCS
     "${CMAKE_CURRENT_LIST_DIR}/model/*.cc"
     "${CMAKE_CURRENT_LIST_DIR}/model/*.cpp")

if(NOT CFS_MODEL_SRCS)
    message(FATAL_ERROR
        "No model source found in main/model/.\n"
        "Run  powershell -File main/model/fetch_model.ps1  after the first "
        "`idf.py reconfigure` to copy person_detect_model_data.cc from "
        "managed_components/espressif__esp-tflite-micro/. See model/README_MODEL.md.")
endif()

idf_component_register(
    SRCS
        "app_main.cc"
        "app_camera.cc"
        "controller.cc"
        "serial_cmd.cc"
        "ina219.cc"
        "meas.cc"
        ${CFS_MODEL_SRCS}
    INCLUDE_DIRS "." "model"
    REQUIRES esp32-camera esp-tflite-micro driver esp_timer esp_psram nvs_flash)
