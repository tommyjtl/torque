# Animated session status

**Date:** 2026-10-25

**Status:** Heart Pulse revision activated and verified on UNO Q

Use Heart Pulse for normal standby and Half Helix for active
work. These are low-priority session cues on the UNO Q's MCU-controlled 8 × 13
matrix. Rendering and selection belong to the Linux coordinator; the existing
0.4.0 controller plays the buffered frames. No firmware change is required.

| State | Display | Timing and brightness |
| --- | --- | --- |
| Standby | Heart Pulse: centered circular 5 × 5 glow with two beats | 28 frames at 50 ms; peak 5; 1.4 s loop |
| Working | The gallery's Half Helix in the existing centered 5 × 5 region | 24 frames at 40 ms; peak 5; 0.96 s loop |
| Waiting for approval | Existing static exclamation mark | Unchanged |
| Error | Existing static cross | Unchanged |

The idle revision replaces the original 3.2 s center-dot breath. Heart Pulse
references the circular `dotm-circular-8` entry from the
[animation review](2026-10-24-animation-reference-review.md), with its
[reviewed motion source](https://github.com/zzzzshawn/matrix/blob/e30b80a9c5e6fe388ecbbbac15abfd14f24d0dd3/loaders/loaders/dotm-circular-8.tsx).
It is a circular brightness pulse, with a strong first beat, a weaker second beat
and a quiet tail. Use an original raised-cosine envelope on 21 active dots;
leave the four 5 × 5 corners dark. Keep the shell visible at level 1 even in the
quiet phase. The center is brighter than the inner and outer tiers.

The gallery keeps its nine keypad presets, numbering and 25 ms default. Share
the pure Half Helix and Heart Pulse generators with the example. Heart Pulse
is available by `--animation heart-pulse` and in the ten offline SVG previews;
it has no key binding and is excluded from the default nine-preset live gallery.
This preserves single-command switching within the MCU's nine-slot capacity.
Use `--peak 5 --frame-ms 50` to match idle timing in the example. Brightness
uses the controller's native 3-bit levels, not Linux frame streaming or
time-based approximation in the client.

## Ownership and cache lifecycle

Keep the coordinator's existing ownership gates. Maintenance, failed reset,
retained user scenes and foreground device programs prevent all status writes.
Changing session state must never reclaim an owned display. An explicit
`matrix_release` or program release returns control to session cues.

Use resident slots 1 and 2 for standby and working. Upload both clips once when
animated status is first needed, then switch with a single `play_cached` command,
repeating indefinitely. Waiting/error draw their binary frames and stop playback.
Do not upload or restart a clip on every telemetry tick.

The gallery uses all nine slots. Invalidate the status cache when a program
acquires the device and whenever the coordinator obtains a new Board connection.
After ownership returns, upload the status pair again before selecting it. Do not
reserve slots from user programs or assume their cached contents survived.
Static draws, reset and retained scenes preserve resident slots.

## Explicit reset

Preserve the separately implemented Ctrl-C/reset contract: cancel managed work,
stop playback, restore the steady binary standby dot (or retained blank with
`--blank`), turn MCU RGB LEDs off and verify readback. Reset leaves playback
stopped. Normal pulsing resumes at the next status transition or explicit
`matrix_release`. Do not restart an animation merely because a successful reset
finished. Failed reset continues to block automatic repainting.

## Verification and rollout

Test pulse bounds, circular mask and double-beat cadence, shared frame output,
unchanged key bindings and nine-slot preload, cache reuse, transitions
to static warning/error, foreground cache replacement, reconnect, retained scenes,
maintenance and reset failures. Run the complete Python suite and validate the
installed wheel outside the checkout, including offline gallery previews and
installed/source parity.

Activate as a Linux-only runtime update preserving the installed Ctrl-C/package-parity
correction. Preserve firmware identity/boot, Arduino app/default and service
configuration. Check playback status, selected preset and changing firmware
framebuffer values; report these as software readback, separately from a person's
observation of the LEDs. The [unattended updater](2026-10-25-unattended-runtime-updates.md)
is enabled and verified on the validation board: subsequent authorized Linux
animation changes use `torque update` over SSH without another password entry.
Only an unconfigured board needs the administrator bootstrap.
