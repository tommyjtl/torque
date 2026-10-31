# GPU speech-recognition alternatives after the GGML experiment

**Date:** 2026-10-29, America/Los_Angeles

**Status:** Source research only. No models, build tools, drivers or experiments
were installed on the UNO Q. The user requested another search for GPU STT
workarounds after removal of the Whisper experiment directories.

**Subsequent result:** The authorized
[ncnn experiment](2026-10-30-ncnn-streaming-speech-benchmark.md) verified real GPU
calculations and full GPU-enabled speech recognition. The conservative GPU
configuration was slower than CPU. CPU Zipformer passed the fixed-clip
file-end-to-final threshold in all 18 trials; live microphone acceptance remains
open. The text below records the original research and proposal.

The failed [GGML Vulkan trial](2026-10-29-whisper-vulkan-gpu-benchmark.md)
establishes a failure in that tested backend/driver configuration, not a failure
of every possible GPU inference runtime. No reproducible successful Adreno 702
GPU STT benchmark was found in this search. Primary upstream source inspection
did identify concrete alternatives.

## Candidates

1. **sherpa-ncnn streaming Zipformer with Vulkan.** The project's
   [comparison documentation](https://k2-fsa.github.io/sherpa/intro.html) lists
   ARM GPU Vulkan support and Linux ARM64. Its
   [Zipformer implementation](https://github.com/k2-fsa/sherpa-ncnn/blob/master/sherpa-ncnn/csrc/zipformer-model.cc)
   tests for a GPU and enables Vulkan on encoder, decoder and joiner before
   loading the networks. The model configuration exposes a GPU toggle. This is
   a distinct streaming model/runtime and cannot be compared as a GPU-only
   optimization of the existing Moonshine baseline. It is the first candidate
   for a small compatibility test, not an accepted UNO Q solution.

2. **ncnn's own Whisper implementation.** Tencent's
   [C++ example](https://github.com/Tencent/ncnn/blob/master/examples/whisper.cpp)
   enables Vulkan for the feature extractor, encoder, decoder and output
   projection. It explicitly disables FP16 packing, storage and arithmetic in
   that example. Converted models are linked from the author's
   [Android example](https://github.com/nihui/ncnn-android-whisper).
   The engine and shaders differ from GGML. The Android app is not a Debian
   executable; the portable C++ example is the relevant entry point. GPU flags
   alone do not prove that all operators actually execute on the GPU.

3. **LiteRT Moonshine Tiny and OpenCL.** The
   [converted model card](https://huggingface.co/litert-community/moonshine-tiny)
   supplies float32/int8 files and separate encode/decode signatures. This is
   the older 27M-parameter Moonshine Tiny with fixed five-second windows, not
   the Tiny Streaming English model used in the report. The card reports
   5.4 ms GPU encoding on a Galaxy S26, explicitly **encoder only**, with no
   full GPU transcription time. It is a different Adreno chip and Android
   driver stack. An OpenCL or GPU-encoder/CPU-decoder experiment would first
   need a validated Linux ARM64 runtime and operator-placement checks. Those
   phone numbers are not a latency prediction for UNO Q.

## Important limits found during inspection

- ncnn has an actual
  [UNO Q benchmark entry](https://github.com/Tencent/ncnn/blob/master/benchmark/README.md),
  but its command reports `gpu_device = -1`: it is a **CPU** benchmark of other
  networks, not proof of GPU speech recognition.
- Current
  [GGML OpenCL code](https://github.com/ggml-org/whisper.cpp/blob/master/ggml/src/ggml-opencl/ggml-opencl.cpp)
  recognizes specific Adreno generations and relies on subgroup features.
  Its generation matcher does not list 702. The board's earlier inventory
  reports Rusticl device name `FD702`; changing a name check would not establish
  correct subgroup behavior or kernel compatibility.
- MNN does provide OpenCL/Vulkan engines and a sherpa-mnn wrapper. However, the
  inspected wrapper's
  [session factory](https://github.com/alibaba/MNN/blob/master/apps/frameworks/sherpa-mnn/sherpa-mnn/csrc/session.cc)
  accepts a provider string without selecting a GPU backend in that function.
  A provider argument alone therefore is not a verified GPU workaround in that
  code path; runtime wiring and actual placement would need review.
- ncnn documents automatic CPU fallback for unsupported Vulkan operators and
  warns that GPU execution can be slower on ARM devices. A successful command
  or a GPU initialization message would not by itself satisfy acceleration
  acceptance. See the
  [ncnn Vulkan FAQ](https://ncnn.readthedocs.io/en/latest/how-to-use-and-FAQ/FAQ-ncnn-vulkan.html).

## Proposed next bounded experiment

First validate a few ncnn Vulkan compute operations on the actual Adreno 702,
using the current driver and checked CPU reference outputs. Only after those
pass, stage one small English streaming Zipformer model and compare ncnn CPU
and GPU modes with the same inputs and decoding settings. Log actual operator
placement, CPU fallbacks, correctness/WER, full final-text latency, memory and
input backlog. Use the existing Moonshine fixture copies and preserve its
working environment. Keep model/build storage bounded and export receipts.

This is a proposal, not an executed test or a promise of sub-one-second final
text. No driver update, firmware change or restoration of the removed Whisper
experiments was performed during this investigation.
