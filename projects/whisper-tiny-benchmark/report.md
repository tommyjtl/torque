# UNO Q Whisper tiny.en measurements

CPU-only prebuilt pywhispercpp 1.5.1, original Tiny English weights. Six complete LibriSpeech test-clean utterances from two speakers; this is a small smoke test.

## 20261030T030038-replay

Historical WER is invalid: stripped segment texts were joined without spaces. Raw results are preserved; see the separate corrected accuracy pass. Latency remains valid.


| Trial | Endpoint to final (s) | VAD estimated end to final (s) | WER |
| --- | --- | --- | --- |
| 6930-75918-0000 | 5.031 | 5.713 | invalid (segment join) |
| 6930-75918-0006 | 5.221 | 5.903 | invalid (segment join) |
| 6930-75918-0005 | 5.756 | 6.439 | invalid (segment join) |
| 1320-122617-0003 | 5.325 | 6.007 | invalid (segment join) |
| 1320-122617-0022 | 5.156 | 5.838 | invalid (segment join) |
| 1320-122617-0002 | 6.061 | 6.742 | invalid (segment join) |

VAD-estimated end is not an independently annotated human speech end. Live audio-clock anchoring uses PCM arrival; transport/buffer delay is not independently measured. Microphone samples and transcript text are not saved in these results.

ipc_baseline (baseline): 5 status IPC samples; median 1.93ms, maximum 2.91ms.

## 20261030T030312-mic


| Trial | Endpoint to final (s) | VAD estimated end to final (s) | WER |
| --- | --- | --- | --- |
| Incomplete/no accepted utterance | not established | not established | not scored |
| 1 | 5.499 | 5.502 | 100.0% |
| Incomplete/no accepted utterance | not established | not established | not scored |

VAD-estimated end is not an independently annotated human speech end. Live audio-clock anchoring uses PCM arrival; transport/buffer delay is not independently measured. Microphone samples and transcript text are not saved in these results.

Truncated listening windows are excluded from recognition-quality and post-speech latency conclusions.

ipc_baseline (baseline): 5 status IPC samples; median 2.06ms, maximum 2.83ms.

## 20261030T031059-mic


| Trial | Endpoint to final (s) | VAD estimated end to final (s) | WER |
| --- | --- | --- | --- |
| Incomplete/no accepted utterance | not established | not established | not scored |

VAD-estimated end is not an independently annotated human speech end. Live audio-clock anchoring uses PCM arrival; transport/buffer delay is not independently measured. Microphone samples and transcript text are not saved in these results.

Truncated listening windows are excluded from recognition-quality and post-speech latency conclusions.

ipc_baseline (baseline): 5 status IPC samples; median 2.71ms, maximum 3.51ms.

## 20261030T031529-files

Historical WER is invalid: stripped segment texts were joined without spaces. Raw results are preserved; see the separate corrected accuracy pass. Latency remains valid.

| Threads | Warm median / range (s) | Aggregate RTF | WER, six unique clips | Worker peak RSS (MiB) |
| --- | --- | --- | --- | --- |
| 2 | 9.912 / 9.438–11.305 | 1.321 | invalid (segment join) | 199.8 |
| 4 | 5.229 / 5.011–6.228 | 0.702 | invalid (segment join) | 199.1 |

Warm inference excludes model initialization; three repetitions per utterance. WER uses the first repetition of each unique clip, not repeated copies as independent speech.

| Threads | Clip duration (s) | Warm median (s) | WER |
| --- | --- | --- | --- |
| 2 | 3.505 | 9.507 | invalid (segment join) |
| 2 | 5.850 | 9.819 | invalid (segment join) |
| 2 | 13.160 | 10.807 | invalid (segment join) |
| 2 | 6.285 | 10.081 | invalid (segment join) |
| 2 | 3.855 | 9.724 | invalid (segment join) |
| 2 | 13.585 | 11.291 | invalid (segment join) |
| 4 | 3.505 | 5.028 | invalid (segment join) |
| 4 | 5.850 | 5.149 | invalid (segment join) |
| 4 | 13.160 | 5.725 | invalid (segment join) |
| 4 | 6.285 | 5.326 | invalid (segment join) |
| 4 | 3.855 | 5.156 | invalid (segment join) |
| 4 | 13.585 | 6.039 | invalid (segment join) |

2 threads: imports 0.932s; model load 0.253s; process to ready 1.262s.

2-thread silence control returned: '[BLANK_AUDIO]'.

4 threads: imports 0.938s; model load 0.257s; process to ready 1.272s.

4-thread silence control returned: '[BLANK_AUDIO]'.

ipc_baseline (baseline): 5 status IPC samples; median 2.79ms, maximum 3.17ms.

ipc_under_load (2): 1001 status IPC samples; median 1.75ms, maximum 3.53ms.

ipc_under_load (4): 530 status IPC samples; median 1.99ms, maximum 7.42ms.

## 20261030T060930-accuracy-correction

Corrected segment joining; one new accuracy pass per clip and thread setting. Historical timing measurements are unchanged.

| Threads | Word errors / reference words | Corrected WER |
| --- | --- | --- |
| 2 | 2/136 | 1.5% |
| 4 | 2/136 | 1.5% |

## Interpretation

A completed run establishes measurement and cleanup, not acceptable voice-interface latency. Compare total post-speech delay against the one-second target, including endpoint silence and capture cleanup. No automatic board commands or cloud inference are part of this benchmark.
