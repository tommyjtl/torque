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
