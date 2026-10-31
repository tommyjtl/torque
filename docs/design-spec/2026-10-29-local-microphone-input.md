# Local microphone input and a matrix level meter

**Date:** 2026-10-29, America/Los_Angeles

**Status:** Implemented and deployed in `0.2.0-6d9abc9bfb75`. Host/ARM64 suites,
finite PCM capture, exact routing restoration and installed CLI interrupt cleanup
passed. The user confirmed the initial example works. The faster refresh revision
measured 12.51 successful draws/second versus 8.75 in its four-second baseline.

The microphone is a Linux/ALSA peripheral on the UNO Media Carrier. The first
source profile is UNO Q's `ArduinoImolaHPH` MIC-IN/MultiMedia3 route, using the
published codec routing and mono 48 kHz S32_LE capture. Digital capture gain is
0 dB (TX_DEC0 value 84); the guide's +16 dB value clipped during the first probe.
No new MCU firmware,
Arduino app start/stop, service setting, boot change or OS package is required
on this validation board: `arecord` and `amixer` already exist and are accessible.
Other machines report missing dependencies/access instead of changing them.

## Public API and scope

- `torque.audio.audio_capabilities(card=None)` reports supported capture endpoints
  and access without starting PCM, acquiring a lease or changing controls.
  `available` is not a plugged-microphone or audible-signal claim.
- `Microphone(card=None, seconds=60)` does not record during construction.
  `start()` or context entry opens finite capture; `close()` waits for cleanup.
  Duration is an integer 1..300 seconds. Card selectors use discovered ALSA IDs.
- `read(frames=2400, timeout=2, latest=False)` returns an `AudioChunk`, with None
  at completion and `TimeoutError` for a stalled read. Partial records survive a
  timeout. `latest=True` drains a bounded amount of queued data and selects the
  newest complete window for latency-sensitive UIs; ordered reads remain default.
- Chunks expose PCM bytes, format/rate/channels, frame count, RMS, peak and dBFS.
  Levels describe digital amplitude and are not calibrated sound-pressure data.
- `MicrophoneBusy`, `MicrophoneUnavailable` and `AudioError` distinguish ownership,
  missing endpoint/access and capture/cleanup failures.

The first implementation uses Python's standard library and the installed ALSA
tools. Arduino's microphone API is a reference, not an added dependency on its
entire App Bricks package. USB/Bluetooth sources, arbitrary device defaults,
WAV-file recording, ASR, wake words and model uploads are outside this first scope.

## Capture ownership and restoration

An isolated helper process owns a private per-account card lease, temporary
mixer state and an `arecord` child. Its stdin is a lifetime/control pipe from
the client; EOF on normal close or parent death ends capture. The helper is in
its own process group so terminating a managed program leaves it time to clean up.
It inherits runtime/program leases so updates remain fenced until cleanup ends.

Before writes, refuse an already open capture on the card, read all required
controls and validate all routing choices. Save exact values before mutation,
including writes whose acknowledgements might fail. Verify setup readback.
On stop/error, stop/reap `arecord`, then restore changed controls in reverse
order with readback. Preserve a value that another consumer changed and report
incomplete restoration. Advisory leases do not exclude unrelated ALSA clients.

PCM streams through pipes only. Bounded buffering and a stalled-consumer deadline
stop capture if the client stops reading. Finite duration bounds a live helper.
SIGINT/SIGTERM, partial setup failure, no source, busy device, fragmented PCM,
normal EOF and parent SIGKILL require tests. Killing the helper itself or losing
power cannot guarantee mixer restoration; no stronger crash-recovery claim is made.

## Example and agent use

`torque example microphone-level-meter` starts a 30-second local level-history
display on the existing matrix. Each column represents recent RMS amplitude,
not a frequency band. The revised example targets 15 matrix updates per second,
analyzes 25 ms windows and reports terminal levels at 5 Hz. The ALSA period is
25 ms with a 100 ms buffer; the helper uses a 10 ms pipe polling timeout.
Actual matrix cadence depends on synchronous controller RPC latency.
The example opens capture before acquiring the matrix and clears/releases it
on exit. It saves no audio and makes no network requests.

`--list` and offline preview consume no audio or MCU output. `--console-only`
is the first hardware probe. `--seconds`, `--fps`, `--floor-dbfs` and optional
`--card` keep ordinary tuning inside the example's parser and manifest catalog.
Preview data is labelled synthetic; a finite silent capture is not a signal pass.

The agent's `audio_capabilities` tool is a strict read-only metadata operation.
The input skill documents the SDK. Discovery alone does not establish user intent
to record, persist audio or send it to a provider. Requested programs use the
normal project/run authorization; no new automatic background listener is added.

## Acceptance

1. Host tests and the full required Python suite; skill/worker syntax validation.
2. Matching installed ARM64 package tests and source parity.
3. Read-only capture inventory and existing Arduino app/controller check.
4. Bounded local console capture with exact before/after mixer equality and
   capture-process/lease release. No audio file is retained.
5. Installed example with user-supplied quiet/speech/clap input, measured level
   changes and MCU frame readback. The person's visual observation is separate.
6. Ctrl-C/termination cleanup and normal status cue restored without new firmware.

Deploy through the reviewed normal-account application updater. Preserve unrelated
display/shield research edits, service configuration, boot default, firmware boot
and user settings. Record the final transaction/release and limitations in the
[microphone journal](../journal/2026-10-29-microphone-input-investigation.md).

The next proposed experiment is an
[isolated Whisper tiny.en benchmark](2026-10-29-isolated-whisper-tiny-benchmark.md).
It uses the installed capture API from a separate project and private recognition
environment; speech recognition is not part of the deployed microphone SDK.
