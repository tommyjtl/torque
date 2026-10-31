# ncnn GPU execution and fast CPU streaming speech

**Date:** 2026-10-30, America/Los_Angeles

**Status:** Completed and verified. Hardware GPU calculations and full
GPU-enabled recognition worked. The conservative GPU path was slower than CPU.
The CPU configuration met the fixed-clip file-end threshold in all 18 trials;
live microphone/whole-turn acceptance is still open.

The user authorized the [isolated experiment](../design-spec/2026-10-29-ncnn-streaming-gpu-benchmark.md)
after the [runtime-alternatives investigation](2026-10-29-gpu-speech-runtime-alternatives.md).
The new [project](../../projects/ncnn-speech-benchmark/README.md) is separate from
Moonshine. The removed Whisper directories were not restored. No MCU firmware,
Arduino application, service configuration, boot default or OS driver was changed.

## Reproducible source and build

sherpa-ncnn is pinned to `c61e50d61e9fbed5972afa4d95bc560e168affe2` (2.1.15).
Its declared ncnn dependency is pinned to
`c4193aadbbb56582aa87b1850dd3d98fb8fd936d`. Source archives, dependency recipes,
private Debian package hashes and actual compiler flags are retained. GCC 14.2,
CMake and glslang were extracted into this project's `tools/`; no package
installation or maintainer script ran. An additional private `glslang-tools`
package resolved a missing imported shader-tool executable during configuration.

The ncnn kernels compiled with one job. After measured compiler memory stayed
around 500 MiB with ample free RAM, only this experiment's Ninja build was
interrupted and resumed with two jobs for the smaller speech libraries. Existing
objects were retained. Cortex-A53 flags disable unsupported ARMv8.2/SVE kernels.

A small private `runtime-profile.patch` makes timestamp/query/log instrumentation
opt-in through `TORQUE_NCNN_PROFILE`. It changes diagnostic statements, not tensor
operations. Profiled calibration is kept separate from unprofiled main timings.
The patch and before/after source hashes are in the source lock.

## GPU calculation gate

The Freedreno ICD was forced and llvmpipe excluded. The actual integrated
Turnip Adreno 702 reports 16,384 bytes of shared memory per workgroup.

`20261030T073357-probe` completed vector addition correctly, then refused the
generic MatMul layer because this pinned ncnn revision has no Vulkan
implementation of it. That is an unsupported operator, not a driver crash.

`20261030T073746-probe` used the supported InnerProduct layer to perform three
batched matrix multiplications (K=16/32/64), in addition to vector addition.
Explicit Vulkan tensors, GPU weight upload and queue submission were followed
by CPU readback and comparison against independent arithmetic references.
All four tests had **zero measured error**. CPU fallback cannot silently satisfy
these direct Vulkan calls. An initial non-dumpable process setting blocked
ncnn's `/proc/self/auxv` CPU-feature read; it was removed while retaining the
zero core-file limit, parent-death signal and finite native alarm.

## Model and GPU recognition proof

Only after the gate passed, seven assets of the small English streaming
Zipformer model were staged: 41,329,751 bytes, publisher-declared Apache-2.0,
Hugging Face revision `20af696d92a32438db47fb7d4bd961b36fb07021` of
`marcoyang/sherpa-ncnn-streaming-zipformer-20M-2023-02-17`.
LFS SHA-256 or Git blob identity was checked against the pinned revision;
SHA-256 and sizes for every staged file are retained. Encoder metadata version
1 was checked for compatibility. The six existing Moonshine fixtures were
copied and verified, preserving 46.240 seconds and 136 reference words.

The CPU calibration `20261030T075942-cpu-bulk` recognized the first eight-word
clip exactly. Its measured bulk processing of the clip plus three seconds of
silence took 1.734 seconds; this is not a post-speech latency measurement.

GPU calibration `20261030T080032-gpu-bulk-profile` produced the same exact text.
Vulkan timestamp logs contained 52,194 positive GPU timing rows and 6,476 CPU
profile rows across the excluded warm-up and one measured trial. These are
operation instances, not unique layers or a compute-offload percentage. The
model therefore executes a **GPU/CPU hybrid** path. It is actual accelerated
recognition, rather than merely an initialized GPU or a model option.

