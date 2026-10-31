# Isolated Whisper tiny.en benchmark on UNO Q

**Date:** 2026-10-29, America/Los_Angeles

**Status:** Isolated harness implemented; fixed-file and paced-replay measurements
completed. Microphone trials are being investigated; recognition quality is not
accepted. This remains an experiment, not an installed speech-recognition SDK.

## Question and first scope

Measure whether local English transcription is useful on our UNO Q, using
Whisper `tiny.en` through the CPU backend of `whisper.cpp`. Start with a small,
fixed set of English recordings, then test the Media Carrier MIC-IN microphone.
Keep Torque running normally so the results describe this device in use.

The first experiment uses the original `ggml-tiny.en.bin` model, two and four
inference threads, and one decoder configuration. Quantized models, Moonshine,
continuous partial transcription and production SDK integration are follow-ups.
This is utterance-at-a-time recognition: listen, detect the end, transcribe.
It must not be described as native streaming Whisper.

The earlier NXP Cortex-A53 figures demonstrate a possible performance range for
another optimized pipeline. They are not an expected result or acceptance test
for this implementation. Measure the complete transcription, not just encoder
timing from `whisper-bench`.

## Checked board and dependency path

The read-only inventory on 2026-10-29 found:

- Four CPU cores, up to 2.016 GHz; about 3.6 GiB usable RAM. Linux reports
  `fp asimd ...` CPU features, without the newer dot-product/FP16 arithmetic flags.
  Do not assume newer ARM instructions or GPU/NPU acceleration.
- CPython 3.13.5, Linux aarch64, glibc 2.41.
- `arecord`, `amixer` and Git available; CMake, Ninja, C/C++ compilers, FFmpeg and
  SoX absent from PATH. Their absence is not permission to install OS packages.
- Approximately 14.2 GiB available on `/home/arduino`, versus 1.48 GiB on the
  separate `/opt/torque` filesystem. Put experiment artifacts on the home volume.
- Torque `0.2.0-9ed93a142a1d` ready and idle; controller 0.4.0/protocol 1.3,
  MCU boot `1295313560`. Recheck these observations before execution.

Prefer a private Python environment with a binary `pywhispercpp` CPU wheel.
This binding keeps the Whisper context resident and accepts NumPy PCM arrays.
PyPI currently publishes a candidate `pywhispercpp==1.5.1` CPython 3.13,
manylinux aarch64 wheel. Candidate resampling and endpointing dependencies are
`soxr==1.1.0` and `webrtcvad-wheels==2.0.14.post1`; compatible aarch64 wheels are
also listed. NumPy and all transitive dependencies need exact versions/hashes
in the experiment lockfile. These are inventory findings, not tested installs.

Use binary-only resolution into that environment and fail on a missing wheel;
do not silently compile on the board. Check imports, CPU feature compatibility,
actual binding parameters and the bundled engine version before timed trials.
Record the wheel hashes and backend system information. A prebuilt-wheel result
is not a claim about the fastest possible native build. If it fails, prepare a
separate Linux/aarch64 build off-board with compatible instructions and libraries;
do not substitute a macOS ARM executable or change Torque's dependencies.

## Location and isolation

Keep the reproducible harness in repository `projects/whisper-tiny-benchmark/`.
On UNO Q, use the corresponding separate project directory:

```text
/home/arduino/torque/projects/whisper-tiny-benchmark/
  runner.py                 # installed Torque Python: orchestration and capture
  worker.py                 # private environment: inference/resampling/VAD
  requirements.lock         # exact experiment-only dependencies and hashes
  fixtures.json             # immutable sample IDs, references and provenance
  .venv/                    # isolated; no system-site-packages
  models/                   # one pinned tiny.en model
  fixtures/                 # small licensed English sample pack
  results/<run-id>/          # manifest, metrics.jsonl and report.md
  scratch/<run-id>/          # bounded temporary run artifacts
```

These paths and scripts are proposed, not installed commands. Keep downloaded
weights, environments, audio and generated results out of Git. The initial
experiment does not add an example-catalog entry or a `torque speech` command.
It does not require a Torque release update, service restart, Arduino app
start/stop, MCU flash or boot-default change. It does not acquire or draw on the
matrix by default; normal Heart Pulse status can continue. The user subsequently
requested physical guidance: optional `--guide-matrix` temporarily owns the
matrix for a 3-2-1 countdown, hollow speak circle, working dots and completion
check, then releases it back to status. A check means completed, not accurate.

Launch the runner through the existing managed-project path (`torque run`) using
the installed Torque Python for `torque.audio`. Launch the inference worker with
the private environment's Python. Do not install another Torque copy into that
environment or change `PYTHONPATH` globally. Preserve program/release leases
through child cleanup, and keep the worker tied to the runner's lifetime so a
disconnect or terminated runner cannot leave unbounded inference behind.

