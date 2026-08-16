#!/bin/bash
# Build fp16 TRT engines from the C1 ONNX files. Logs kept for provenance.
cd ~/topic30/models
TRT=/usr/src/tensorrt/bin/trtexec
mkdir -p ~/topic30/c1b_out/build_logs
LOG=~/topic30/c1b_out/build_logs
echo "START $(date)" > $LOG/build_master.log

build () {
  local onnx=$1 eng=$2 name=$3
  echo "=== building $name -> $eng ===" | tee -a $LOG/build_master.log
  $TRT --onnx=$onnx --saveEngine=$eng --fp16 \
       --memPoolSize=workspace:4096 --noDataTransfers --useCudaGraph \
       > $LOG/build_$name.log 2>&1
  rc=$?
  echo "$name rc=$rc" | tee -a $LOG/build_master.log
  if [ $rc -eq 0 ]; then
    ls -la $eng | tee -a $LOG/build_master.log
    grep -iE 'Precision:|fp16|Throughput|mean.*ms|GPU Compute Time' $LOG/build_$name.log | tail -8 | tee -a $LOG/build_master.log
  else
    echo "--- FAIL tail $name ---" | tee -a $LOG/build_master.log
    tail -25 $LOG/build_$name.log | tee -a $LOG/build_master.log
  fi
}

build yolov3u.onnx yolov3u_fp16.engine yolov3u
build yolo26s.onnx yolo26s_fp16.engine yolo26s
echo "ALL BUILD DONE $(date)" | tee -a $LOG/build_master.log
