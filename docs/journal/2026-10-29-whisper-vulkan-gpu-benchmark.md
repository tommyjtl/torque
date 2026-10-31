# Whisper Vulkan compatibility and matched CPU control

**Date:** 2026-10-29, America/Los_Angeles. Result directory names use UTC and
therefore begin `20261030` for these evening trials.

**Status:** Completed. No valid GPU transcription timing or GPU speedup was
obtained. The matched CPU control passed; the sub-one-second final-transcript
requirement remains unmet. No live microphone capture was used in this phase.

The authorized [experiment](../design-spec/2026-10-29-whisper-vulkan-gpu-benchmark.md)
is isolated in [its project](../../projects/whisper-gpu-benchmark/README.md).
Both recognizers already use the Linux MPU's Cortex-A53 CPU cores; this tests
whether the separate Adreno GPU can accelerate Whisper, without MCU changes.

## Build and GPU identity

The ARM64 build pins Whisper revision
`f24588a272ae8e23280d9c220536437164e6ed28`, matching the Python binding's upstream
revision. GCC 14.2, CMake 3.31.6 and shaderc 2025.2 were extracted privately from
115 exact Debian packages (104,936,260 downloaded bytes). Package versions and
SHA-256 hashes, source archive hash and build flags are retained. No apt
installation, package-index update, maintainer script or driver change occurred.
The executable uses the board's installed Vulkan loader/driver at runtime.

Parallel compilation exceeded available build memory. A generated C++ unit
contained about 140 MB of SPIR-V byte literals. The private compiler wrapper
embeds those same compiled shader files using `.incbin`, checking each array's
size and SHA-256 against its original bytes. A native linked test verified byte
identity and the pointer table. Compilation used one job. This changes binary
packaging, not shader math. Original generated sources and embedding receipts
are retained; this is a private experimental build, not an upstream patch.

Forcing the Freedreno ICD excluded llvmpipe. The backend enumerated the actual
Turnip Adreno 702, Mesa 25.2.6, with 16 KiB shared memory per workgroup, FP16,
32-lane warps, no integer dot product and no matrix cores. GPU enumeration and
buffer allocation are recorded separately from completed inference.

## GPU failures

| Result directory | Configuration | Outcome |
| --- | --- | --- |
| `20261030T051525-probe` | Stock device probe | Actual Adreno enumerated; no inference |
| `20261030T051657-gpu-profile` | Stock backend, FP16, profiling | Shared-memory initialization refused |
| `20261030T053840-gpu-profile` | Private compatibility patch, FP16, profiling | `ErrorDeviceLost` during inference |
| `20261030T054831-gpu` | Same patch, FP16, no profiling | Same device loss |
| `20261030T055100-gpu` | Same patch, FP32 compute, fusion disabled | Same device loss |

The stock initialization checks quantized types even when the loaded model does
not use them. Its smallest IQ1 tile needs 16,512 bytes, exceeding the real 16,384
byte limit by 128 bytes; the conservative F16 check needs 4,224 bytes. The private
`vulkan-low-memory.patch` retains the limit, disables unsupported dtype kernels
and adds scheduling fallback for those unsupported types. It does not raise a
reported hardware limit or alter model weights. FP32 compute still used the
original F16/F32 model weights.

The patched backend selected Vulkan0 and allocated 77.11 MB of model buffers.
It then aborted on queue submission with `vk::DeviceLostError`, before even the
warm-up produced a transcript. Disabling profiling and then F16/fusion did not
resolve it. No run established a completed profiled GPU operation or final
transcript; initialization near 0.56 seconds is not a transcription result.
Further GPU attempts were stopped. A specific shader/driver root cause has not
been isolated, and these results do not prove the GPU could never accelerate ASR.

## Matched CPU control and accuracy correction

`20261030T055333-cpu` used the same new executable, original Tiny English weights,
English greedy best-of-one decoding, no context or temperature fallback, four
threads and the same six hashed mono 16 kHz clips. One first-clip warm-up was
excluded; three full warm repetitions per clip yielded 18 measured transcripts.