## Model and fixed English clips

Download the English-only Tiny model from the model repository linked by
upstream `whisper.cpp`. Record its immutable revision, SHA-256, byte size and
license. Pass its local path to the binding so timed runs cannot auto-download
or choose another model. Download/setup time is separate from inference.

Use the upstream JFK sample only for a compatibility smoke test. For the actual
comparison, freeze six complete LibriSpeech `test-clean` utterances from at least
two speakers: two approximately 2–4 seconds, two 5–8 seconds and two 10–15 seconds.
Choose IDs by metadata/duration before running recognition. Keep natural word
boundaries; do not cut a long recording into arbitrary short fragments or count
repeated copies as independent utterances.

Each manifest entry records source URL/revision, corpus/speaker/utterance ID,
reference transcript, source/converted hashes, exact sample count and conversion
recipe. LibriSpeech is CC BY 4.0: preserve attribution with the fixture pack.
Prepare only these samples on the Mac, where FFmpeg is available, and transfer
mono 16 kHz PCM WAVs. Do not download the entire corpus onto UNO Q. Also include
a separately labelled synthetic silence control to expose spurious text.

## Trial method and measurements

Fix English, transcription rather than translation, greedy decoding, temperature
zero, no temperature fallback, no previous-transcript context and no prompt or
reference-text hints. Keep the ordinary audio-context setting; any later context
or decoding optimization is a separate configuration with another accuracy check.
Use one worker/context at a time, without parallel file decoding or hidden batching.
Record all effective parameters and whether CPU-only execution was verified.

For each thread count:

1. Start a fresh worker and record Python/import time, model initialization,
   first inference and total process-start-to-final time separately. This is a
   fresh-process measurement; do not call it a cold disk/page-cache result. Do
   not clear the kernel cache or reboot to manufacture a cold run.
2. Warm up once, then run all six clips three times using the same model context.
   Reuse weights, but disable text-context reuse between utterances. Alternate
   configuration order or record the order and temperature/load drift.
3. Time PCM preparation separately from the complete model call. Preserve raw
   per-trial values; report median and range. Three repetitions do not justify a
   confident p95 or a general accuracy claim.

| Measurement | Definition |
| --- | --- |
| Decode wall time | Monotonic time from ready 16 kHz samples to final transcript |
| Real-time factor (RTF) | Decode wall seconds / actual input-audio seconds; below 1 is faster than real time |
| First output | Time to the first nonempty callback/segment, if available; not a stable final transcript |
| Initialization | Process/import and model-load times, separate from warm decode |
| CPU | User/system CPU deltas and wall time; name the convention if reporting percent |
| Memory | Worker peak RSS with explicit units; a reused worker's high-water mark is cumulative, not per-clip RSS |
| Accuracy | Per-clip and pooled `(substitutions + deletions + insertions) / reference words` |

For WER, normalize references and hypotheses identically: lowercase, remove
punctuation and collapse whitespace, with no semantic rewriting or answer hints.
Publish raw and normalized fixed-clip transcripts with errors. List silence
output separately, since empty-reference WER is undefined. Six utterances provide
a practical smoke test, not a replacement for a full ASR evaluation dataset.

## Microphone and end-of-speech latency

Use the existing [local microphone API](2026-10-29-local-microphone-input.md),
selecting `ArduinoImolaHPH`/MultiMedia3 through discovery. Start only after the
worker/model is ready, announce `MICROPHONE_READY`, then invite the user to speak.
Allow a short, reported startup-settling interval before that cue. Trials are
explicit and finite, never an automatic background listener.

Read ordered samples with `latest=False`. The level meter's `latest=True` mode
intentionally discards old samples and must not be reused. Convert mono 48 kHz
S32_LE to normalized float32, resample continuously to 16 kHz with persistent
filter state, and flush once at the utterance boundary. Do not take every third
sample without an anti-alias filter. Include conversion/filter buffering in the
end-to-end timing and verify input/output sample counts.

Use WebRTC VAD on 20 ms, mono 16 kHz int16 blocks, with a fresh detector per
trial, aggressiveness 2, 300 ms pre-roll, at least 200 ms detected speech and
700 ms trailing nonspeech to close an utterance. These are initial experiment
settings, not proven microphone tuning. Bound each listening window to 15 seconds
and one utterance; silence ends as `no_speech`, and an overlong phrase is marked
truncated rather than silently counted as successful recognition.

For the user-requested matrix-guided retry, allow a 30-second listening window
inside a 40-second finite capture, with a 32-second worker buffer limit. Discard
the explicit pre-READY settling/countdown audio only. Prefer one prompted phrase
per invocation so the user can follow the physical cue rather than chat timing.
Do not treat the first mistimed live trials as recognition-quality evidence.

