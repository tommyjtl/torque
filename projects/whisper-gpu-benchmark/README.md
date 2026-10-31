# Whisper Vulkan experiment

Private Linux ARM64 build and finite CPU/GPU compatibility benchmark for UNO Q.
It reuses the original Tiny English model and six hashed English recordings in
the earlier Whisper project. It does not change Torque, MCU firmware, boot
selection, services or OS package installation.

`setup_tools.py` resolves configured Debian candidates, downloads packages and
extracts them into `tools/`. It never invokes installation or maintainer scripts.
`build.py` uses that private sysroot and one compiler job. Large generated shader
byte arrays are packaged with `.incbin` by `compile_cxx.py`/`embed_spirv.py`, with
their contents checked against the original compiled SPIR-V. Engine/shader math
is not changed by that packaging step.

The stock source pin is in `source-lock.json`. After its initialization failure,
`apply_compat.py` produced the recorded private `vulkan-low-memory.patch`. It
disables dtypes that exceed the real shared-memory limit and routes those
unsupported operations to CPU. This is an experimental compatibility patch,
not an upstream-supported UNO Q configuration. It does not make device-lost
inference a successful run.

```bash
torque run ~/torque/projects/whisper-gpu-benchmark/runner.py probe
torque run ~/torque/projects/whisper-gpu-benchmark/runner.py cpu --first-clip
torque run ~/torque/projects/whisper-gpu-benchmark/runner.py gpu --first-clip --profile
torque run ~/torque/projects/whisper-gpu-benchmark/runner.py cpu --repeats 3
```

The runner selects only the Freedreno Adreno ICD, rejects software-renderer
substitution and captures backend/kernel evidence. Profiling runs are diagnostic
and excluded from normal latency comparisons. Results, logs and source snapshots
remain under `results/`. No microphone or matrix guidance is used in this phase.
Native inference is supervised with deadlines; core dumps are disabled for the
experimental native process. `report.py` summarizes saved measurements without
starting a model or GPU job.

**Observed outcome:** the stock backend refused the 16 KiB shared-memory limit;
the private compatibility variant loaded model buffers, but all tested GPU
inference variants ended in `ErrorDeviceLost`. No accepted GPU transcript or
speedup has been demonstrated. Existing model/fixture inputs are preserved.
