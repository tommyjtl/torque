# Media Carrier microphone input investigation

**Date:** 2026-10-29, America/Los_Angeles

**Status:** SDK/example deployed; PCM capture/restoration and Ctrl-C acceptance
passed. The user ran the installed example and confirmed it works, supplying
live level reports. The initial inspection below
was read-only; subsequent finite captures were explicitly authorized. No MCU
flash was performed.

The user reports receiving and attaching the Media Carrier and connecting a
microphone to its MIC-IN jack. The exact microphone model/plug is not confirmed.
The BOM mentions a teenage engineering M-1 and a separate microphone candidate;
neither is assumed to be the connected device solely from that history.

## Current support boundary

Torque has no microphone/audio capture API or audio example. Its current Sound
Bars animation is synthetic. The shared project input API handles the Keychron,
and the public Board API controls the MCU matrix/RGB and observes telemetry.

The carrier's headset microphone uses the Qualcomm/Linux audio path. Arduino
documents ALSA capture through the combined MIC-IN / Headphones Out jack, with
codec routing set through mixer controls. This is a Linux SDK/input addition;
no new MCU firmware is needed to capture audio. Matrix visualization can continue
through the existing public `from torque import Board, Frame` API.

## Actual board observations

- Kernel remains `7.0.0-g122c2c22d838` and `torque.service` is active.
- ALSA card ID is `ArduinoImolaHPH`, description `Arduino-Imola-HPH-LOUT`.
  Capture endpoints MultiMedia1–4 exist; Arduino's carrier guide identifies
  device 2 / MultiMedia3 for this microphone route. Card index 0 is the current
  observation, not a portable selector to embed in the SDK.
- `arecord`, `aplay`, `amixer`, `alsaucm` and `wpctl` are installed.
- The normal `arduino` account has read/write access to the sound control and
  capture nodes. Torque's service has `PrivateDevices=no` and `DevicePolicy=auto`.
  Access metadata is not a successful capture test or proof that the device is idle.
- All nine routing/gain controls in Arduino's recording guide exist, including
  ADC2 routing, MultiMedia3's capture mixer and TX_DEC0 controls. Their values
  were not changed.
- Read-only `Mic Jack` and `Headphone Jack` control values both report `off`.
  This is a detail to investigate, not proof that the user's physical plug is
  absent: the signal route, codec detection and connector compatibility still
  require validation.

The inventory commands (`arecord -l`, `aplay -l`, mixer-control listing and jack
control reads) did not open a PCM capture stream. No microphone samples were
read, saved or sent to a model/provider.

## Proposed first scope for discussion

1. Validate the actual microphone/plug and MIC-IN route with a deliberately
   bounded local signal test before committing to a backend abstraction.
2. Add a project-facing `torque.audio` module, with proposed `audio_capabilities()`
   and `Microphone` entry points. These names are a proposal, not installed APIs.
3. Capability discovery reports metadata and readiness limitations without
   opening a recording stream. Opening capture is a separate explicit action.
4. Define source selection, bounded PCM chunks, sample format/rate, start/stop,
   device-busy errors and cleanup. Discover the intended card/profile rather than
   choose a changing default that might select another microphone.
5. Coordinate capture ownership and restore the mixer values the program changed.
   Handle partial setup failure and Ctrl-C without killing another audio consumer
   or replacing global audio defaults. Hard process termination and concurrent
   mixer changes need an explicit lifecycle design before claiming restoration.
6. First example: a finite live sound-level meter on the LED matrix, using real
   microphone energy. It should process audio locally in memory and avoid saving
   recordings by default. Speech recognition, wake words and sending spoken
   commands to the agent are later, separate features.

Arduino already supplies an ALSA-backed `Microphone` peripheral with streaming
chunks and level/pause helpers. Evaluate reusing that backend against a smaller
ALSA adapter for Torque. Its current package declares Python >=3.13 and microphone
extras including pyalsaaudio and NumPy; adding the entire package should be a
deliberate dependency decision. Arduino's standalone ALSA recipe is also a
published reference for the required codec path, but its cleanup commands are not
a substitute for restoring arbitrary pre-existing mixer values.

The user accepted this scope and authorized proceeding with the example. See the
[implementation design](../design-spec/2026-10-29-local-microphone-input.md).
The SDK uses the installed ALSA tools with no added Python audio dependencies;
a private helper owns capture/routing and handles parent loss. The manifest adds
`microphone-level-meter` automatically to the example catalog. Read-only agent
discovery and the input skill document this new source. No speech-recognition,
saved-recording or provider-upload feature is added.

