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


### CPU live acceptance update

Three initial live trials were responsive but did not establish reliable recognition. The first phrase/cue was uncontrolled and excluded from accuracy scoring. The two short, user-confirmed repetitions each had three word errors out of five; separate recordings do not establish a causal decoder improvement. Greedy and four-path beam search remain available. No independently annotated speech-end latency was measured. Microphone transcript/reference text and PCM were not saved in the results. GPU retirement completed after CPU preservation and known-file/rate-conversion checks. The next priority is CPU recognition quality and explicit whole-turn handling.
