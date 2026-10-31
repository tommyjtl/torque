# CPU Zipformer next steps

**Status:** CPU runtime and live prototype are preserved; GPU retirement is
complete. Initial live trials were responsive but had connected-speech errors.
Recognition quality and whole-turn handling remain open acceptance items.

**Decision:** Adopt CPU streaming Zipformer for the next local English speech
prototype. Close the tested GPU speech path for latency: GPU recognition was
correct, but its median file-end-to-final delay was 6.457 s (0/18 under one
second), versus CPU 0.387 s (18/18). Both had 4/136 word errors. This is a
performance failure for our requirement, not a failure to execute on the GPU.

## Preserve a small CPU baseline

Retain the exact tested native executable, the seven pinned model assets and
six hashed fixtures in `projects/zipformer-cpu/` on the UNO Q. Keep provenance
and CPU benchmark evidence. The launcher must always pass the CPU execution
mode and disable diagnostic profiling. Preserve the existing binary rather than
introducing a different model/build during cleanup; its optional compiled GPU
backend is unused. Do not remove system graphics drivers or other applications.

Archive the old ncnn GPU experiment's source, measurements, logs and receipts on
the Mac before removing the board's old experiment directory, build toolchain,
probe executable, shader cache and intermediate objects. Refuse active process,
container or runtime references. Under the deployment/program locks, copy and
hash-check the CPU runtime/assets first, then verify a finite known-file CPU run
before deleting the old directory. Preserve service configuration, user settings,
firmware boot/default and unrelated projects. This is not a runtime update and
requires no administrator grant or firmware upload.

## First live prototype

Preload the model before announcing readiness. Use the existing Torque microphone
capability/discovery API and accessible Media Carrier input; do not hardcode a
numeric ALSA card index. Capture ordered 48 kHz S32_LE samples and resample with
a stateful 16 kHz converter. Keep capture draining separately from inference,
bound queued audio and abort visibly if it falls behind instead of dropping it.

Start with push-to-talk or an explicit send action. The fast 0.3-second endpoint
emitted five and three segments in the two longest test clips; a segment ending
does not establish that a person finished their whole turn. Display/aggregate
segments without automatically executing recognized text as board commands.

Use the matrix for 3–2–1, a readiness cue, processing and completion, then release
ownership to normal status on every exit path. Wait for the person's readiness
before live trials. Keep audio in memory and announce capture. Test one short
English phrase at a time, with no decoder prompt containing the expected answer.

Record key-release-to-stable-final, the audio-clock/VAD estimate, queue lag,
capture cleanup, accuracy, CPU/RSS and status responsiveness separately. Actual
human speech-end latency needs an independent annotation; the recorded-clip
file-end metric is a proxy. Verify microphone routing is restored and all workers
and leases are released. Only after this acceptance should a production speech
API or broader Torque agent integration be proposed.

See the [benchmark and retirement record](../journal/2026-10-30-ncnn-streaming-speech-benchmark.md).
