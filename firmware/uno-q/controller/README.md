# UNO Q base controller

For the relationship between this sketch, Arduino's resident Zephyr loader,
Linux boot and Torque, see the [firmware layers in ARCHITECTURE.md](../../../ARCHITECTURE.md#the-firmware-and-software-layers).

Source version **0.4.0 / protocol 1.3** adds nine resident animation slots for
single-command preset switching to MCU RGB LEDs 3 and 4, eight-level 8×13 matrix
frames, up to 32 frames per clip, state snapshots, and async telemetry.
The validation board still runs the matched
**0.3.0 / protocol 1.2** firmware and SDK release, with successful Half Helix
playback and exact framebuffer verification. See the
[live deployment record](../../../docs/journal/2026-10-24-grayscale-half-helix.md).
The source installer now shares matching 0.4.0/protocol 1.3 pins; the
[controller update guide](../../../install/README.md) documents preparation,
explicit activation, and compatibility with older installer helpers.
Python talks to the resident sketch
through the existing local Arduino Router. Pattern edits do not compile or
upload firmware.

The [grayscale design](../../../docs/design-spec/2026-10-24-matrix-grayscale.md)
defines the extension and its release boundary. The
[Dot Matrix Animations example](../../../examples/06-dot-matrix-animations/)
previews nine presets offline by default, with an
optional Keychron/terminal selector for explicit playback.

## Resident presets in 0.4.0

`matrix-presets` advertises nine volatile slots with at most 32 frames each.
Upload a clip with `matrix.load`, then `matrix.cache(slot)` to retain it without
starting playback. After preloading, `matrix.play_cached(slot, repeat=0)` starts
the selected resident loop with one RPC and no frame upload. The SDK validates
capability before writes; an older controller returns an unsupported-feature
error. The example falls back to ordinary uploads on older controllers/SDKs.

Caching does not alter the display or last committed upload ID. A selected slot
cannot be overwritten until clear/draw/commit or another selection releases it.
Ordinary staging uploads remain independent of resident playback. Clear/draw
retain slot contents; reboot clears them. Existing boot and writer checks apply.
Status/snapshots expose the selected `preset` (0 for ordinary playback), using
optional compact wire field `j` without changing existing telemetry schemas.
Operation codes 13/14 are cache/cached-play. See the
[resident preset design](../../../docs/design-spec/2026-10-24-resident-animation-presets.md)
for memory, timing and packet-budget verification.

## Grayscale frames in 0.3.0

Installed programs use the public Torque API:

```python
from torque import Board, Frame

frame = Frame.from_rows([
    "....01234567.",
    ".............",
    ".............",
    ".............",
    ".............",
    ".............",
    ".............",
    ".............",
], bits=3)
# On an explicitly deployed 0.3.0 controller and matching Torque runtime:
with Board() as board:
    board.matrix.draw(frame)
    observed = board.matrix.frame()  # exact levels; framebuffer, not optical data
```

`Frame(pixels, bits=3)` accepts 104 integer values in 0..7. Default `bits=1`
keeps existing binary behavior: a binary 1 is rendered at hardware level 7.
Clips must use one format throughout. Existing 32-frame and duration limits
apply to both formats. An old controller fails capability validation before
any grayscale mutation; no conversion or automatic upload occurs.

The original `matrix` capability and binary RPCs stay unchanged. The optional
`matrix-grayscale` capability advertises `gray3-hex-msb`, `bits:3`, and
`max_value:7`. New mutations are `matrix.draw_gray`, `matrix.begin_gray`, and
`matrix.write_gray`, with the same expected boot ID and ownership requirements.
Three-bit frames pack to 39 bytes / 78 hex characters; the first pixel's most
significant bit is the first packed bit. Commit/abort/play/stop/clear are shared.
Commit holds the old visible frame and its format until explicit playback.

Binary snapshots/events retain schema 1. Grayscale snapshots/matrix events use
schema 2 with a compact `m` array containing Base64-packed pixels and playback
metadata, keeping complete packets within 256 bytes. The SDK returns `bits`,
`frame_hex`, and rows preserving native intensities. Older SDKs cannot decode
grayscale state; use the matching SDK rather than treating brightness as binary.
RGB/health/error events retain schema 1, with operation codes 10..12 added for
the grayscale commands. See the design for the complete layout.

## Prepare on the UNO Q

From the repository root:

```bash
python3 scripts/prepare-controller.py --client --resolve
```

This installs the native client into `packages/device/.venv` and compiles with the pinned
Arduino profile. It may download dependencies, including pip inside that
environment when Debian lacks `ensurepip`. It requires no manual uv installation,
sudo, system Python changes, or API key. Build output and provenance go under
`.cache/base-controller/`. It never starts an app or uploads firmware.

Use `--client-only` to install only the client. Without `--resolve`, compilation
uses already-installed core/libraries and reports missing dependencies. The fx
setup script remains separate and never deploys this controller.

## Router access and read-only checks

The user running a native client needs access to
`/var/run/arduino-router.sock`. The SDK reports missing or denied socket access;
it does not change file modes, user groups, services, or connect over TCP.
An administrator must resolve missing intended access before native control.
On the validation board, the user added `arduino` to the existing router group.
A fresh SSH session now has socket access, and the native client reaches the
router. Version 0.3.0 is deployed there and reports protocol 1.2 and `ready: true`.

That board's socket belongs to the existing `arduino-router` group. An
administrator can grant intended access with the following command on that
board, then the user must leave and reconnect the SSH session:

```bash
sudo usermod -aG arduino-router arduino
```

This is an explicit administrator action, not part of preparation. On another
board, check the actual socket owner/group before choosing an access change.

After an authorized deployment and with socket access:

```bash
packages/device/.venv/bin/unoq-control info
packages/device/.venv/bin/unoq-control status
```

These commands do not start playback or change LEDs. A different sketch, missing
RPC method, or unsupported protocol produces an error rather than an upload.

## Deliberate deployment

Deployment replaces the current MCU sketch and can stop the running Arduino app.
When that replacement is intended, run:

```bash
python3 scripts/flash-controller.py --replace-firmware
```

The helper requires a successful current profile build, records the current app
listing, and invokes App CLI's existing app-start workflow. App CLI may rebuild
and creates its normal Linux runtime container from the small deployment wrapper.
That wrapper runs `App.run()`; user demos run independently with the native SDK.
The helper verifies firmware identity after upload. It does not back up arbitrary
MCU flash or change boot defaults; keep the previous app source/artifact when
restoration is needed. Its build manifest describes the preflight build, not a
read-back hash of the uploaded binary.

When replacing the same running app, the helper explicitly stops it, waits for
the stopped state, then starts it. This avoids an observed App CLI 0.14 restart
race. It verifies the expected source version and, when the previous controller
is reachable, a fresh MCU boot identifier.

Do not deploy while router access is unresolved: identity verification would be
blocked. Starting another Arduino app may later replace this firmware. Stopping
its Linux wrapper does not guarantee the MCU stops or remains unchanged; check
identity again before the next use.

## Python use

```python
from unoq_control import Board, Frame

with Board() as board:
    board.rgb(3).set(True, False, False)
    try:
        frame = Frame.from_rows([
            "#############",
            "##..........#",
            "#.#.........#",
            "#...........#",
            "#...........#",
            "#...........#",
            "#...........#",
            "#############",
        ])
        board.matrix.draw(frame)
    finally:
        board.rgb(3).set(False, False, False)
        board.matrix.clear()
```

`Frame` also accepts 104 integer pixels, each 0 or 1, in row-major order.
`matrix.load(frames, durations)` validates the whole animation in Python, sends
it to staging storage, and commits only after every frame is acknowledged. It
does not start playback. `matrix.play(repeat=1)` plays once; `repeat=0` explicitly
requests an infinite loop. Frame durations of 20..60,000 ms are accepted, with
up to 32 frames. These are input limits, not a measured frame-rate guarantee.

On completion or `stop()`, the matrix holds its last frame. `clear()` stops and
blanks it. Closing Python retains the display and lets finite MCU playback
finish. A reboot clears stored frames. The finite
[examples](../../../examples/) clear their outputs unless explicitly detached.

Use `from unoq_control.leds import UserLed` for the Linux user RGB LED, or
`with Board().rgb("linux-user") as led:`. This direct sysfs context snapshots
brightness/triggers and restores them on exit, without connecting to the MCU.
MCU RGB accepts booleans only and hides the active-low pin wiring.

## Protocol and failure behavior

RPC names start with `unoq.control.v1.`. Arguments are positional. Every mutation
starts with the `boot_id` read from `system.info`; firmware rejects a stale boot
before changing hardware. The client never automatically retries mutations.

| Suffix | Arguments after boot ID | Result |
|---|---|---|
| `system.info` | No boot ID or arguments | JSON string: name, version, protocol, boot ID, ready |
| `system.snapshot`, `system.health` | No boot ID or arguments | Compact JSON strings decoded by the SDK |
| `system.subscribe` | Callback endpoint | Positive observer token; identical endpoint retries are idempotent |
| `system.renew`, `system.unsubscribe` | Observer token | 0 on success; stale token returns -3 |
| `system.capability` | No boot ID; capability name | JSON string: capability object or `null` |
| `matrix.status` | No boot ID or arguments | JSON string: boot ID, playback, frame count/index, upload and committed IDs |
| `rgb.set` | LED ID, red, green, blue | 0 on success |
| `matrix.draw` | Encoded frame | 0 on success |
| `matrix.clear`, `matrix.stop` | None | 0 on success |
| `matrix.begin` | Frame count | Positive upload ID |
| `matrix.write_frame` | Upload ID, index, encoded frame, duration ms | 0 on success |
| `matrix.commit`, `matrix.abort` | Upload ID | 0 on success |
| `matrix.play` | Repeat count | 0 on success |

A wire frame is 13 packed bytes represented by **26 hexadecimal characters**.
Pixel `row * 13 + column` occupies bit `7 - (index % 8)` in byte `index // 8`.
The Python API handles this encoding. Compact requests and JSON-string replies
fit within a 256-byte test budget; the actual pinned transport is checked during
compilation and wire tests. Arduino RPC boundaries use `String`, not
`std::string`, because of the pinned MsgPack library's Arduino configuration.

Application codes: -1 invalid arguments, -2 busy upload, -3 stale boot/upload,
-4 incomplete animation, -5 unsupported capability, -6 exhausted capacity.
Transport errors remain distinct. Unknown capability queries return `null`.
The client rejects a firmware identity with `ready: false`, which indicates
incomplete RPC registration.

Uploads expire after 30 seconds without a valid frame write. Incomplete or bad
uploads never replace the old animation. Commit stops old playback while
preserving the visible frame; repeated successful commit is idempotent. A
status query reports the committed ID after an ambiguous timeout. Abort affects
only the matching staging upload. Playback runs in the main loop without
blocking delays; late ticks hold a frame rather than emitting a catch-up burst.
Failed `load` calls expose their upload identifier as `error.upload_id` on a
`ControllerError`. Reply waiting uses the configured timeout; the native Bridge
transport also has its own bounded send/reconnect waits.

Cooperating clients use an owner-only advisory lock for MCU writes, held until
`Board.close()`. Read-only clients do not take it. It does not authenticate Bridge
callers. The optional display leases described by the
[hardware feedback spec](../../../docs/design-spec/2026-10-24-fx-hardware-feedback.md)
are not part of version 0.2.0; `display-lease` capability returns `null`.

## State snapshots and asynchronous observation

```python
from unoq_control import Board

with Board() as board:
    print(board.snapshot())
    print(board.rgb(3).status())
    print(board.matrix.frame())
    print(board.health())
    with board.watch() as observer:
        for event in observer:
            print(event)
```

Observation is passive and does not take the output-writer lock. Use another
client or terminal to change LEDs while watching. Close the observer or press
Ctrl-C to stop. `observer.latest` returns a copy of the current cached snapshot.
The [finite observer example](../../../examples/05-state-observer/) runs for fifteen
seconds. CLI equivalents are `snapshot`, `health`, and
`watch --duration 15 --jsonl`.

RGB state includes requested channels, independently read raw GPIO levels,
active-low logical readback, and `readback_valid`. A failed GPIO read produces
unavailable readback rather than an invented off state. Matrix state reports
the firmware framebuffer and playback metadata; it does not measure emitted
light. RGB channels remain binary, without PWM brightness fields.

The MCU supports one observer with a ten-second lease. Normal close releases it;
an abandoned observer expires without changing outputs. Matrix progress is
sampled at 200 ms intervals. Queue gaps or receiver overflow cause snapshot
resynchronization. This is a best-effort state stream, not a durable history of
every transient change.

The observer uses a separate connection and performs no nested RPCs from the
notification callback. It marks cached state stale on disconnect and reconnects
with bounded retries. For deliberate maintenance, increase the retry budget:

```bash
packages/device/.venv/bin/unoq-control watch --duration 180 --reconnect-attempts 60 --jsonl
```

The normal default is three attempts, with a maximum of 100. Recovery never
replays actuator commands. The event stream can feed a later fx integration;
the SDK does not automatically start model turns or execute event contents.

## Validation boundary

Host state-machine/client tests and UNO Q compilation are separate from an
authorized upload, actual hardware RPCs, and a person's observation of the LEDs.
See [validation results](../../../docs/validation.md). Version 0.2.0 passed deployment,
GPIO/framebuffer snapshots, async delivery, observer expiry, and recovery across
an actual MCU firmware restart. The user previously confirmed the visible RGB
and matrix demos on version 0.1.0. Optical timing and power-cycle persistence
remain separate checks.
