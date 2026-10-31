**Recorded-clip tests now meet the one-second file-end target on the CPU.** Streaming Zipformer produced its last natural final a median **0.387 seconds after file end**, with **18/18 trials below one second**, versus Moonshine’s previous best median of **1.458 seconds**. Full GPU-enabled Zipformer recognition also worked, but the tested hybrid configuration was slower at **6.457 seconds median**. **Live microphone latency and whole-turn endpoint detection remain unvalidated.**

Measured <date start="2026-10-29" end="2026-10-30" time-zone="America/Los_Angeles" /> on the physical UNO Q. Results use UTC timestamps. This report covers Whisper, Moonshine and the ncnn/Zipformer follow-up.

## What was tested

| Component | Observed configuration |
| --- | --- |
| Board | Arduino UNO Q, 4 GB variant; about 3.6 GiB usable RAM |
| Linux MPU | Qualcomm QRB2210, four Cortex-A53 CPU cores, up to 2.016 GHz |
| GPU | Turnip Adreno 702, Mesa 25.2.6, installed Freedreno Vulkan driver |
| System | Debian 13, Linux 7.0.0-g122c2c22d838, aarch64, CPython 3.13.5 |
| Concurrent application | Torque remained running; the MCU continued the resident matrix/RGB controller |
| Audio inputs | Six fixed English clips; earlier finite physical microphone trials through the Media Carrier MIC-IN jack |

Both CPU recognizers already run on the Linux MPU. The STM32 MCU is responsible for the resident controller; changing its firmware would not accelerate these ASR programs. The GPU is a separate execution path whose presence alone does not establish compatible inference. Arduino's [UNO Q product documentation](https://store.arduino.cc/products/uno-q-4gb) describes the board; the configuration above was checked on our board.

The fixed corpus contains six complete LibriSpeech test-clean utterances from two speakers, totaling **46.240 seconds and 136 reference words**. IDs and converted PCM SHA-256 hashes were frozen before comparing recognizers. Audio is mono, 16 kHz, signed PCM16. This is a small engineering screening set, not a general accuracy evaluation.

| Clip ID | Duration |
| --- | --- |
| 6930-75918-0000 | 3.505 s |
| 6930-75918-0006 | 5.850 s |
| 6930-75918-0005 | 13.160 s |
| 1320-122617-0003 | 6.285 s |
| 1320-122617-0022 | 3.855 s |
| 1320-122617-0002 | 13.585 s |

