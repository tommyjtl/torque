# Local Media Carrier microphone API

Audio belongs to Linux/ALSA; matrix output belongs to the MCU. No new sketch or
Arduino app is needed. The supported source in this version is UNO Q's analog
Media Carrier MIC-IN route, not a generic USB/Bluetooth/default microphone.

```python
from torque.audio import Microphone, audio_capabilities

capabilities = audio_capabilities()  # Endpoint/access metadata; no capture.
with Microphone(seconds=10) as microphone:
    while True:
        chunk = microphone.read()
        if chunk is None:
            break
        level = chunk.rms
```

Construction does not capture. `start()` or context entry does. `close()` stops
and waits for routing cleanup; context exit calls it. `seconds` is an integer
1..300 (default 60). Use the user's duration with a bounded run loop; the example
is 30 seconds by default. `card=` optionally selects a discovered card ID, not a
changing numeric ALSA index.

`read(frames=2400, timeout=2, latest=False)` returns an `AudioChunk`, or None at finite stream
completion. Frames are 1..48000; timeout is in (0,5] seconds. A timeout raises
`TimeoutError` and retains partial input. For a responsive meter/UI,
`read(frames=1200, latest=True)` uses 25 ms windows and discards queued older
complete samples. The default preserves every sample in order. Chunks contain `.pcm` bytes, `.frames`,
`.sample_rate` (48000), `.channels` (1), `.format` (`S32_LE`), `.rms`, `.peak` and
`.dbfs`. Digital levels are uncalibrated and do not measure sound-pressure level.
No file or network operation is part of this capture API. PCM is omitted from
the object's repr; do not log it or save recordings unless requested.

`available` in discovery means an accessible supported endpoint/tools exist.
It does not establish a connected microphone, a free device, a configured route
or audible signal. Stop and report `MicrophoneBusy`; do not stop another consumer
or change access/groups/global defaults. `MicrophoneUnavailable` and `AudioError`
report missing support, routing/capture failures or incomplete cleanup.

A separate helper owns a per-account card lease, finite `arecord` process and
temporary mixer changes. Parent/control-pipe loss triggers cleanup, and inherited
release/program leases fence runtime updates until that cleanup finishes. Controls
are restored to their exact previous values when still owned; concurrent changes
are reported rather than overwritten. Killing the helper itself or losing power
cannot guarantee mixer restoration. Keep the microphone in a context manager
and handle SIGTERM/Ctrl-C through normal exception/finally cleanup.

The packaged example is `torque example microphone-level-meter`. It shows recent
RMS level history, not frequency bands or recognized words. `--list` and preview
mode never record. A silent/flat level meter needs a microphone/connector/routing
check; enumeration alone is not a successful microphone test.