## Software and installed acceptance

- Host: 321 Python tests passed (two optional native integrations skipped).
  ARM64: 321 tests passed (four optional integrations/compiler checks skipped).
  Tests include metadata-only discovery, exact mixer rollback, contention,
  concurrent changes, partial PCM/timeouts, normal EOF, actual parent-SIGKILL
  supervision with synthetic input, and measured levels reaching matrix frames.
- Wheel and source distribution built. Skill validation and worker JS syntax
  checks passed. Installed-source parity matched 18 application modules, and
  `microphone-level-meter` is present in the packaged example catalog.
- Two authorized three-second local capture probes each returned 60 PCM chunks;
  the first also recorded 144,000 frames. Each restored every touched mixer value exactly, closed the
  capture endpoint and released its input lease. No raw audio was retained.
- The first probe used the guide's TX_DEC0 value 100 (+16 dB) and clipped.
  The deployed profile uses value 84 (0 dB). The raw startup probes still contain
  a peak of 1.0 and DC/transient energy; these figures are not a clean-voice or
  user-supplied-sound acceptance claim. The live level test remains important.
- The installed CLI example was interrupted after reaching capture readiness.
  It exited 130; the microphone route was restored, PCM closed and lease free.
  This also exercised the helper's separate lifetime during CLI interruption.
- Normal-account update transaction `f73ce654833e4ff7b527e654c0a959df`
  committed application release `0.2.0-943bf9ad137f`. No sudo prompt was needed.
  Firmware 0.4.0/protocol 1.3 boot ID `1295313560`, boot default and service
  configuration were preserved. Unrelated display/shield research was excluded
  from the frozen application source.

Private receipts and level-only logs are under
`~/.cache/torque/microphone-yjhp2e3y/`. The initial higher-gain candidate
`0.2.0-b04768a8a57f` was prepared/tested but never activated. Post-deployment
acceptance notes are maintained in this source journal without another restart.
The user subsequently ran `torque example microphone-level-meter` and reported
that it works. Their supplied terminal output shows changing heights 6–8 and
varying digital levels/peaks. This is user acceptance of the live example, not
an optical measurement or calibrated microphone-quality claim.

## Faster refresh follow-up

The user requested faster detection/updates. A four-second baseline on the real
board measured 8.75 matrix draws/second at the original 10 Hz target, with a
42.7 ms median / 64.7 ms maximum synchronous draw RPC in that run. Terminal
reports were separately throttled to 2 Hz.

The revision targets 15 Hz drawing, 25 ms analysis windows and 5 Hz terminal
reports. ALSA period/buffer sizes halve to 1200/4800 frames; helper pipe waits
reduce to 10 ms. An explicit `latest=True` read mode prevents the meter from
replaying queued older audio during slow display calls; ordinary SDK reads
continue preserving samples.

The revised four-second real-board test completed 51 draws, measuring 12.51
successful draws/second; median draw RPC remained 42.7 ms. Routing restored
exactly, capture closed, matrix ownership released, status display resumed and
the firmware boot was unchanged. This measures acknowledged draw cadence, not
an optical frame-rate or physical sound-to-light latency measurement.

Host and ARM64 suites passed 322 tests (two/four optional checks skipped).
Transaction `1bf840e98dee46c8b2cdb01d2022c60a` committed release
`0.2.0-6d9abc9bfb75`, preserving firmware boot, service configuration and boot
default. Installed source parity matched 18 modules and example help confirms
the 15 FPS default. Receipts are `prepared-speed.json`, `applied-speed.json`,
`speed-baseline.json` and `speed-benchmark.json` in the private directory above.

## Primary references

- [Media Carrier audio recording and routing](https://github.com/arduino/docs-content/blob/main/content/hardware/uno/carriers/uno-media-carrier/tutorials/01.user-manual/content.md#audio)
- [Arduino microphone peripheral](https://github.com/arduino/app-bricks-py/tree/main/src/arduino/app_peripherals/microphone)
- [Arduino microphone usage](https://github.com/arduino/app-bricks-py/blob/main/src/arduino/app_peripherals/microphone/README.md)
- [Arduino App Bricks dependencies](https://github.com/arduino/app-bricks-py/blob/main/pyproject.toml)
