# Shared keypad discovery in Dot Matrix Animations

**Date:** 2026-10-26

**Status:** Deployed; software and lease checks passed. The user confirmed that
keys 1, 3 and 9 switched correctly and felt responsive.

During first-commit preparation, the user chose Apache 2.0 and requested removal
of personal Bluetooth addresses. Review found the shared `Keypad(address=None)`
API already supported single-device discovery, explicit disambiguation and
project leases. The developer capture logger had a pilot address default, and
the animation gallery still used a separate first-match evdev implementation.

The logger now requires an explicit `--address`; public capture history uses
role placeholders and tests use synthetic identities. Captures remain private
workspace output. The license/publication preparation has not committed or
pushed the repository.

The user then authorized moving the gallery to the shared input API and testing
on UNO Q. A thin adapter translates shared `KeyEvent` press events into presets;
repeat/release/resync markers do not select an animation. Shared discovery,
descriptor verification, startup-held suppression, state resync, disconnect
cleanup and advisory leases replace the duplicate implementation.

The default still selects one readable verified Keychron. Several matches require
`--keyboard-address`; an unavailable explicit target or a busy lease fails before
matrix acquisition. Automatic mode with no target/device retains finite gallery
fallback. Escape exits and disconnect falls back to the finite gallery. Native
number-row digit names `1`–`9` were added to the shared event map to preserve
the gallery's existing number-row/numpad behavior.

Keys 1–9, the ten renderers, Heart Pulse's name-only availability, 25 ms gallery
timing and cached single-command switching are preserved. No input selection
contains a personal address, and no device preference file is required. A future
saved preference belongs outside Git; no new preference loader is implemented.

This is a Linux application/example update on the existing 0.4.0 controller.
No Arduino app start/stop, firmware flash, pairing, permission/group change,
exclusive OS grab or raw keystroke capture is part of this test.

## Verification and deployment

- Host: 299 Python tests passed, with two optional native Bridge integrations
  skipped. The ARM64 board passed the same 299-test suite, with four optional
  integrations/compiler checks skipped. A legacy updater test fixture now isolates
  the board's bootstrap marker; the production guard against using that legacy
  updater on an enabled layout remains unchanged.
- The application wheel and source distribution built successfully. All ten clips
  at seven peak levels matched the pre-refactor frame sequences exactly: 70 full
  comparisons. All nine key assignments are unchanged.
- Installed-source parity matched all 16 application modules. On the actual
  keypad, opening a second shared reader raised `KeypadBusy`; closing the first
  allowed a new reader to open. Discovery selected one verified readable keyboard
  without an address argument. These are software/device-access checks, not
  evidence of a person's keypress or optical observation.
- Normal unattended SSH activation committed transaction
  `33778ddf099b47098fa97d5d5d8b655a`, installing
  `0.2.0-58ff3c5d6158`. No additional administrator entry was needed. Firmware
  0.4.0 boot ID `1203245458`, boot default and service configuration were preserved.
  The reviewed overlay excluded unrelated license/storage work in the checkout.

A bounded live gallery trial started through
`torque example dot-matrix-animations --input keyboard`. It preloaded the nine
presets, but no selection arrived before the three-minute deadline. The fresh
trial likewise ended with no selection in its action log. Cleanup released matrix
ownership, restored Heart Pulse and allowed the shared keypad lease to reopen.
The user subsequently confirmed that 1 → 3 → 9 showed the expected animations
and felt responsive. This is the person's observation; the timed trial logs do
not independently corroborate those physical keypresses or measure their latency.

A separate automated terminal-input trial exercised the installed managed CLI:
keys 1, 3 and 9 produced MCU status for cached slots 1/3/9 with 24/30/24 frames,
three-bit brightness and active playback. Escape exited successfully, released
ownership and restored status display without changing the firmware boot.
Terminal writes reached the corresponding daemon-cached MCU status in 59–62 ms.
That measures this software/readback path, not physical key-to-light latency;
the terminal trial did not exercise evdev or optically measure the LEDs.

Receipts, test logs and gallery action summaries are in the board's private
`~/.cache/torque/shared-keypad-du09mqb7/` directory. No raw key stream or personal
Bluetooth address is included in this journal. Post-deployment acceptance notes
are maintained here in source; they do not require another runtime restart.

See the
[input design](../design-spec/2026-10-25-keypad-project-input.md) and
[example guide](../../examples/06-dot-matrix-animations/README.md).
