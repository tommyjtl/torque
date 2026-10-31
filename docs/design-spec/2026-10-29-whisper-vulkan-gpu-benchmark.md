# Whisper Tiny English on the UNO Q Adreno GPU

**Date:** 2026-10-29, America/Los_Angeles

**Status:** Completed with a negative GPU result. The stock backend rejected
initialization; the private compatibility variant lost the device during
inference. No accepted GPU transcription or speedup was obtained. The matched
CPU control completed. See the [experiment journal](../journal/2026-10-29-whisper-vulkan-gpu-benchmark.md).

The user authorized the [GPU follow-up](../journal/2026-10-29-moonshine-streaming-and-gpu-inventory.md#next-gpu-experiment).
Test the actual Adreno 702, using the existing six hashed English clips and
original Tiny English weights. Pin Whisper engine revision
`f24588a272ae8e23280d9c220536437164e6ed28`, matching the earlier Python binding's
upstream revision. Compare CPU and Vulkan from the same new build as well as
the retained CPU measurements; compiler/backend differences must remain visible.

Use separate `projects/whisper-gpu-benchmark/` source, tools, build and result
directories on the home filesystem. The board has Vulkan/OpenCL drivers but no
native compiler, CMake or shader compiler in PATH. The Mac Docker daemon is
inactive and the board's existing image lacks build tools. Prefer unprivileged
download/extraction of the configured Debian ARM64 compiler/build packages into
the project. Record candidate versions, package hashes, source archive hash and
build flags. Do not invoke package installation, update package indexes, edit
the active release, change drivers, start/stop the Arduino app or change services.
Respect third-party licensing; this is a private local build, not an upstream PR.

Keep an explicit disk budget (2 GiB initial project budget; check home and root
separately), limit compilation parallelism, and retain build logs. Private tool
paths affect only the build process. Compiled executables run against the stock
Linux/Vulkan runtime. Reuse the existing read-only model input and small fixture
pack; do not redownload or modify baseline assets.

First enumerate backend devices and require an actual Vulkan Adreno GPU. Set
`VK_DRIVER_FILES` to the Freedreno ICD so llvmpipe cannot silently count as GPU
execution. Confirm backend selection and model buffers/operations in logs. GPU
enumeration alone is not an accepted accelerated result. Handle unsupported
features, device loss or failed correctness as compatibility failures, without
relabeling CPU fallback as GPU performance.

Load the model once, measure startup separately, exclude one warm-up, then time
the full transcription call with four CPU threads and unchanged English greedy
decoding settings. The only intended execution-mode difference is GPU use.
Record three warm repetitions per clip if compatibility/correctness pass, plus
CPU/memory, exact transcript/normalized WER, failures and backend logs. Compare
both matched-build CPU and Vulkan modes. Separate shader initialization/cache
effects from warm execution. Do not mistake encoder-only timings for final text.

Keep each inference and the experiment finite, supervise/reap only its own
processes, and preserve program/release leases through cleanup. No microphone or
matrix output is needed for this phase. The existing idle animation continues.
Afterward verify runtime/daemon epoch, firmware boot, boot default, user settings
and service configuration are unchanged. Record software readback separately
from physical observation. The one-second end-to-final requirement remains
unproven until the complete pipeline meets it, including endpointing/buffering.
