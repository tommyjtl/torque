# Pulsing standby and Half Helix status

**Date:** 2026-10-25

**Status:** Activated; installed acceptance passed

**Later updates:** [Heart Pulse](2026-10-25-heart-pulse-idle.md) replaced the
center-dot breath. [Unattended Linux updates](2026-10-25-unattended-runtime-updates.md)
were enabled on 2026-10-26. The sudo requirements below describe this earlier rollout.

Normal idle status now has a centered dot breathing through native brightness
levels 1–3 over 3.2 seconds. Active work uses Half Helix at peak 5, with a 0.96
second loop. The gallery imports the shared Half Helix generator. All nine gallery
clips remain identical at every brightness (63 old/new frame comparisons), with
CRT Glide on key 3 and the same 25 ms default.

The coordinator uploads two resident clips once, then selects each with one
playback command. Foreground ownership and a new controller connection invalidate
the status cache, because the gallery can replace all nine slots. User-retained
scenes, maintenance and failed reset continue to suppress automatic status writes.
Waiting/error retain their static symbols.

Explicit Ctrl-C/reset still leaves playback stopped on a steady standby dot.
Normal animation resumes on the next session state change or `matrix_release`.
The reset implementation, CLI and packaging correction from the other session
were preserved. The coordinator now checks for the existing 0.4.0 / protocol 1.3
bundle required by resident status clips before rendering.

Validation: the final complete suite passed 250 tests with two skips. On the
UNO Q, all 24 model/control checks (including the installed-wheel terminal
frontend) and seven status tests passed. A separately installed wheel generated
all nine previews outside the checkout and matched all 14 application modules to
source.

A bounded foreground preview through the public Board SDK confirmed idle levels
1, 2 and 3 on the center dot, eight distinct Half Helix framebuffer samples, and
static waiting/error stopping playback. Uploading both clips and starting idle
took 1569.0 ms; cached switching took 32.3 ms. Firmware boot was unchanged,
ownership was released and the production steady standby dot was restored.
These are controller readback checks, not an optical observation. No firmware
has been flashed for this change.

The interrupt fix was rechecked against the board's active release:
`0.2.0-56a1a1ed2c76` → `0.2.0-f71b4f8765d6`. Preflight passed, the candidate's
12 installed application modules match source, and service/default preservation
checks passed. The user then activated it; `acceptance.json` reports success for
blank retention, steady standby and both MCU RGB outputs. Firmware boot remains
2126796425, with service and boot default unchanged. Administrator authentication
was still required at that milestone: the unattended runtime updater was a
proposed design and had not yet installed permission delegation.

See the [status design](../design-spec/2026-10-25-status-animations.md) and
[interrupt/package correction](2026-10-25-interrupt-reset-and-package-parity.md).

## Activation and installed acceptance

The user activated the Linux-only bundle with
`~/.cache/torque/apply-status-cues.sh`. Production now selects
`0.2.0-cf6387b00889`, based on the installed interrupt correction
`0.2.0-f71b4f8765d6`. The runtime's 14 application modules match their bundled
source. Automatic idle playback was sampled across all three brightness levels
on preset 1 with 32 frames. Blank/standby/RGB reset acceptance passed, and a
foreground draw followed by ownership release returned the display to idle
pulsing. The final state is idle with no foreground owner.

Firmware boot 2126796425, the Arduino boot default, systemd service configuration,
conversation and permission mode were preserved. No inference requests were
needed. Receipts are under `~/.cache/torque/status-cues-ex3r9rqu/`:
`stage/applied.json`, `acceptance.json`, `reset-acceptance.json` and
`live-preview.json`. At that rollout, unattended sudo delegation was not yet enabled.
