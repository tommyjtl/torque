# UNO Q ncnn GPU and streaming speech experiment

The real Adreno 702 passed direct Vulkan vector addition and three dense matrix tests, with zero measured error against CPU arithmetic references.

The initial generic MatMul probe found no Vulkan implementation in the pinned engine. The successful matrix tests use its supported InnerProduct layer with batch inputs and explicit GPU weight upload. This is a different runtime from the earlier failed GGML experiment.

| Run | Device / pacing / profiling | Execution / endpoint acceptance | Measured transcripts | GPU timed operators |
| --- | --- | --- | --- | --- |
| 20261030T073357-probe | probe | not accepted; native exit 2 | 0 | 0 |
| 20261030T073746-probe | probe | passed | 0 | 0 |
| 20261030T075942-cpu-bulk | cpu / bulk | passed | 1 | 0 |
| 20261030T080032-gpu-bulk-profile | gpu / bulk / diagnostic profile | passed | 1 | 52194 |
| 20261030T080312-gpu-bulk | gpu / bulk | passed | 1 | 0 |
| 20261030T080913-cpu | cpu / paced | passed | 18 | 0 |
| 20261030T081418-gpu | gpu / paced | passed | 18 | 0 |

## Paced streaming measurements

Same six hashed LibriSpeech test-clean clips as Moonshine. One excluded warm-up. Three measured repetitions per clip for complete sweeps. Model stays loaded; English greedy decoding, four CPU threads, FP32 compute and a 0.3-second nonempty-utterance silence rule are used in both device modes. Audio arrives in ordered 20 ms chunks with three seconds of trailing silence.

| Mode | Accepted natural finals | Median final delay | Range | Under 1 s | WER, first repetition | Peak process RSS |
| --- | --- | --- | --- | --- | --- | --- |
| cpu | 18/18 | 0.387 s | 0.165–0.522 s | 18/18 | 4/136 = 2.9% | 101.9 MiB |
| gpu | 18/18 | 6.457 s | 4.008–13.935 s | 0/18 | 4/136 = 2.9% | 117.1 MiB |

### 20261030T080913-cpu

| Clip | Duration | Median final delay | First-pass WER |
| --- | --- | --- | --- |
| 6930-75918-0000 | 3.505 s | 0.519 s | 0.0% |
| 6930-75918-0006 | 5.850 s | 0.414 s | 0.0% |
| 6930-75918-0005 | 13.160 s | 0.461 s | 0.0% |
| 1320-122617-0003 | 6.285 s | 0.305 s | 0.0% |
| 1320-122617-0022 | 3.855 s | 0.167 s | 16.7% |
| 1320-122617-0002 | 13.585 s | 0.359 s | 4.5% |

Total worker CPU time: 197.70 CPU-s; largest processing call: 0.152 s; largest scheduled-input lag: 0.132 s.
Status IPC: median 2.27 ms; observed maximum 9.89 ms; 399 samples.

### 20261030T081418-gpu

| Clip | Duration | Median final delay | First-pass WER |
| --- | --- | --- | --- |
| 6930-75918-0000 | 3.505 s | 4.308 s | 0.0% |
| 6930-75918-0006 | 5.850 s | 6.325 s | 0.0% |
| 6930-75918-0005 | 13.160 s | 12.933 s | 0.0% |
| 1320-122617-0003 | 6.285 s | 6.462 s | 0.0% |
| 1320-122617-0022 | 3.855 s | 4.126 s | 16.7% |
| 1320-122617-0002 | 13.585 s | 13.513 s | 4.5% |

Total worker CPU time: 296.96 CPU-s; largest processing call: 0.921 s; largest scheduled-input lag: 15.870 s.
Status IPC: median 2.18 ms; observed maximum 5.62 ms; 774 samples.

## Interpretation and limits

Paced latency is file-end to the last natural endpoint with no pending later text; InputFinished is not called to manufacture an endpoint. There are no independently annotated human speech ends. Capture/ALSA cleanup and live microphone accuracy were not measured in this phase. A six-clip result is not a production p95 or accuracy guarantee.

Diagnostic profiling is separate from main timings. A small private patch makes only ncnn timestamp/query/log instrumentation opt-in; it does not change tensor operations. GPU diagnostic microsecond rows come from Vulkan timestamp queries. CPU fallback millisecond rows remain distinct. GPU-enabled speech is a hybrid execution mode; an initialization message is not evidence that every operator ran on the GPU.

CPU-s sums time across threads; process RSS excludes some driver/GPU allocations and is not whole-board memory. Backlog overlaps the final delay and must not be added to it. The endpoint rule and recognizer differ from Moonshine, so comparisons describe whole tested pipelines, not a GPU-only improvement to the Moonshine model.

Reference inputs: LibriSpeech/OpenSLR 12, CC BY 4.0, Vassil Panayotov, Daniel Povey, Guoguo Chen and Sanjeev Khudanpur. Source/model/package pins, raw logs and result snapshots are retained. No firmware upload, service restart or microphone capture is part of this experiment.
