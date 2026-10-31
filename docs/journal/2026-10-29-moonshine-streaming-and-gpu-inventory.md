# Moonshine Tiny Streaming and UNO Q GPU inventory

**Date:** 2026-10-29, America/Los_Angeles

**Status:** CPU screening completed. GPU inventory verified. A subsequent
[Whisper Vulkan experiment](2026-10-29-whisper-vulkan-gpu-benchmark.md) was built
and tested, but obtained no completed GPU transcript. Live Moonshine microphone
trials were not run.

The user requested Moonshine after the Whisper CPU baseline missed a final
transcript within one second of speaking. During that work, they asked whether
the Q's MPU or GPU could accelerate inference. This entry records both results.

## Isolated Moonshine screening

The [project](../../projects/moonshine-tiny-benchmark/README.md) runs separately
at `/home/arduino/torque/projects/moonshine-tiny-benchmark/`. A private environment
uses the published `moonshine-voice==0.1.5` Linux aarch64 CPU wheel. The
[dependency lock](../../projects/moonshine-tiny-benchmark/requirements.lock)
contains fifteen exact wheel versions/hashes. No extra training packages,
system packages, Torque runtime update, service restart or MCU changes were used.

The native catalog selected `ModelArch.TINY_STREAMING` (2) explicitly, not the
older Tiny or the larger English default. The model URL is the dated
`tiny-streaming-en/quantized_26_08_21` bundle. The native download manifest checked
publisher sizes/CRC32C; [the model lock](../../projects/moonshine-tiny-benchmark/model-lock.json)
also records SHA-256 and size for every staged asset. The downloaded model group
is about 45 MB; the helper also cached about 1.7 MB of spelling assets, bringing
staged files to about 47 MB. Spelling mode was not enabled in these tests. Timed
runs use local files with the CPU provider selected explicitly.

The experiment reuses the same six hashed, complete LibriSpeech test-clean clips
and normalization as [Whisper](2026-10-29-whisper-tiny-on-device-benchmark.md).
Each configuration had an excluded warm-up, then one measured paced replay per
clip. These are screening measurements, not three-repetition estimates or p95
latency claims. One warm pass was sufficient to identify that all six clips
missed the one-second threshold in every tested configuration.

Twenty-millisecond chunks arrive at their scheduled audio-clock time, followed
by three seconds of paced silence. Natural completed-line callbacks are recorded
before `stop()`. Stop-forced finals are labelled and excluded; a near-duration-
limit completion or native error also invalidates a finalization success claim.
Multiple lines are joined for whole-utterance scoring. Input lag is measured;
audio is not dropped to conceal that lag. Early text-change callbacks may also
accompany completed clauses, so they do not establish an early stable transcript.

| Update interval / VAD averaging window | Incomplete-line decoding | Median file-end-to-final | Range | Under 1 s | WER |
| --- | --- | --- | --- | --- | --- |
| 0.5 s / 0.5 s | Enabled | 2.464 s | 1.878–3.076 s | 0/6 | 1.5% |
| 0.1 s / 0.15 s | Enabled | 2.250 s | 1.465–5.137 s | 0/6 | 2.2% |
| 0.1 s / 0.15 s | Disabled | **1.458 s** | **1.129–1.908 s** | **0/6** | 2.2% |

Peak worker RSS was about 231–262 MiB across configurations. Busy inference used
multiple CPU cores; the first measured default clip used about 3.4 CPU seconds
per busy wall second. The stock API exposes no documented thread-count option,
so no guessed setting was supplied. Some blocking add-audio calls took over a
second and caused input backlog, especially with incomplete-line decoding.

File end is a proxy: the clips have no independent human speech-end annotations.
These measurements do not prove live human end-to-final latency. Even this proxy
exceeds one second for all eighteen measured trials. The final-only CPU setup
improves substantially on Whisper's roughly 5.9-second paced-replay median, but
does not meet the user's requirement. No production speech API was added.

All phases are retained in one result bundle, `20261030T035510`, with phase
manifests and small harness snapshots. See the
[generated report](../../projects/moonshine-tiny-benchmark/report.md).
No microphone was opened for Moonshine: the earlier physical-input issue remains
unresolved, and this CPU screening already misses the requested latency.

## MPU and GPU are different paths

Both recognizers already run on the UNO Q's Linux MPU: the QRB2210's four
Cortex-A53 CPU cores. The STM32 MCU continues to handle the resident matrix/RGB
firmware. Changing MCU firmware would not accelerate these Linux ASR programs.

The user's normal `arduino` account can enumerate the actual Adreno 702 GPU:

