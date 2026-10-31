# Microphone Level Meter

A finite local microphone meter for the UNO Media Carrier. The matrix shows
the most recent 13 digital level measurements as columns; these are amplitude
history, not frequency bands. This example writes no audio files and makes no
network uploads. It uses the existing grayscale controller without a new sketch.

```bash
torque example microphone-level-meter
torque example microphone-level-meter --seconds 15
torque example microphone-level-meter --console-only
torque example microphone-level-meter --list
torque example --mode preview microphone-level-meter
```

The default live duration is 30 seconds. Once `MICROPHONE_READY` appears, speak
or clap near the microphone. Each column is 0..8 pixels high, with digital level
and peak reports in the terminal. Ctrl-C stops early. The matrix is requested
blank on exit, then normal Torque status display resumes when ownership is
released. No optical observation is inferred from a successful command.

`--floor-dbfs -50` changes the display floor; it does not change hardware gain.
The default is -60 dBFS. The matrix now targets **15 updates per second**;
`--fps 10` can lower that limit (allowed 1..15). Audio analysis uses 25 ms windows,
and terminal reports update five times per second. The meter uses the newest
available audio window so a slow display call does not leave it replaying old levels.
`--seconds` accepts 1..120. `--card` can select the stable ID returned by
discovery. This version supports the carrier jack, not arbitrary default sources.

The microphone must use the combined MIC-IN / Headphones Out connector and
compatible headset wiring. A generic three-contact microphone plug may need a
matching adapter. The example reports endpoints/access with `--list`, but only
a deliberate capture establishes a microphone signal. Check microphone mute,
connector wiring and routing if levels remain flat.

The SDK API is `from torque.audio import Microphone, audio_capabilities`.
It uses the already installed `alsa-utils` tools on Linux, with mono 48 kHz
S32_LE chunks. A private helper owns finite capture and temporary codec routing/gain;
digital gain starts at 0 dB to retain voice headroom. It restores previous mixer
values, including after its parent exits. Another active capture is a busy
error; it is not stopped. Cleanup reports concurrent mixer changes rather than
overwrite them. Killing the helper itself or losing power cannot guarantee
restoration. No permissions, services, pairing or boot settings are changed.

Offline source preview, from the repository root:

```bash
PYTHONPATH=packages/session/src:packages/device/src python3 examples/07-microphone-level-meter/main.py
```

This writes a labelled synthetic SVG under `projects/microphone-level-meter/`
without opening either input or the MCU. Add `--live` only for requested playback
and capture. See the [command reference](../../docs/cli.md).
