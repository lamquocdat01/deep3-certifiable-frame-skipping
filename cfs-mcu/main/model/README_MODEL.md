# TFLM person-detection model

The firmware links against the MLPerf-Tiny **person_detection** model
(MobileNetV1, 96×96, int8), provided by the `espressif/esp-tflite-micro`
managed component. The generated array (`person_detect_model_data.cc`, ~300 KB)
is **not** committed here — it is copied from the component after the first
`idf.py reconfigure`, which downloads the component into `managed_components/`.

## How to obtain it

From the `cfs-mcu/` project root, after ESP-IDF is exported:

```powershell
idf.py set-target esp32s3      # first time; triggers component download
idf.py reconfigure             # ensures managed_components/ is populated
powershell -ExecutionPolicy Bypass -File main/model/fetch_model.ps1
idf.py build
```

`fetch_model.ps1` locates `person_detect_model_data.cc` inside
`managed_components/espressif__esp-tflite-micro/` and copies it here. The build
globs `model/*.cc`, so once the file is present the link resolves the two
symbols used by `app_main.cc`:

- `g_person_detect_model_data[]`
- `g_person_detect_model_data_len`

If the component layout changes and the script cannot find the file, copy it
manually from the component's `examples/person_detection/main/` (older layout)
or `models/` directory into `main/model/`.