- `vulkaninfo --summary` lists **Turnip Adreno (TM) 702** as an integrated GPU,
  using Mesa 25.2.6 / `libvulkan_freedreno.so`.
- Restricting `VK_DRIVER_FILES` to the Freedreno ICD still lists that GPU. This
  distinguishes it from the separately listed **llvmpipe CPU** implementation.
- The Vulkan loader reports instance API 1.4.309; the Adreno physical device
  reports API 1.0.318. These are different facts. Do not conclude compatibility
  or incompatibility from the loader version alone.
- The device reports a compute-capable queue, 16-bit storage, `shaderFloat16`
  and `shaderInt8`. These are feature reports, not a successful ASR GPU run.
- `clinfo` lists Rusticl device **FD702**, device type GPU, OpenCL 3.0 and
  `cl_khr_fp16`. It reports one compute unit and a maximum clock of 844 MHz.
  A GPU being present does not establish that it will beat the CPU workload.

The installed ASR wheels have been explicitly configured for CPU. Moonshine's
ONNX Runtime provider interface is not a ready-made Vulkan/Adreno switch for this
Linux wheel. CUDA is not a backend for this Adreno GPU, and Android NNAPI is not
the Debian execution path. A compatible alternate provider/build or backend port
would need its own validation.

`whisper.cpp` has a documented Vulkan backend, making a separate GPU-enabled
Linux ARM64 build a concrete candidate. Its Vulkan-loader check requires 1.2;
the installed loader passes that check. Physical-device feature compatibility
and actual model operations still need an execution test. The published Vulkan
container image is listed for amd64, so it must not be assumed to be an ARM64
GPU solution for UNO Q.

The current GGML OpenCL source also requires careful review with this stack:
its device-family matcher recognizes strings containing `Adreno`/`Qualcomm` or
`Intel`, while Rusticl names this GPU `FD702`. Its OpenCL C/subgroup requirements
also differ from merely reporting OpenCL device version 3.0. Enumeration alone
therefore does not justify selecting that backend or promising acceleration.

## Next GPU experiment

This plan was subsequently executed; see the
[GPU results and compatibility failures](2026-10-29-whisper-vulkan-gpu-benchmark.md).
The following describes the original experiment plan.

Prepare an isolated GPU-enabled ARM64 build, first check that it accepts the
actual Adreno, then run one known clip with matching output checks. Force the
Adreno ICD/device so a software renderer cannot silently become the claimed
GPU. Record which operations actually offload. Separate first-run shader/model
initialization from warm latency, and compare the same hashed Tiny English
weights/clips against the retained CPU baseline. Measure the full transcript
delay and accuracy, including any CPU fallback, rather than GPU kernel timing.
Do not install drivers, change OS packages or edit the active Torque release
as an incidental setup step. A faster result, including sub-one-second latency,
remains unproven until that experiment runs.

## Verification and cleanup

The final repository suite passed 337 tests on the Mac (two optional skips) and
UNO Q (four optional/compiler skips). Event tests distinguish partial text,
natural finalization, stop-forced text, a pending later line, duration-limit
completion and native errors. An earlier host run hit a `PermissionError` in the
existing oversized-shell-output process-cleanup test; its 24-test module and
subsequent complete suites passed on recheck. No daemon code was changed for
this experiment.

Final readback confirmed the same runtime release and daemon epoch, firmware
boot `1295313560`, session/model/permission settings and Arduino boot default.
All experiment workers were reaped, the program lease was free and Heart Pulse
remained unowned with six distinct matching framebuffer samples. The project
occupied 164,117,523 bytes of regular files (about 157 MiB); no live microphone
stream was opened. No service restart or firmware upload occurred. These are
software checks, separately from any person's observation of the LEDs.

Raw results and source snapshots are in the board's single result bundle and
copied locally beside the harness. GPU feature reports and the final cleanup
receipt are under the project's ignored `scratch/` directory. The source and
small manifests/report are reviewable; private environments, downloaded assets
and raw result bundles are ignored by Git. The root README remains unchanged.

Sources: [Whisper Vulkan build](https://github.com/ggml-org/whisper.cpp#vulkan-gpu-support),
[GGML Vulkan source](https://github.com/ggml-org/whisper.cpp/blob/master/ggml/src/ggml-vulkan/ggml-vulkan.cpp),
[GGML OpenCL source](https://github.com/ggml-org/whisper.cpp/blob/master/ggml/src/ggml-opencl/ggml-opencl.cpp),
[Moonshine provider/options interface](https://moonshine-voice.readthedocs.io/en/latest/api/options/),
[ONNX execution providers](https://onnxruntime.ai/docs/execution-providers/).
