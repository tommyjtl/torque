# UNO Q matrix grayscale and Half Helix

**Status:** Implemented, deployed at the user's explicit request, and verified
through live framebuffer readback, 2026-10-24. Firmware 0.3.0 / protocol 1.2 and
SDK 0.3.0 run in the matched release `0.1.0-e5e9bab7e388` on the validation
board. Boot defaults and the service configuration were preserved. See the
[deployment record](../journal/2026-10-24-grayscale-half-helix.md).
The subsequent source staging/install scripts now share 0.4.0 / protocol 1.3 through
`install/torque_bundle.py`. The durable [controller updater](../../install/README.md)
owns its readiness check and supports older installer helpers.

Validation evidence:

| Check | Result |
|---|---|
| `python3 -m unittest discover -s tests -v` on the Mac | 140 tests, passed; two native Bridge tests skipped locally |
| Both native Bridge tests using the existing UNO Q Python environment and temporary Unix sockets | 2 passed, including grayscale requests and schema 1→2 notifications |
| Arduino CLI 1.5.1, pinned `default` UNO Q profile, isolated `/tmp/torque-grayscale-vf4s94dm/` source | Compile passed: 138,548 bytes flash; 60,276 bytes globals |
| Half Helix offline SVG and XML/frame checks | Generated; 24 frames at discrete levels; no board connection |
| Firmware upload and runtime restart | 0.3.0 / protocol 1.2 verified with a new MCU boot ID; Torque ready |
| Half Helix on the UNO Q | 15 finite loops completed; 122 grayscale samples matched all 24 generated frames; all levels 0..7 observed |
| Physical LED appearance | Not yet confirmed by a person |
| Source-only updater/gallery/input follow-up | 164 tests passed, including older-helper compatibility, repeat-run guards, animation geometry, Keychron identity/repeats/gaps, terminal restore, and finite fallback; two native Bridge tests skipped locally |

The source build and `compile.log` remain under that temporary board directory.
Host test logs are `/tmp/torque-grayscale-tests-final.log`. The preview is
`projects/half-helix/preview.svg`. Browser rendering was not verified; the local
file URL was blocked by browser policy, so preview checks used its SVG data and
quantized frames. Live deployment/playback evidence is saved locally in
`projects/half-helix/validation.json` and on the board in
`/home/arduino/torque/projects/half-helix/live-result.json`.

## Purpose and hardware boundary

Implement the eight-level brightness proposed by the
[animation review](2026-10-24-animation-reference-review.md),
[studio design](2026-10-24-session-display-studio.md), and
[vision](2026-10-24-torque-vision.md). Half Helix is the first reference example.
Other animation families and studio editing follow separately.

The STM32 MCU owns the UNO Q's **13-column by 8-row** blue matrix. The pinned
ArduinoCore-zephyr 1.0.0 matrix driver supplies `setGrayscaleBits(3)` and
`draw(const uint8_t*)`, with native pixel levels **0..7**. Linux generates
frames; the MCU renders and schedules them. Use the driver's refresh routine,
not Linux-side PWM or per-frame RPCs for buffered playback. RGB LEDs remain
binary and are outside this feature.

## Public frame contract

Keep `from torque import Board, Frame`. A `Frame` has 104 row-major integer
pixels and an explicit `bits` value: 1 (default) or 3. Boolean and floating-point
pixels are invalid. Coordinates and row orientation remain unchanged.

* `Frame(pixels)` and `Frame.from_rows(rows)` retain binary behavior. Binary
  `1` / `#` means fully lit, mapped to hardware level **7**.
* `Frame(pixels, bits=3)` accepts 0..7. In this format **1 is dim**.
  `Frame.from_rows(rows, bits=3)` accepts eight 13-character rows of `.` or
  digits 0..7. There is no implicit thresholding or 0..255 conversion.
* `matrix.draw` and `matrix.load` choose the wire method from `frame.bits`.
  A clip must use one format throughout; reject mixed clips before any RPC.
* `matrix.frame()` reconstructs the original format and exact intensities from
  a coherent framebuffer snapshot. It is not an optical measurement.

Expose grayscale only after a `matrix-grayscale` capability query succeeds.
An old controller returns `null`; fail with a clear unsupported-feature error
before taking ownership or sending a mutation. Binary drawing and playback
continue to work with controller 0.2.0. Old SDKs can use binary commands on the
new controller but cannot decode state while another client displays grayscale.
They must not be presented with a fabricated binary readback.

## Wire contract and storage

Preserve `unoq.control.v1` and every existing binary command. Add:

| RPC suffix | Arguments after expected boot ID | Operation code |
|---|---|---:|
| `matrix.draw_gray` | Packed grayscale hex | 10 |
| `matrix.begin_gray` | Frame count | 11 |
| `matrix.write_gray` | Upload ID, frame index, packed grayscale hex, duration ms | 12 |

Binary frames remain 13 bytes / 26 hex characters. Grayscale is **39 bytes /
78 hex characters**: concatenate each pixel's three bits most-significant bit
first, in row-major order. This uses exactly 312 bits, without padding.
Each upload records its format; reject a write through the other format's
method without changing staging or active data. `commit`, `abort`, `play`,
`stop`, `clear`, and `status` are shared.

