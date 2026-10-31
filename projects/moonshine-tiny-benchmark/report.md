# UNO Q Moonshine Tiny Streaming CPU screening

Same six hashed LibriSpeech test-clean clips as the Whisper baseline. One excluded warm-up and one measured paced replay per clip/configuration. No GPU acceleration or live microphone capture was used.

**Latency is file-end to the last natural completed-line callback.** There are no independent human speech-end annotations. Forced-stop and suspected duration-limit completions are excluded. These six-clip screening results do not establish production accuracy or a p95 latency.

| Update interval / VAD window | Decode incomplete lines | Median final delay | Range | Under 1 s | WER | Peak RSS |
| --- | --- | --- | --- | --- | --- | --- |
| 0.1 s / 0.15 s | True | 2.250 s | 1.465–5.137 s | 0/6 | 2.2% | 256.8 MiB |
| 0.1 s / 0.15 s | False | 1.458 s | 1.129–1.908 s | 0/6 | 2.2% | 241.4 MiB |
| 0.5 s / 0.5 s | True | 2.464 s | 1.878–3.076 s | 0/6 | 1.5% | 262.0 MiB |

The tested CPU configurations improved on the approximately 5.9-second Whisper paced-replay median, but none of these measured natural-final file-end delays met the one-second target. CPU defaults are library-managed; no unsupported thread option was supplied. Early text-change callbacks can also accompany completed clauses and are not proof of a stable whole-utterance transcript.

## 0.1 s / 0.15 s; incomplete-line decoding True

| Clip | Duration | Final delay | WER | Largest input lag |
| --- | --- | --- | --- | --- |
| 6930-75918-0000 | 3.505 s | 1.465 s | 0.0% | 0.972 s |
| 6930-75918-0006 | 5.850 s | 2.926 s | 0.0% | 2.477 s |
| 6930-75918-0005 | 13.160 s | 2.877 s | 0.0% | 2.514 s |
| 1320-122617-0003 | 6.285 s | 1.529 s | 9.1% | 1.666 s |
| 1320-122617-0022 | 3.855 s | 1.623 s | 0.0% | 1.639 s |
| 1320-122617-0002 | 13.585 s | 5.137 s | 2.3% | 5.056 s |

Process/import/model to ready: 1.143 s; model load 0.455 s.
Largest observed blocking add-audio call: 1.774 s. Input was preserved, with backlog measured rather than hidden by dropping samples.
Status IPC: median 1.79 ms, maximum 6.77 ms (372 samples).

## 0.1 s / 0.15 s; incomplete-line decoding False

| Clip | Duration | Final delay | WER | Largest input lag |
| --- | --- | --- | --- | --- |
| 6930-75918-0000 | 3.505 s | 1.369 s | 0.0% | 1.174 s |
| 6930-75918-0006 | 5.850 s | 1.908 s | 0.0% | 1.758 s |
| 6930-75918-0005 | 13.160 s | 1.137 s | 0.0% | 2.136 s |
| 1320-122617-0003 | 6.285 s | 1.129 s | 9.1% | 1.383 s |
| 1320-122617-0022 | 3.855 s | 1.548 s | 0.0% | 1.703 s |
| 1320-122617-0002 | 13.585 s | 1.675 s | 2.3% | 1.881 s |

Process/import/model to ready: 1.226 s; model load 0.466 s.
Largest observed blocking add-audio call: 2.156 s. Input was preserved, with backlog measured rather than hidden by dropping samples.
Status IPC: median 2.00 ms, maximum 6.94 ms (358 samples).

## 0.5 s / 0.5 s; incomplete-line decoding True

| Clip | Duration | Final delay | WER | Largest input lag |
| --- | --- | --- | --- | --- |
| 6930-75918-0000 | 3.505 s | 1.878 s | 12.5% | 1.383 s |
| 6930-75918-0006 | 5.850 s | 2.236 s | 0.0% | 1.554 s |
| 6930-75918-0005 | 13.160 s | 1.941 s | 0.0% | 2.311 s |
| 1320-122617-0003 | 6.285 s | 2.713 s | 0.0% | 1.993 s |
| 1320-122617-0022 | 3.855 s | 3.076 s | 0.0% | 2.584 s |
| 1320-122617-0002 | 13.585 s | 2.692 s | 2.3% | 2.362 s |

Process/import/model to ready: 1.183 s; model load 0.489 s.
Largest observed blocking add-audio call: 2.590 s. Input was preserved, with backlog measured rather than hidden by dropping samples.
Status IPC: median 1.81 ms, maximum 9.47 ms (358 samples).
