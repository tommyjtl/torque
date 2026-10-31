# Moonshine Tiny Streaming follow-up

**Date:** 2026-10-29, America/Los_Angeles

**Status:** Implemented; CPU screening completed. All tested configurations
missed the one-second target. GPU inventory is available; GPU inference is not
yet benchmarked. See the [results journal](../journal/2026-10-29-moonshine-streaming-and-gpu-inventory.md).

The user wants a stable final transcript less than one second after speaking.
The [Whisper experiment](../journal/2026-10-29-whisper-tiny-on-device-benchmark.md)
took about five seconds to decode a completed short utterance. Test Moonshine's
**Tiny Streaming English** architecture, not the older non-streaming Tiny model.

Use a separate `projects/moonshine-tiny-benchmark/` directory and private venv
on the UNO Q home filesystem. Start with the published CPU-only
`moonshine-voice==0.1.5` aarch64 wheel. Select `ModelArch.TINY_STREAMING` (2)
explicitly; English's library default is a larger model. Freeze the native
download manifest, file hashes and exact dependency wheel hashes. Timed runs
use local assets, without automatic downloads, speaker identification, text
logging, saved audio or transcript PCM returns. Keep Torque, its release,
firmware, service and boot default unchanged.

Use the same six hashed English clips and WER normalization as Whisper. First
run one compatibility sample, then feed all clips in real-time-paced chunks,
with an initial warm screening pass and three repetitions only if a configuration
is promising at the target. Measure CPU time, resident memory, add-audio call
duration/backlog, first partial text, natural completed-line callbacks and
recognition accuracy. Report cold process/import/model startup separately.
Do not infer a configurable thread count: use only options actually exposed by
the installed library and record native defaults plus measured CPU use.

The important acceptance measure is last-speech-sample to **natural final** text,
including buffering and speech-end detection. The corpus files have no independent
human speech-end annotations, so report file-end and detector-end proxies with
that limitation. Append paced silence to permit natural endpointing; do not call
`stop()` at a known reference boundary to manufacture a low-latency completion.
Tag any completion caused by `stop()` as forced and exclude it from the latency
claim. Preserve partial/final distinction and account for multiple lines within
an utterance. Test both the default configuration and a separately labelled
shorter endpoint window only if the default does not meet the target. Do not
supply reference words or phrase hints to the model.

For microphone trials, retain the public Torque capture API and matrix-guided
single-phrase pacing requested by the user: 3-2-1, speak circle, working dots,
completion check. Recheck the user's readiness before opening capture. The
earlier live-input failure remains unresolved; a model change does not establish
microphone signal quality. Use finite capture and preserve ordered samples.
Drain capture independently of potentially blocking inference into a bounded
queue. Abort and report backlog rather than drop audio while claiming real time.
Normalize 48 kHz S32_LE and apply the tested streaming resampler, including its
buffering in the latency budget. Store aggregate signal metrics, not PCM or
microphone transcript text. Recognized speech must not execute actions.

Bound each decode/request and experiment; stop/reap only its own workers and
restore the microphone/matrix through existing ownership cleanup. Preserve the
Whisper baseline directories. Store all phases of this experiment in a single
timestamped result bundle, with copied small harness sources and manifests, so
retries cannot prune an earlier phase. Keep the project below 1 GiB and results
below 20 MiB, with no broad cache cleanup. Run software tests and an installed
CPU smoke check before inviting live speech. Record failures as failures; a
fast partial transcript or forced completion is not sub-one-second final text.

Sources: [models](https://moonshine-voice.readthedocs.io/en/latest/models/available-models/),
[custom audio and events](https://moonshine-voice.readthedocs.io/en/latest/using/transcription/),
[native options](https://moonshine-voice.readthedocs.io/en/latest/api/options/),
[downloads](https://moonshine-voice.readthedocs.io/en/latest/using/downloading-models/).