Internally both formats use packed three-bit frames. Each binary on pixel is
expanded to 7. Preserve a separate visible-format flag and a per-animation
format flag, so committing an upload does not change the held frame's format.
Clear produces a binary blank frame. Active/staging frame arrays use 2,496
bytes total; duration arrays use another 256 bytes, before metadata and the
104-byte unpacked driver frame. Bound the controller object to 3 KiB in tests.

Retain 1..32 frames, 20..60,000 ms durations, 30-second staging expiry, atomic
commit, idempotent repeated commit, stale-boot rejection, no automatic mutation
retries, finite playback/explicit infinite repeat, and no catch-up bursts.
Reset discards frames. Closing Python does not itself cancel MCU playback.
Independent regional composition and larger buffers are deferred.

`matrix-grayscale` advertises rows, columns, frame/duration limits, `bits:3`,
`max_value:7`, and `encoding:"gray3-hex-msb"`. The original `matrix` capability
retains its binary encoding. Firmware identity is 0.3.0, protocol [1,2].

## Exact brightness telemetry within the existing transport

Retain the installed **256-byte MessagePack packet budget**, including the
envelope and 34-character observer callback name. Do not enlarge transport
buffers as a shortcut. Schema 1 remains unchanged for binary snapshots/events,
RGB events, errors, and health.

A snapshot or matrix event whose visible frame is grayscale uses schema 2:
keep common fields `v,b,s,r,t,c`, snapshot RGB fields, and event `h,k,o`.
Replace the six binary matrix fields `f,p,i,n,a,u` with one `m` array:

```text
m = [base64_packed_gray3, playing, frame_index, frame_count, committed_id, upload_id]
```

The 39 packed bytes encode to exactly 52 standard Base64 characters, with no
padding. Short array metadata leaves room for maximum-width counters. Reject
wrong array sizes, invalid Base64/lengths, out-of-range metadata, and unsupported
schemas. The SDK normalizes both formats to `frame_hex`, `bits`, readable rows,
playback metadata, and `source:"firmware_framebuffer"`. Brightness-only changes
advance the revision and produce sampled matrix events. Existing gap recovery,
observer expiry, source labels, and 200 ms playback sampling stay in place.

Advertise telemetry `schema:1` plus `schemas:[1,2]`. The new SDK accepts both.
Operation codes 10..12 also appear in health/error decoding. Preserve the
daemon's writer ownership gate for all three added mutation methods. Its
controller identity check must recognize the new source bundle; installed
0.2.0 releases are not changed by editing this repository.

## Dot Matrix Animations reference

The reference is now `examples/06-dot-matrix-animations/`, using the public
Torque API and original renderers inspired by the reviewed motion. It includes
nine presets: Half Helix, Neon Drift, CRT Glide, Echo Ring, Origin Wave, Prism
Bloom, Sound Bars, Mobius Run, and Plasma Veil. All render a 5x5 region at (4,1),
leaving other cells off, using at most 32 frames and native
levels 0..7 and peak/timing controls. Default steps are now 25 ms at the user's
request. Half Helix retains
the renderer verified in the live deployment. The six newest animations have
host verification, not physical LED acceptance.

Default execution creates nine offline SVG previews and never opens a board
or input device. Explicit `--play` auto-detects a readable Bluetooth Keychron
K0 Max Keyboard through Linux sysfs and verified descriptor identity. Keys
1–9 select the continuous preset loops in the order above, ignoring repeats
and initial held keys. A different choice supersedes the active clip; selecting
the same preset keeps it running. Escape stops and exits. Missing or
disconnected input falls back to three finite gallery rounds, then exits.
Input overruns resynchronize held state without inventing presses. There is
no exclusive grab or change to permissions, pairing, or services.

`--input terminal` explicitly uses an interactive SSH/local terminal and restores
its settings on exit. `--input none` forces the finite gallery. A single
`--animation` bypasses selection and repeats that clip `--repeat` times.
Request clear on normal completion, Ctrl-C, SIGTERM, or timeout when communication
remains available. A hard kill or connection loss cannot guarantee clear.
Generated variations remain in `projects/`.

## Verification and release boundary

Host checks must exercise Python/C++ packed-frame agreement (including bits
across byte boundaries), levels 0..7, legacy full brightness, invalid inputs,
format-mismatched uploads, atomic replacement, expiry, timer wrap, finite and
infinite playback, exact brightness readback, format transitions, error codes,
maximum-width telemetry and full packet sizes, ownership rejection, unsupported
firmware, and preview without hardware calls. Run the repository Python suite.
Compile the pinned UNO Q profile separately if the target toolchain is available.

Record host checks, UNO Q compile, successful upload, framebuffer readback, and
a person's LED observation as separate evidence. Implementation and preview
alone do not authorize starting an Arduino app, flashing firmware, restarting
services, or updating the installed release. The later explicit request to
flash/restart and run Half Helix authorized the deployment recorded above. No
boot defaults, service configuration, or access permissions were changed.
Source-installer version pins are now reconciled. Saving and testing the durable
updater and extended example does not redeploy the running board.
