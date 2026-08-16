# fetch_model.ps1 — copy the TFLM person-detection model array from the
# esp-tflite-micro managed component into main/model/.
# Run from the cfs-mcu project root after `idf.py reconfigure`.
$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path      # main/model
$projRoot  = Split-Path -Parent (Split-Path -Parent $scriptDir)    # cfs-mcu
$mc        = Join-Path $projRoot 'managed_components'

if (-not (Test-Path $mc)) {
    Write-Error "managed_components/ not found. Run 'idf.py reconfigure' first (it downloads esp-tflite-micro)."
}

$candidates = Get-ChildItem -Path $mc -Recurse -Filter 'person_detect_model_data.cc' -ErrorAction SilentlyContinue
if (-not $candidates) {
    # Some component versions name it differently or ship a .cpp
    $candidates = Get-ChildItem -Path $mc -Recurse -Include 'person_detect_model_data.c*','*person_detect*model*data*.c*' -ErrorAction SilentlyContinue
}
if (-not $candidates) {
    Write-Error "Could not find person_detect_model_data.cc under $mc. See README_MODEL.md to copy it manually."
}

$src = $candidates[0].FullName
$dst = Join-Path $scriptDir 'person_detect_model_data.cc'
Copy-Item -Path $src -Destination $dst -Force
Write-Host "Copied model:"
Write-Host "  from: $src"
Write-Host "  to  : $dst"
$size = (Get-Item $dst).Length
Write-Host ("  size: {0:N0} bytes" -f $size)

# The .cc includes person_detect_model_data.h — copy it too.
$srcH = Join-Path (Split-Path -Parent $src) 'person_detect_model_data.h'
if (Test-Path $srcH) {
    Copy-Item -Path $srcH -Destination (Join-Path $scriptDir 'person_detect_model_data.h') -Force
    Write-Host "Copied header: person_detect_model_data.h"
} else {
    Write-Warning "person_detect_model_data.h not found next to the .cc; check the include in the .cc."
}