Median full decode was **5.278 seconds**, range **5.003–6.046 seconds**, aggregate
RTF **0.702**, peak native-process RSS **165.3 MiB**. Model initialization took
0.242 seconds and the excluded warm-up 5.519 seconds. RTF below one describes
throughput relative to audio duration, not post-speech finalization under a
second. Six-clip WER was **2/136 = 1.5%**; this small test is not general accuracy.

Comparing transcripts exposed a bug in the earlier Python benchmark: its binding
strips each segment, but the harness joined segments without spaces. This
created false word errors. The worker now joins with spaces and a regression
test covers word boundaries. Original result files are preserved and their
accuracy is explicitly marked invalid; their timing measurements are unchanged.
A fresh excluded warm-up plus one accuracy pass per clip at both two/four
threads (`20261030T060930-accuracy-correction`) independently found 2/136 errors
for each setting. It is not presented as a three-repeat timing replacement or
as a GPU/decoder accuracy improvement. Earlier replay accuracy is invalidated;
its endpoint latency remains valid. No new live microphone acceptance is claimed.

## Verification, cleanup and storage

The full repository suite passed **344 tests** on the Mac (two skips) and UNO Q
(four skips). Tests cover device/evidence rejection, real nonzero profiling
requirements, generated-byte identity, compatibility-patch bounds and transcript
segment joining. Shell syntax checks passed. No installed Torque code changed.

Readback confirmed the same active release `0.2.0-9ed93a142a1d`, daemon epoch,
PID, session/model/permission settings, firmware boot `1295313560`, Arduino boot
default, service unit and settings hashes. The OS package database hash is also
unchanged. Experiment processes were reaped and the program lease was free.
Four distinct firmware framebuffer samples matched the expected Heart Pulse
frames, with no output owner. These are software readbacks, not optical proof.

After checking process descriptors and all container mount references, only the
115 hash-verified downloaded `.deb` caches were removed, reclaiming 104,936,260
bytes. Extracted tools, source archive, vendor source, compiled binaries, build
logs, receipts, model/fixture inputs and every result were preserved. The project
occupied 1,047,826,854 bytes afterward, below its 2 GiB budget. Available space
was 1,595,867,136 bytes on the root filesystem and 13,780,545,536 bytes on home.
Small acceptance receipts remain under ignored `scratch/`; results are mirrored
locally. No firmware upload, service restart or microphone opening occurred in
this phase. Existing sources and unrelated work remain intact.

The [generated GPU report](../../projects/whisper-gpu-benchmark/report.md) and
the complete speech-performance report distinguish successful CPU measurements,
failed GPU configurations and the unresolved physical microphone acceptance.

Sources: [pinned engine](https://github.com/ggml-org/whisper.cpp/tree/f24588a272ae8e23280d9c220536437164e6ed28),
[Vulkan backend](https://github.com/ggml-org/whisper.cpp#vulkan-gpu-support),
[LibriSpeech data and attribution](https://www.openslr.org/12/).

## Subsequent user-requested removal from the board

After reviewing the report, the user requested removal of the Whisper experiment
files from the UNO Q. Both `whisper-tiny-benchmark/` and `whisper-gpu-benchmark/`
were removed from `/home/arduino/torque/projects/`, including their private
environments, weights, toolchain and build artifacts. No GPU or Whisper trial
was run during cleanup. Runtime/program locks and process/mapped-file/container
checks confirmed the projects were unused before deletion.

Sources, reports, raw measurements, logs and receipts were first exported to a
verified 960,118-byte archive on the Mac, under the local GPU project's ignored
`scratch/uno-q-whisper-experiments-20261029.tar.gz`. Its SHA-256 is
`01bb1d7dcd297c525f4f5f59451398194e7cdcc8d8846e799e380ad4a9ed9048`.
Local project sources/results and the previously saved Notion report remain.
The board paths described above record the experiment's original location;
repeating it now requires restoring/staging the projects and dependencies.

Actual available home space increased by **1,263,398,912 bytes (1.18 GiB)** to
15,043,784,704 bytes (14.01 GiB). Sixteen Moonshine model/fixture files passed
their existing SHA-256 checks before and after removal. Torque release, daemon
epoch/PID, firmware boot, settings, session/model/permissions, service unit and
Arduino boot default were unchanged. The small removal receipt remains in
`~/.cache/torque/whisper-removal-20261029.json` and is mirrored locally.