With diagnostics disabled, `20261030T080312-gpu-bulk` again recognized the clip
exactly, taking 12.375 seconds of bulk processing. Profiling was not the sole
cause of its slower processing. A lost SSH client returned 255, but the board's
native completion and passed result were intact; that is not recorded as a
model failure. Finite paced sweeps subsequently run in a separate process
session, with durable logs and inherited Torque leases, so connection drops
cannot invalidate them. No duplicate jobs are launched.

## Completed CPU paced sweep

`20261030T080913-cpu` used four threads, greedy decoding, FP32 compute, no
subgroup/cooperative-matrix path and a 0.3-second silence rule after nonempty
speech. Audio was fed in ordered 20 ms blocks, with three seconds of trailing
silence. One first-clip warm-up was excluded; six clips were measured three times.

All **18/18** natural-final file-end delays were under one second: median
**0.387 seconds**, range approximately **0.165–0.522 seconds**. First-pass WER
was **4/136 = 2.9%**, with four word-exact clips. Peak process RSS was
**101.9 MiB**. Two errors were on the short "they outstrip" phrase; the longer
clip had a name spelling and British/American spelling difference. The same
normalization/scoring policy is retained; no errors were edited away.

This clears the fixed-clip proxy threshold. It does not establish live human
speech-end latency: there are no independent speech-end annotations or physical
microphone/capture-cleanup measurements. InputFinished was not called to force
a final, and no later pending text was allowed for an accepted endpoint.
Endpoint settings and model architecture differ from Moonshine; comparisons
describe complete tested pipelines, not an isolated GPU or engine speedup.

## Completed GPU comparison and practical interpretation

The unprofiled GPU paced run `20261030T081418-gpu` completed all 18 natural
finals. Median file-end-to-final delay was **6.457 s**, range **4.008–13.935 s**,
with **0/18** below one second. First-pass WER was also 4/136; normalized
transcripts matched the CPU on **all 18 paired trials**. Peak process RSS was
117.1 MiB. Largest processing call/input lag were 0.921/15.870 s, versus
0.152/0.132 s for CPU. CPU time across the 18 trials was 296.96 CPU-s for GPU
mode and 197.70 CPU-s for CPU mode; CPU-s sums time across threads.

Native model initialization was 0.389 s (CPU) and 3.264 s (GPU), with ordinary
filesystem/shader caches. These are not forced-cold startup measurements or
complete process startup times. Status IPC medians/observed maxima were
2.27/9.89 ms (399 samples) and 2.18/5.62 ms (774 samples), respectively.

Thus ncnn provides a working GPU speech path on this board, while the tested
CPU streaming configuration is the practical latency candidate. The comparison
uses conservative FP32 settings, disabled subgroup/cooperative-matrix paths and
the recipe's pinned ncnn revision. It is not a ceiling for newer runtimes, FP16
tuning or every possible GPU configuration. GPU operator counts are not compute
fractions; CPU fallback, transfers and many small GPU submissions remain in this
hybrid path. No claim of a specific isolated bottleneck is made from timing alone.

The fast endpoint is also an important qualification: the two longest clips
produced five and three completed segments. The benchmark retained every segment
and measured the last final after the entire known clip, with no pending text.
An earlier segment completion is not proof that a person has finished their
whole turn. A first live prototype should use push-to-talk or a separate
end-of-turn policy before sending commands to the agent. No recognized text was
executed as a board command in these experiments.

## Final verification and retention

The final suites ran **348 tests** on the Mac (two skips) and UNO Q (four skips),
with no failures. Runtime release/epoch/PID, firmware boot `1295313560`, session,
model/permissions, settings, service configuration and Arduino boot default were
unchanged. The OS package database hash was unchanged. Workers were reaped, the
program lease was free and sixteen Moonshine model/fixture hashes matched.
Six distinct readback frames matched Heart Pulse over multiple cycles; an
initial shorter sampling window was insufficient to cover the pulse. These are
software framebuffer checks, not a person's optical observation.

