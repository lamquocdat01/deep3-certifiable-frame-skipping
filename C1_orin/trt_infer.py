"""trt_infer.py — TensorRT 10.x inference wrapper for the C1b measurement.
Loads a serialized .engine (built by trtexec), runs the SAME preprocessing as
detector_t1.DetectorT1 (letterbox 114 + BGR->RGB + /255 CHW float32), and decodes
the end2end (1,300,6) output with detector_t1.decode_yolo. Same infer() interface:
returns {"conf_top", "n_person", "det_ms"}. Device memory via cuda-python (cudart)."""
import time, sys
import numpy as np
import tensorrt as trt
from cuda import cudart
sys.path.insert(0, "/home/dat/topic30/code")
from detector_t1 import decode_yolo, _letterbox

def _chk(err, msg=""):
    if isinstance(err, tuple):
        err = err[0]
    if int(err) != 0:
        raise RuntimeError("CUDA error %s %s" % (int(err), msg))

class TRTDetector:
    def __init__(self, engine_path, conf=0.25, imgsz=640):
        self.conf = conf; self.imgsz = imgsz
        self.providers = ["TensorRT(engine)"]
        logger = trt.Logger(trt.Logger.ERROR)
        runtime = trt.Runtime(logger)
        with open(engine_path, "rb") as f:
            self.engine = runtime.deserialize_cuda_engine(f.read())
        if self.engine is None:
            raise RuntimeError("failed to deserialize engine %s" % engine_path)
        self.ctx = self.engine.create_execution_context()
        err, self.stream = cudart.cudaStreamCreate(); _chk(err, "streamCreate")
        self.inp = None; self.outs = []
        self.dev = {}; self.host = {}
        for i in range(self.engine.num_io_tensors):
            name = self.engine.get_tensor_name(i)
            dtype = trt.nptype(self.engine.get_tensor_dtype(name))
            shape = tuple(self.engine.get_tensor_shape(name))
            nbytes = int(np.prod(shape)) * np.dtype(dtype).itemsize
            err, dptr = cudart.cudaMalloc(nbytes); _chk(err, "malloc "+name)
            self.dev[name] = (dptr, nbytes)
            self.host[name] = np.zeros(shape, dtype=dtype)
            self.ctx.set_tensor_address(name, int(dptr))
            if self.engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT:
                self.inp = (name, shape, dtype)
            else:
                self.outs.append((name, shape, dtype))
        # warmup
        dummy = np.zeros(self.inp[1], dtype=self.inp[2])
        for _ in range(10):
            self._run(dummy)

    def _run(self, x):
        name, shape, dtype = self.inp
        x = np.ascontiguousarray(x, dtype=dtype)
        dptr, nbytes = self.dev[name]
        _chk(cudart.cudaMemcpyAsync(dptr, x.ctypes.data, nbytes,
             cudart.cudaMemcpyKind.cudaMemcpyHostToDevice, self.stream), "h2d")
        ok = self.ctx.execute_async_v3(self.stream)
        if not ok:
            raise RuntimeError("execute_async_v3 returned False")
        for oname, oshape, odtype in self.outs:
            odptr, onb = self.dev[oname]
            _chk(cudart.cudaMemcpyAsync(self.host[oname].ctypes.data, odptr, onb,
                 cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost, self.stream), "d2h")
        _chk(cudart.cudaStreamSynchronize(self.stream), "sync")
        return self.host[self.outs[0][0]]

    def infer(self, frame):
        t0 = time.time()
        img, _ = _letterbox(frame, self.imgsz)
        x = np.ascontiguousarray(img[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0)
        out = self._run(x)
        conf_top, n = decode_yolo(out[None] if out.ndim == 2 else out, self.conf)
        return {"conf_top": conf_top, "n_person": n, "det_ms": round((time.time()-t0)*1000, 1)}


if __name__ == "__main__":
    import glob, statistics, cv2
    eng = sys.argv[1]; imgsz = int(sys.argv[2]) if len(sys.argv) > 2 else 640
    d = TRTDetector(eng, imgsz=imgsz)
    print("engine io: in=", d.inp, "out=", [o[:2] for o in d.outs])
    frames = sorted(glob.glob("/home/dat/topic30/data/highway/input/*.jpg"))[:60]
    imgs = [cv2.imread(f) for f in frames]
    for im in imgs[:10]: d.infer(im)
    ms = [d.infer(im)["det_ms"] for im in imgs]
    print("det_ms mean=%.2f median=%.2f min=%.2f max=%.2f -> back2back fps~%.1f" % (
        statistics.mean(ms), statistics.median(ms), min(ms), max(ms), 1000.0/statistics.mean(ms)))
    print("last:", d.infer(imgs[-1]))
