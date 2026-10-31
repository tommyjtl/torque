# CPU Zipformer live microphone experiment

**Date:** 2026-10-30, America/Los_Angeles; result IDs use UTC `20261031`.

**Result:** Live CPU capture/transcription worked and the participant reported
quick completion. Recognition quality did not pass the short phrase checks.
The recorded-file sub-one-second result remains separate from live acceptance.

The user requested voice input before GPU cleanup. All build/model files were
kept while implementing and testing the CPU worker. No GPU experiments resumed.
The board was reachable again, using runtime `0.2.0-9ed93a142a1d`, firmware boot
`1395641681` and the Media Carrier input. No service restart or firmware upload
was needed.

## Pipeline and software checks

The separate CPU worker links the previously pinned sherpa-ncnn/ncnn libraries.
Only the new IPC wrapper was compiled, leaving the matched benchmark executable
unchanged. The build uses the retained compile/link recipe directly, avoiding a
date-based CMake regeneration and unnecessary library rebuild.

Capture uses `torque.audio.Microphone`, a discovered `ArduinoImolaHPH` card and
ordered 20 ms mono 48 kHz S32_LE blocks. The native stream performs stateful
resampling to the model's 16 kHz input. Known-file tests at both 16 kHz and
48 kHz reproduced the exact eight-word reference with greedy and modified beam
search; no microphone was opened for those checks.

The model loads before capture readiness. The matrix counts 3–2–1, displays a
hollow speak circle, then processing/completion cues. Capture is limited to
40 seconds, with at most 30 seconds after READY. A separate reader drains capture
into a bounded one-second queue; old input is not dropped. Model/release leases,
parent-death handling, native alarms and normal SIGTERM/finally cleanup are used.

## Live trials

| UTC result ID | Decoder | Accuracy interpretation |
| --- | --- | --- |
| `20261031T040657-voice` | Greedy | Participant missed the window or said a different phrase. Prompt score is retained but marked unusable; not an accepted accuracy test. |
| `20261031T041157-voice` | Greedy | User provided the actual short phrase afterward. Three word errors in five reference words; not exact. |
| `20261031T042118-voice` | Modified beam search, four paths | User repeated the phrase with connected initial words. Key content improved qualitatively, but the prefix was wrong; three substitutions in five words. |

The last two trials were separate utterances, not replay of the same PCM. Their
single-phrase scores cannot establish general WER or a causal decoder improvement.
No expected phrase or hotword was supplied to the recognizer. Connected speech
is normal usage; changing the person's pronunciation is not an acceptance fix.

| Metric | Greedy free speech | Beam free speech |
| --- | --- | --- |
| Audio consumed | 4.260 s | 4.260 s |
| Largest native processing call | 0.109 s | 0.111 s |
| Largest observed queue lag | 0.109 s | 0.111 s |
| Peak process RSS | 149.3 MiB | 149.3 MiB |
| Input RMS | 0.255 | 0.271 |
| Full-scale sample fraction | 0.041% | 0.051% |
| Capture cleanup after native final | 0.455 s | 0.454 s |

These levels do not isolate the cause of recognition errors. No independent
human speech-end annotation was collected, so no numerical live speech-end
latency claim is made. The participant's quick-completion report is qualitative.
The 0.3-second model endpoint can split longer speech; whole-turn handling is
still unvalidated.

## Cleanup and next direction

After every capture, all nine touched mixer controls matched their prior values,
the microphone closed and matrix ownership was released to status. Runtime and
firmware boot remained unchanged. PCM and microphone transcript/reference text
were not saved in result files; only aggregate signal/timing/scoring fields and
participant feedback were retained. Recognized text appeared in the calling
terminal/conversation and was never executed as a board command.

CPU Zipformer remains the selected development baseline. Next work is recognition
quality and explicit turn handling, including microphone clarity investigation
or a larger compatible CPU model if needed. Neither decoder is production-ready
from these trials. The CPU runtime, model, both decoder choices and live results
must be preserved before retiring the GPU build/test directory.

Retirement subsequently completed after a CPU smoke test. The CPU live sources,
runtime, both decoder choices, model, fixtures and trial results are retained in
`~/torque/projects/zipformer-cpu`; the old GPU experiment/build directory is gone.
The worker's known-file tests at both sample rates passed again after removal.
See the [retirement receipt](2026-10-30-ncnn-streaming-speech-benchmark.md#adopted-direction-and-gpu-retirement).