The runner keeps draining ordered capture while the worker endpoints, then
closes the microphone and waits for routing cleanup before asking the worker to
decode the bounded PCM buffer. Do not keep recording while a blocking decode
allows old microphone audio to pile up. Keep this same endpoint policy for
real-time-paced fixture replay and live input.

Record monotonic timestamps for capture start, ready cue, last VAD-positive
sample, endpoint decision, capture cleanup completion, decode start, first
output and final output. Distinguish:

- **Endpoint-to-final:** processing/cleanup time after the endpoint decision.
- **Estimated speech-end-to-final:** last VAD-positive audio time to final output,
  including silence wait, audio buffering, cleanup and decoding. VAD's last
  positive frame is an estimate, not independently measured human speech end.
- **Reference-end-to-final:** on real-time-paced fixed recordings, use annotated
  speech-end sample positions to measure the whole wait and assess endpoint
  errors. Use audio/sample clocks as well as arrival timestamps so queued PCM is
  not mistaken for live speech. Ground-truth endpoints must not control the VAD.

Fixed-window capture, if used for a diagnostic, reports capture-end-to-final
only. It cannot establish how long the user waited after actually stopping.
Whisper segment timestamps cannot independently validate that latency either.

After the fixed-clip sweep, choose the best measured thread count and try three
short prompted phrases, such as “Show the heart animation” or “Stop the current
animation.” They are transcription tests and must never execute board/agent
actions. The user can report misrecognitions; compare the prompted reference in
memory. Local microphone audio stays in memory, and microphone transcript text
is displayed but excluded from saved results by default. Save prompt IDs,
scores, signal/clipping statistics and timings; retaining microphone transcripts
requires an explicit run option. No voice recording is retained or uploaded.

## Resource limits and coexistence

Keep the initial project below 1 GiB and require at least 2 GiB free on the home
filesystem before setup. Reuse one environment/model/fixture pack. Retain at most
three completed metric/report directories with a 20 MiB total results budget.
Pin the fixed-file/replay baselines during live retries; remove only this
experiment's completed, unleased, unpinned older results. Stop and request export
if pinned data fills the budget. Preserve any run still in use. Remove its
scratch files after children exit; never prune
Torque releases, other projects, credentials or vendor caches as a side effect.

Bound a decode to 60 seconds and a sweep to 20 minutes. Capture has its separate
15-second limit. On timeout/Ctrl-C, stop only this experiment's workers, close
capture, await mixer restoration and release leases. A native call that cannot
abort promptly needs bounded termination of its own worker; capture cleanup
must not depend on that worker returning. Recheck cleanup on parent loss.

Record available CPU temperature/frequency, load, RAM and throttling information;
mark missing sensors unavailable. Avoid changing governors, scheduling policy or
system services. Compare baseline and under-load daemon status IPC latency using
the same persistent connection, and check device readiness before/after. Heart
Pulse continues on the MCU, so visible animation alone does not prove that the
Linux daemon remained responsive. No cloud-model turn is needed for this test.

## Delivery and decision

Implementation order: lock/check the private binary environment; validate model
and fixture provenance; run fixed clips; test endpointing with paced replay;
invite the user for the finite microphone trials; then write a journal report.
The user has requested this benchmark; the document-first step records the
method before implementation and execution.

Before live work, test scoring, resampling continuity, endpoint/no-speech/time
limits, worker termination, bounded output and capture cleanup with synthetic
inputs. Run the repository Python suite after adding Python code. The real-board
report must contain the exact runtime/model/fixture identities, raw measurements,
limitations and successful restoration of the microphone route and ownership.
Preserve MCU boot, service configuration, boot default and user settings.

Treat sub-one-second **total** post-speech delay as a usability target, not a
promised result. The initial 700 ms silence setting already consumes much of
that budget. Report honestly whether latency, recognition quality and coexistence
meet the intended use. If Tiny is too slow or inaccurate, use this same harness
and fixture set for the next candidate; do not merge an unmeasured recognizer
into Torque or call poor hardware results an implementation success.

## Sources

- [whisper.cpp](https://github.com/ggml-org/whisper.cpp): CPU backend, model formats and quantization.
- [Encoder-only benchmark boundary](https://github.com/ggml-org/whisper.cpp/tree/master/examples/bench).
- [Upstream model download source](https://github.com/ggml-org/whisper.cpp/blob/master/models/download-ggml-model.sh).
- [PyWhisperCpp API](https://absadiki.github.io/pywhispercpp/) and [published wheels](https://pypi.org/project/pywhispercpp/).
- [Python-SoXR streaming resampler](https://github.com/dofuuz/python-soxr).
- [WebRTC VAD Python wheels and frame requirements](https://github.com/daanzu/py-webrtcvad-wheels).
- [LibriSpeech provenance and CC BY 4.0 license](https://www.openslr.org/12/).
- [NXP's separate optimized pipeline measurements](https://www.nxp.com/design/design-center/software/embedded-software/speech-to-text:STT).
