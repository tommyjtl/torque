# Heart Pulse for idle status

**Date:** 2026-10-25

**Status:** Activated; installed acceptance passed

**2026-10-26 follow-up:** The [unattended updater](2026-10-25-unattended-runtime-updates.md)
is now enabled. The administrator commands below are historical rollout evidence;
use [current CLI instructions](../cli.md#unattended-linux-runtime-updates) for
subsequent authorized Linux changes.

The user chose Heart Pulse to replace the center-dot idle breath, and requested
the same animation in the example without assigning a number key. The
[animation review](../design-spec/2026-10-24-animation-reference-review.md) identifies
the reference as circular `dotm-circular-8`. Its
[reviewed source](https://github.com/zzzzshawn/matrix/blob/e30b80a9c5e6fe388ecbbbac15abfd14f24d0dd3/loaders/loaders/dotm-circular-8.tsx)
uses a double-beat circular brightness field. This is a glowing round mask,
rather than a heart-shaped glyph.

The original hardware adaptation uses 28 native 3-bit frames, a strong first
beat, a weaker second beat, and a quiet tail. Twenty-one dots occupy the centered
5 × 5 region at (4,1), with four dark corners and a dim, visible shell. Idle runs
at peak 5 and 50 ms per frame: 1.4 seconds per loop. Working still uses Half Helix
at peak 5 and 40 ms per frame. Static waiting/error and explicit reset behavior
are preserved.

The example imports the shared Heart Pulse generator. `--animation heart-pulse`
selects it; `--peak 5 --frame-ms 50` matches idle. Offline preview writes ten SVGs.
The default live gallery, Keychron mapping and terminal number keys remain the
same nine presets, fitting the MCU's nine resident slots without slowing key
switches. Heart Pulse has no number-key binding. All nine old clips are byte-for-
byte unchanged at peaks 1–7 (63 comparisons).

The complete host suite passed 251 tests with two skips. Tests cover the circular
mask, brightness bounds, relative beat strengths, quiet tail, shared generator,
CLI selection, key exclusion, nine-slot preload, ownership and reset behavior.
The wheel and sdist have been rebuilt. On UNO Q, 54 software checks passed:
24 model/control checks, seven status checks and 23 animation/input checks. The
installed wheel matches all 14 application modules, exposes Heart Pulse in help,
generates ten default previews and produces a 1.4 s preview with idle arguments.

The Linux-only bundle `0.2.0-7b6b751f2f9c` is staged against the active
`0.2.0-cf6387b00889` release. Preflight passed with firmware boot 2126796425,
the existing service unit and Arduino boot default. Activation via
`~/.cache/torque/apply-heart-pulse.sh` requires private sudo authentication;
`sudo -n` reported that a password is required. Staging and receipts are under
`~/.cache/torque/heart-pulse-wx6q5wwu/`. No MCU flash is involved.

See the updated [status design](../design-spec/2026-10-25-status-animations.md).

## Activation and live readback

The user ran the activation script. Production selects `0.2.0-7b6b751f2f9c` and
the service is ready, idle and unowned, with preset 1 playing 28 grayscale
frames. Installed/source parity matches all 14 application modules.

Automatic idle acceptance sampled all 28 frame indices and six distinct
framebuffers. Every sample matched its generated Heart Pulse frame, with 21 lit
dots and center levels 2–5. Reset acceptance passed; foreground release then
restored Heart Pulse, with 26 frame indices sampled in the second check.
Firmware boot 2126796425, service configuration, boot default, conversation and
permission mode were preserved. No firmware upload or inference request was
needed. This is firmware framebuffer readback, not an optical measurement.
