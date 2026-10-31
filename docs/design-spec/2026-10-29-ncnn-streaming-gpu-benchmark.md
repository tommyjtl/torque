# Isolated ncnn GPU and streaming speech experiment

**Status:** Completed. Direct GPU arithmetic and full GPU-enabled recognition
worked. CPU Zipformer finalized all 18 paced trials within one second of file
end (median 0.387 s); the tested GPU hybrid path was slower (median 6.457 s).
Live microphone/whole-turn acceptance remains open. See the
[results](../journal/2026-10-30-ncnn-streaming-speech-benchmark.md).

The user requested execution of the proposed ncnn compatibility test followed
by an English streaming Zipformer comparison. Use a separate
`projects/ncnn-speech-benchmark/` on the UNO Q's Linux MPU and actual Adreno 702.
Keep Moonshine and the controller intact. Do not restore removed Whisper
projects, install OS packages/drivers, start an Arduino app, flash firmware,
restart services or change boot defaults.

Pin sherpa-ncnn and its declared ncnn dependency, record source/package/model
hashes and build flags, and review upstream instructions before building. Since
no compiler is installed, download/extract build packages privately under this
project. Keep a 2 GiB project budget, check root and home independently and use
one compiler job for the ncnn kernel build. The smaller speech-library build may
use two after checking memory headroom; record the actual job count. Preserve
source locks, logs, measurements and small receipts.

Gate speech-model staging on explicit Vulkan computations passing known CPU
references. Force the Freedreno ICD, select hardware Adreno and exclude software
renderers. Use Vulkan tensors/command submission with CPU readback for arithmetic
and a matrix/convolution operation; a GPU-enumeration message or a model's GPU
flag alone is insufficient. Record failures honestly and stop the dependent GPU
phase if this gate fails. Do not count silent CPU fallback as acceleration.

If the gate passes, stage one small English streaming Zipformer model and reuse
the six hashed Moonshine LibriSpeech fixtures. Compare the same executable/model
with CPU and GPU selected, four CPU threads, identical decoding/endpoint settings,
one excluded warm-up and three warm repetitions per clip when execution passes.
Separate model loading, processing throughput and paced file-end-to-final delay.
Verify real GPU operators, CPU fallbacks and transcript correctness/WER, record
input lag, CPU/RSS and Torque status response. File end is a proxy without human
speech-end annotations; forced flush is not a natural endpoint. Do not claim a
production p95 or sub-one-second live latency from six clips.

Run all native children through Torque program/release leases with finite
deadlines and core dumps disabled. Refuse busy state rather than cancelling
other work. Reap only experiment children. No microphone is required for the
initial comparison. Any later physical capture must have an announced ready cue
and be kept distinct from fixed-clip evidence.

Afterward verify runtime/daemon epoch, MCU boot, service unit, boot default,
settings and Moonshine input hashes are unchanged, leases are released and the
user's display intent is preserved. Export results to the Mac. Remove only
verified unused download caches; preserve relevant receipts and source.
