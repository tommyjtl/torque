# Resident animation presets and responsive selection

**Status:** Controller/SDK 0.4.0, protocol 1.3 implemented and software-checked.
The validation board still runs 0.3.0; implementation and compilation do not
deploy it. The pinned UNO Q compile passed: 154,636 bytes flash and 74,248 bytes
global RAM (28%). The 178-test host suite passed with two local Bridge skips;
both native Bridge wire tests passed separately on the board using test sockets.
The maximum cached grayscale notification is 253 bytes including its envelope.

## Problem and goal

The interactive gallery uploads 24–32 frames on every selection. Read-only
measurements on the active board found median status/snapshot RPC round trips
of 25.3/27.35 ms. Many sequential upload acknowledgments explain approximately
a second of switching delay. Faster input polling cannot eliminate that work.

Upload the gallery once at startup and retain nine clips in MCU RAM. A keypress
then selects one resident clip with one bounded RPC. Use 10 ms input polling and
sample playback health separately at 250 ms; target a visibly prompt switch,
without promising a hard real-time or measured optical latency bound.

## Controller and API

Keep all binary/grayscale upload and playback methods. Add optional capability
`matrix-presets` with `max_presets:9`, `max_frames:32`. Slot numbers are 1..9;
0 denotes ordinary committed-buffer playback. Installed programs continue to
use `from torque import Board, Frame` and the existing ownership/boot checks.

| Operation | RPC after expected boot ID | Behavior |
|---|---|---|
| `matrix.cache(slot)` | `matrix.cache(slot)` | Copy the complete committed clip into a slot; no playback or visible change |
| `matrix.play_cached(slot, repeat)` | `matrix.play_cached(slot, repeat)` | Select and immediately start that resident clip |

Only committed, complete clips can be cached. Reject invalid slots/repeat counts
without changing state; empty slots return incomplete. A selected slot cannot
be overwritten, including while stopped: clear/draw/commit or select another
slot first. Ordinary active/staging uploads remain independent of cached
playback, so partial/expired uploads cannot corrupt the visible resident clip.
Commit stops playback and holds the visible image as before, then selects the
new ordinary committed buffer for subsequent play. Last committed upload IDs
keep their original transactional meaning; cache selection does not invent a
new upload ID.

Cache slots retain their own frames, durations, count, and format. Cached
playback uses them directly rather than copying or uploading frames per switch.
Clear/draw leave resident storage intact and return to ordinary-buffer metadata,
resetting the cursor when necessary. Stop holds the selected source and frame.
All resident clips disappear on an MCU reset. No mutation is automatically retried.

Nine additional 32-frame packed clips use about 12.5 KiB. Host checks bound the
whole controller object to 16 KiB; verify target RAM with the pinned UNO Q build.
Frame durations remain 20..60,000 ms and repeat 0 explicitly loops.

## Telemetry and compatibility

Add `preset` to `matrix.status`. Framebuffer snapshots/matrix events carry
optional compact `j` for a nonzero selected slot. Both existing telemetry
schemas stay intact, including the six-field grayscale `m` array. The SDK
normalizes `preset` to 0 when the field is absent. Include the source selection
in state comparison; verify maximum-width cached grayscale events still fit
the complete 256-byte transport budget. Operation codes 13/14 identify cache
and cached-play commands in errors/health.

The new SDK can still use 0.2.0/0.3.0 controllers; unsupported preset capability
is reported before writes. The example falls back to ordinary uploads when
the controller or SDK lacks caching, with an explicit slower-switching message.
The matched daemon accepts the new pair and keeps its existing writer gate for
both added RPCs. Installer source pins move together to 0.4.0 / [1,3].

## Gallery and validation

Keys 1–9 select Half Helix, Neon Drift, CRT Glide, Echo Ring, Origin Wave,
Prism Bloom, Sound Bars, Mobius Run, and Plasma Veil. All clips fit a centered
5x5 region, native levels 0..7, and a 32-frame slot. Defaults remain 25 ms and
continuous selected playback until another key or Escape. No-keyboard fallback
plays three finite gallery rounds. No source code from the upstream gallery
is incorporated; the motion references inform original small renderers.

Test all slots, invalid and empty selections, overwrite protection, independent
staging/expiry/commit behavior, format transitions, timer wrap, finite/infinite
playback, reset, exact grayscale readback, packet budgets, ownership rejection,
old-controller fallback, and one cached-play mutation per key change. Run the
full Python suite and the pinned target compile. Staging a matched release is
separate from administrator-authorized activation. Preserve service and boot
configuration; do not interrupt the current live demo for software checks.