Only unused, hash-verified downloaded `.deb` files were pruned after process and
container-reference checks, reclaiming **109,842,044 bytes**. Sources, private
tools, model, executables, locks, receipts and all results remain. The project
occupied **698,101,628 bytes** afterward, within its 2 GiB budget; root/home had
1,595,842,560 / 14,292,955,136 bytes available. No service restart, firmware
upload, driver change or microphone opening occurred.

The raw result/source/log export was verified on the Mac before cache cleanup:
`scratch/board-results-20261030.tar.gz`, 603,538 bytes, SHA-256
`6e1aac0f5d96e5a4c78c4ebe86388cd2ecdd091af739e1c6fad5a513852d1f77`.
The cleanup receipt is mirrored separately. See the
[generated report](../../projects/ncnn-speech-benchmark/report.md).

Sources: [streaming model documentation](https://k2-fsa.github.io/sherpa/ncnn/pretrained_models/zipformer-transucer-models.html),
[sherpa-ncnn](https://github.com/k2-fsa/sherpa-ncnn),
[ncnn](https://github.com/Tencent/ncnn),
[model publisher](https://huggingface.co/marcoyang/sherpa-ncnn-streaming-zipformer-20M-2023-02-17).

## Adopted direction and GPU retirement

The user chose CPU Zipformer for the next steps and requested cleanup of the GPU
experiment. The tested GPU path is closed for its **performance failure** against
the one-second requirement, not a correctness failure: it executed GPU kernels,
completed recognition and matched CPU transcripts, but took 6.457 s median after
file end versus CPU 0.387 s.

The [CPU next-step design](../design-spec/2026-10-30-cpu-zipformer-next-steps.md)
keeps the tested executable/model and makes the next prototype CPU-only at its
entrypoint. The next acceptance is controlled live microphone capture with
push-to-talk or separate whole-turn handling. A new GPU experiment requires an
explicit request. Archived source/results stay on the Mac and in the Notion
report; cleanup must preserve the CPU baseline before deleting GPU build data.

**On-board retirement status:** Completed after reconnection and the requested
live voice trials. The old `/home/arduino/torque/projects/ncnn-speech-benchmark`
directory (698,206,058 regular-file bytes) was removed. The small CPU project at
`/home/arduino/torque/projects/zipformer-cpu` retains the exact matched CPU
executable, pinned model/fixtures, CPU baseline, live worker, both decoder choices
and live trial metadata, totaling 69,864,023 bytes at acceptance. Optional GPU
backend code remains embedded in the matched executable but the CPU entrypoint
always selects CPU; system graphics drivers were not removed.

A fresh GPU/source/result archive was verified on the Mac, SHA-256
`f3d603f606470ef49c78e5b33de7d49161088b58b10faa712c3c2939148e8226`.
The separate live-source/runtime/metric archive is SHA-256
`13994a568963665026bda078a95ed95b30b35aef895e7d007eeab138fbef1f11`.
All 94 old result files matched the archive receipt before deletion. Every
existing CPU live file was copied and checked before its temporary duplicate
was removed. Only reproducible Python bytecode was excluded from that equality
check. Process, descriptor, mapped-file, container and lease checks passed.

The preserved CPU known-file smoke run `20261031T043102-cpu` passed before
removal. The live worker's 16/48 kHz recorded-clip tests passed again after
removal (`20261031T043508-selftest`). Runtime, settings, display intent, firmware
boot `1395641681` and boot default were unchanged during retirement. Removal of
the old workspace and temporary duplicate recovered 764,661,760 allocated
bytes; home had 14,973,599,744 bytes available afterward. These removal figures
are distinct from the earlier package-download cleanup.

See the [live experiment](2026-10-30-cpu-zipformer-live-input.md): responsive
streaming was observed, but connected-speech accuracy failed the initial phrase
checks. CPU remains the chosen development direction, not a production-ready
voice interface.