Dataset attribution: Vassil Panayotov, Daniel Povey, Guoguo Chen and Sanjeev Khudanpur; LibriSpeech derived from LibriVox, CC BY 4.0. The [OpenSLR dataset page](https://www.openslr.org/12/) supplies the corpus and license information. The attached measurement export includes references, hashes and fixed-clip hypotheses; microphone PCM and microphone transcript text are not attached.

## CPU results: full file decoding

The model is the original mixed F16/F32 `ggml-tiny.en.bin`, 77,704,715 bytes. Model SHA-256: `921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f`. The [pinned model asset](https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-tiny.en.bin) is shared by both Whisper builds.

These timings cover the complete transcription call with a resident model. They exclude loading and one initial warm-up, and use three measured repetitions per clip: **18 trials per row**. English greedy decoding uses best-of-one, no prior context, temperature zero and no temperature fallback.

| CPU build | Threads | Median full decode | Range | Aggregate RTF | Peak recognizer-process RSS |
| --- | --- | --- | --- | --- | --- |
| Prebuilt pywhispercpp 1.5.1 | 2 | 9.912 s | 9.438–11.305 s | 1.321 | 199.8 MiB |
| Prebuilt pywhispercpp 1.5.1 | 4 | 5.229 s | 5.011–6.228 s | 0.702 | 199.1 MiB |
| New native CPU/Vulkan build, CPU selected | 4 | 5.278 s | 5.003–6.046 s | 0.702 | 165.3 MiB |

RTF is total decoding time divided by total audio duration. An RTF below one means throughput faster than playback; it does not mean a final answer arrives within one second after speaking. Even the 3.5-second clip took about five seconds to decode. RSS is recognizer-process memory, excluding Torque and the rest of the OS; different wrapper/runtime overhead makes the two memory rows descriptive, not a pure engine-memory comparison.

The prebuilt four-thread process took about **1.272 seconds to become ready**, including imports and **0.257 seconds of model loading**. The new native build initialized the model in **0.242 seconds** and took **5.519 seconds for the excluded first decode**. These are ordinary cached-filesystem fresh-process observations; no reboot or forced cache drop established cold-storage startup.

**Accuracy correction:** the original Python harness joined stripped segment strings without spaces. That created false errors such as `partitionof` and inflated the reported WER to 7.4%. Those historical scores are invalid; their raw records and timing measurements are preserved. The worker now inserts segment boundaries, with a regression test. A separate fresh accuracy pass over all six clips at both two and four threads found **2/136 word errors = 1.5%** for each setting. The native CPU control independently found the same 1.5%. Four utterances were exact; two had one word error each. This is a harness correction, not evidence of a model or GPU accuracy improvement. Historical replay WER is also invalidated; no inferred word boundaries were retroactively substituted into the old raw text.

## Streaming results: delay after file end

The user-facing requirement is a stable whole-utterance final transcript within one second of actual speech end, including endpointing, buffering and cleanup. The available clips have no independent human speech-end annotations, so **file end is a proxy**. These results cannot establish live human speech-end latency.

Whisper paced replay fed ordered 20 ms audio chunks through its VAD pipeline, with a 700 ms trailing-silence endpoint. Its median **file-end-to-final was 5.888 seconds**; the VAD-estimated speech-end-to-final median was **5.955 seconds**, range **5.713–6.742 seconds**. A first-output callback arrived near the final result and did not provide a useful early transcript.

Moonshine used `moonshine-voice==0.1.5`, explicitly selected **Tiny Streaming English / ModelArch 2**, the dated `tiny-streaming-en/quantized_26_08_21` assets and the CPU provider. The main model group is about 45 MB. Downloaded spelling assets brought the cache to 46,899,201 bytes; spelling mode was not enabled. Model and wheel hashes are retained. These API/model choices follow the publisher's [available-model catalog](https://moonshine-voice.readthedocs.io/en/latest/models/available-models/) and [options documentation](https://moonshine-voice.readthedocs.io/en/latest/api/options/).

| Moonshine update interval / VAD window | Decode incomplete lines | Median file-end-to-final | Range | Under 1 s | Six-clip WER | Peak recognizer-process RSS |
| --- | --- | --- | --- | --- | --- | --- |
| 0.5 s / 0.5 s | Enabled | 2.464 s | 1.878–3.076 s | 0/6 | 1.5% | 262.0 MiB |
| 0.1 s / 0.15 s | Enabled | 2.250 s | 1.465–5.137 s | 0/6 | 2.2% | 256.8 MiB |
| 0.1 s / 0.15 s | Disabled; final-only | **1.458 s** | **1.129–1.908 s** | **0/6** | 2.2% | 241.4 MiB |

Each Moonshine configuration had one excluded warm-up and **one measured paced replay per clip**, followed by three seconds of paced silence. These are six-trial screening results, not three-repeat estimates or a p95 latency. Natural completed-line callbacks were timestamped before `stop()`; forced-stop, suspected duration-limit and errored completions were excluded. Multiple completed lines were combined for whole-utterance scoring. An early text-change event can accompany a completed clause, so it is not proof of an early stable whole-utterance result.

Moonshine kept all input samples. Blocking add-audio calls exceeded one second in some trials and caused measurable backlog, especially with incomplete-line decoding enabled. Its CPU threading was library-managed; no undocumented thread option was supplied. Final-only decoding reduced final delay on this screening set, but every trial still exceeded one second. The best configuration's ready time was **1.226 seconds**, including **0.466 seconds of model loading**. No physical microphone trial was run for Moonshine because CPU latency already missed the requirement and live-input acceptance remained unresolved.

### Moonshine: per-clip measurements

Configurations: **A** = 0.5 s update / 0.5 s VAD window with partial text; **B** = 0.1 s / 0.15 s with partial text; **C** = 0.1 s / 0.15 s with final-only text. All delays below are seconds from the original file end to the last natural completed-line callback. Each cell represents one measured replay after an excluded warm-up.

| Clip ID | Audio duration | A final delay | B final delay | C final delay | C word errors / reference words |
| --- | --- | --- | --- | --- | --- |
| 6930-75918-0000 | 3.505 s | 1.878 s | 1.465 s | 1.369 s | 0/8 |
| 6930-75918-0006 | 5.850 s | 2.236 s | 2.926 s | 1.908 s | 0/17 |
| 6930-75918-0005 | 13.160 s | 1.941 s | 2.877 s | 1.137 s | 0/33 |
| 1320-122617-0003 | 6.285 s | 2.713 s | 1.529 s | 1.129 s | 2/22 |
| 1320-122617-0022 | 3.855 s | 3.076 s | 1.623 s | 1.548 s | 0/12 |
| 1320-122617-0002 | 13.585 s | 2.692 s | 5.137 s | 1.675 s | 1/44 |

| Additional metric | A: default partials | B: tuned partials | C: final-only |
| --- | --- | --- | --- |
| Mean final delay | 2.423 s | 2.593 s | 1.461 s |
| Natural finals accepted | 6/6 | 6/6 | 6/6 |
| Results below 1.0 / 1.5 / 2.0 s | 0/6; 0/6; 2/6 | 0/6; 1/6; 3/6 | 0/6; 3/6; 6/6 |
| Word errors / reference words | 2/136 | 3/136 | 3/136 |
| Process start to ready | 1.183 s | 1.143 s | 1.226 s |
| Model load, included in ready time | 0.489 s | 0.455 s | 0.466 s |
| Peak recognizer-process RSS | 262.0 MiB | 256.8 MiB | 241.4 MiB |
| Total worker CPU time, six measured trials | 190.38 CPU-s | 200.98 CPU-s | 128.65 CPU-s |
| Longest blocking add-audio call | 2.590 s | 1.774 s | 2.156 s |
| Largest scheduled-input lag | 2.584 s | 5.056 s | 2.136 s |
| Torque status IPC: median / observed max | 1.81 / 9.47 ms | 1.79 / 6.77 ms | 2.00 / 6.94 ms |
| Status IPC sample count | 358 | 372 | 358 |

**Interpretation:** in this one-pass comparison, C reduced median final delay by 35.2% and total worker CPU time by 36.0% relative to B. C had 3/6 results below 1.5 seconds and 6/6 below two seconds. Its fastest result was 1.129 seconds, and its median missed the one-second target by 0.458 seconds. These are observed sample results, not latency guarantees or a p95 estimate.

All three configurations produced natural finals on the six measured clips. The 1.5% versus 2.2% aggregate WER difference is only one additional word error (2 versus 3 out of 136); this sample does not establish a general accuracy tradeoff. Four clips were word-exact in C. WER removes punctuation and ignores case; it is not semantic command-success accuracy.

**How to read resource metrics:** CPU-s sums user and system CPU time across worker threads, so it can exceed elapsed wall time. It covers the six paced trials, including the three seconds of appended silence per trial and stream stop; model loading and the excluded warm-up are outside that sum. RSS is the worker process high-water mark, including its libraries/model and earlier warm-up allocations, rather than model-weight size or whole-board RAM. IPC measures Torque daemon status requests, not microphone or recognition latency.

**Responsiveness limit:** C still blocked inside a single add-audio call for up to 2.156 seconds and accumulated up to 2.136 seconds of scheduled-input lag. B reached 5.056 seconds of lag. Input samples were retained. These intermediate backlog measurements overlap the reported final delay and must not be added to it. The synchronous feed path needs separate capture/inference scheduling before a responsive live application can be accepted.

Evidence: retained Moonshine bundle `20261030T035510`, with runs `files-0.5-0.5-035510` (A), `files-0.1-0.15-035942` (B), and `files-0.1-0.15-040237` (C). These details were calculated from existing logs; no new inference or microphone trial was run. File end remains an unannotated proxy for speech end, and live-microphone performance remains unverified.

## Whisper GGML/Vulkan experiment: compatibility failure

The isolated ARM64 build pins Whisper revision `f24588a272ae8e23280d9c220536437164e6ed28`, matching the Python binding's upstream engine revision. The new build's CPU result above is the matched control. Compiler/build differences remain visible rather than being attributed to GPU acceleration. The engine documents [Vulkan support](https://github.com/ggml-org/whisper.cpp#vulkan-gpu-support); compatibility was tested against the [pinned source](https://github.com/ggml-org/whisper.cpp/tree/f24588a272ae8e23280d9c220536437164e6ed28).

`VK_DRIVER_FILES` selected only the installed Freedreno ICD, excluding llvmpipe. The actual Adreno reported a compute queue, 16-bit storage and shader FP16. The loader's API version was 1.4.309; the physical device's was 1.0.318. Loader and device versions are distinct facts and neither enumeration nor the loader version establishes working ASR.

| Configuration | Outcome | Accepted GPU transcripts |
| --- | --- | --- |
| Stock backend, profiling enabled | Initialization refused the 16 KiB shared-memory limit | 0 |
| Private compatibility patch, FP16, profiling enabled | `vk::DeviceLostError` / queue submission failed | 0 |
| Same patch, FP16, profiling disabled | Same device loss | 0 |
| Same patch, FP32 compute, fusion disabled | Same device loss | 0 |

The stock backend checks quantized dtypes at initialization even when the original Tiny model does not use them. Its smallest IQ1 tile required **16,512 bytes**, exceeding **16,384 bytes of shared memory per workgroup**. This is a per-workgroup limit, not the model's total GPU memory budget. A private patch disabled unsupported dtypes and routed those unsupported matrix multiplications to CPU; it preserved the real limit and did not alter F16 shader math or weights.

With the patch, Vulkan0 was selected and **77.11 MB of model buffers** were allocated. Inference then aborted before even the warm-up produced a transcript. Initialization around 0.56 seconds is therefore not a GPU transcription timing. Disabling profiling and then FP16/fusion did not fix it. No completed GPU kernel profile or final transcript was accepted, and the specific shader/driver root cause remains unisolated. Further GPU attempts on this configuration were stopped. These failures do not establish that Adreno acceleration is impossible, but there is currently no usable GPU path from this experiment.

The private toolchain was extracted from 115 hash-pinned Debian packages into the project, without installing packages or changing drivers. A generated 140 MB C++ shader-byte file exceeded compilation memory. Large arrays were instead embedded from their original SPIR-V files, with per-array size/SHA-256 checks and a native linked byte-identity test. This was build packaging, not an inference optimization. Compilation used one job. Source locks, build flags, the compatibility patch and raw failure logs are retained.

OpenCL also enumerated a real Rusticl `FD702` GPU, but no OpenCL ASR model was built or timed. The backend's device-family and subgroup assumptions still need validation; OpenCL enumeration is not an accepted alternative inference result. No CUDA, Android NNAPI or dedicated NPU result is claimed.

## ncnn / Zipformer follow-up: working GPU, faster CPU

**Adopted direction (2026-10-30):** CPU Zipformer is selected for the next prototype. The tested GPU path is closed for latency (6.457 s median; 0/18 under one second), while its recognition was correct. GPU evidence is archived. On-board retirement is complete. The CPU model, runtime and live files remain in zipformer-cpu; the old GPU build/test directory has been removed.

Measured <date start="2026-10-30" time-zone="America/Los_Angeles" />. **Streaming Zipformer on the CPU is now the fastest tested pipeline on this UNO Q.** The GPU path also completed real speech recognition, but its tested conservative configuration was much slower.

| Mode | Median file-end-to-final | Range | Below 1 s | Six-clip WER | Peak process RSS |
| --- | --- | --- | --- | --- | --- |
| CPU, four threads | **0.387 s** | **0.165–0.522 s** | **18/18** | 4/136 = 2.9% | 101.9 MiB |
| Adreno Vulkan + CPU fallbacks | 6.457 s | 4.008–13.935 s | 0/18 | 4/136 = 2.9% | 117.1 MiB |

Both modes used the same executable, publisher weights, greedy decoder and 0.3-second nonempty-speech silence rule. There was one excluded warm-up, then three paced repetitions of each of the same six clips. Audio arrived in ordered 20 ms chunks, followed by three seconds of silence; model loading and diagnostic profiles were excluded from these latency numbers. Normalized transcripts matched in all **18 paired trials**. WER counts each unique clip once, using the first repetition.

| Clip ID | Duration | CPU median | GPU median | Word errors / reference words | CPU completed segments |
| --- | --- | --- | --- | --- | --- |
| 6930-75918-0000 | 3.505 s | 0.519 s | 4.308 s | 0/8 | 1 |
| 6930-75918-0006 | 5.850 s | 0.414 s | 6.325 s | 0/17 | 1 |
| 6930-75918-0005 | 13.160 s | 0.461 s | 12.933 s | 0/33 | 5 |
| 1320-122617-0003 | 6.285 s | 0.305 s | 6.462 s | 0/22 | 1 |
| 1320-122617-0022 | 3.855 s | 0.167 s | 4.126 s | 2/12 | 1 |
| 1320-122617-0002 | 13.585 s | 0.359 s | 13.513 s | 2/44 | 3 |

| Resource / responsiveness metric | CPU | GPU hybrid |
| --- | --- | --- |
| Native model initialization, cached filesystem | 0.389 s | 3.264 s |
| Worker CPU time across 18 trials | 197.70 CPU-s | 296.96 CPU-s |
| Longest processing call | 0.152 s | 0.921 s |
| Largest observed scheduled-input lag | 0.132 s | 15.870 s |
| Torque status IPC, median / observed maximum | 2.27 / 9.89 ms | 2.18 / 5.62 ms |
| Status IPC samples | 399 | 774 |

**GPU evidence:** direct Vulkan addition and three dense matrix tests matched CPU references with zero measured error. Full model calibration then returned the exact eight-word reference, with 52,194 positive GPU timing rows and 6,476 CPU profile rows across its warm-up and measured trial. GPU timestamps and CPU fallbacks were logged separately. Main runs disabled this profiling and used the same executable. Counts are operation instances, not unique layers or a percentage of compute offloaded.

**What this establishes:** ncnn offers a working GPU speech-recognition path on the UNO Q, while the tested CPU configuration provides the better final-text latency. The GPU run kept all samples and accumulated backlog. The result applies to the recipe-pinned runtime with FP32 compute and subgroup/cooperative-matrix paths disabled; FP16 tuning, newer runtimes and other models were not evaluated here. No universal GPU performance ceiling or isolated bottleneck is claimed.

**Fast endpoint qualification:** the two longest clips emitted five and three completed segments. The harness joined all segments and timed the last final after the entire known file, with no pending later text. A segment ending during a pause is not proof that the person has finished their whole turn. For a first voice-command prototype, use push-to-talk or a separate end-of-turn policy before sending commands to the agent. These measurements do not include live microphone buffering or capture cleanup, and file end still lacks an independent human speech-end annotation.

Compared with the previous best Moonshine pipeline, this CPU configuration has lower measured final delay (0.387 versus 1.458 s). Its six-clip WER is one additional word error (4 versus 3 out of 136), which is too little data to establish a general accuracy tradeoff. The model and endpoint policy both differ, so this is a comparison of tested pipelines rather than an isolated engine speedup.

Reproduction: sherpa-ncnn `c61e50d61e9fbed5972afa4d95bc560e168affe2` and its ncnn pin `c4193aadbbb56582aa87b1850dd3d98fb8fd936d`; the small English [Zipformer model](https://huggingface.co/marcoyang/sherpa-ncnn-streaming-zipformer-20M-2023-02-17), revision `20af696d92a32438db47fb7d4bd961b36fb07021`, totals 41,329,751 bytes and is publisher-declared Apache-2.0. Package, source, model and fixture hashes are included in the attached data. A private patch makes only diagnostic instrumentation opt-in; model/operator math was not modified.

Final checks: 348 tests ran on each machine with no failures (Mac two skips, UNO Q four). Runtime, firmware boot, service configuration, user settings and boot default were unchanged; workers were reaped and the program lease was free. Sixteen Moonshine model/fixture hashes matched. Unused verified package-download caches were pruned, reclaiming 109,842,044 bytes; the retained experiment occupied about 666 MiB. No live microphone capture, firmware upload or service restart occurred.

## Physical microphone trials and limits

The carrier input was the `ArduinoImolaHPH` capture device, DEV 2 / MultiMedia3, mono 48 kHz S32_LE, through Torque's ordered microphone stream. Audio was resampled to 16 kHz for recognition. Samples stayed in memory; no audio files or network audio uploads were made. Recognized phrases were never executed as commands.

The first three Whisper live trials were not controlled accuracy trials: the user reported missing readiness windows. A subsequent trial used the matrix for 3–2–1 countdown, a speak circle, processing dots and a completion check. It reached the 30-second listening limit without a reliable endpoint and produced an incorrect `(upbeat music)` result. That text is a recognition failure, not proof that music was present. Truncated/uncontrolled trials are excluded from latency and accuracy acceptance.

A fixed known clip passed through the same resampler/VAD and yielded the expected eight words. That checks software format handling, not the physical microphone's speech quality. An earlier resampler-burst endpoint bug was corrected. All nine touched ALSA route controls were restored after capture. The input level meter working does not establish reliable live recognition; that remains an open issue.

## Verification and retained evidence

The latest suites ran 348 tests on the Mac (two skips) and UNO Q (four skips), with no failures. Native hardware tests and software readback are recorded separately from unit tests and physical observation.

The active Torque release, daemon epoch/PID, firmware boot ID, session/model/permission settings, Arduino boot default, service configuration and settings hashes stayed unchanged through the GPU experiment. The OS package database hash also stayed unchanged. Workers were reaped, the program lease was free, and four distinct framebuffer samples matched the unowned Heart Pulse idle animation. No firmware upload, service restart or live microphone opening occurred in the GPU phase.

Only 115 unused, hash-verified downloaded `.deb` caches were removed after checking process descriptors and container mount references, reclaiming **104,936,260 bytes**. Extracted tools, source archive, vendor source, executables, logs, receipts, model/fixture inputs and results were retained. The GPU project occupied about **999 MiB** after cleanup, within its 2 GiB budget. Root/home remained separate storage pools, with about **1.49 GiB / 12.83 GiB available**, respectively.

All sources and results are retained locally. The Whisper projects were removed from the UNO Q at the user’s request after archival; Moonshine and ncnn-speech-benchmark remain on the board. Original result bundles and new runs 20261030T080913-cpu / 20261030T081418-gpu are preserved with source and model hashes.

The next step is a controlled live microphone prototype using CPU Zipformer, with push-to-talk or a separate whole-turn endpoint policy. Live buffering, cleanup and speech-end latency still need measurement. No recognized text is automatically executed as a board command.

### CPU live acceptance update

Three initial live trials were responsive but did not establish reliable recognition. The first phrase/cue was uncontrolled and excluded from accuracy scoring. The two short, user-confirmed repetitions each had three word errors out of five; separate recordings do not establish a causal decoder improvement. Greedy and four-path beam search remain available. No independently annotated speech-end latency was measured. Microphone transcript/reference text and PCM were not saved in the results. GPU retirement completed after CPU preservation and known-file/rate-conversion checks. The next priority is CPU recognition quality and explicit whole-turn handling.
