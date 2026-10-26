# Torque controller API

For direct requests, use the board tools: `matrix_fill({on: true})` lights every
pixel; `matrix_clear({})` retains an explicitly blank matrix; `matrix_draw` takes
8 rows of 13 . or # characters. `rgb_set` takes LED 3 or 4 and boolean red/green/blue.
No project file or shell command is needed. Direct state stays until changed,
a program takes output ownership, or `matrix_release` explicitly restores status.
`device_snapshot` reports actual framebuffer/GPIO plus display mode and ownership.
Use the returned state for a concise confirmation.

Run user programs with the managed Python interpreter provided in the session
instructions, or `torque run projects/<name>/main.py`. No virtual environment
activation is needed.

```python
import time
from torque import Board, Frame

with Board() as board:
    try:
        frame = Frame.from_rows([
            '#############', '#...........#', '#...........#', '#...........#',
            '#...........#', '#...........#', '#...........#', '#############',
        ])
        board.matrix.draw(frame)
        print(board.snapshot()['matrix'])
        time.sleep(1)
    finally:
        board.matrix.clear()
```

`board.rgb(3).set(True, False, False)` sets LED 3 to red. LED 4 uses the same API.
Turn it off with three False values. Dimming/PWM is not supported in this bundle.
`board.snapshot()` distinguishes requested RGB state and GPIO readback.
`board.health()` reads controller health without acquiring output ownership.

`matrix.load(frames, durations=150)` transactionally uploads 1..32 frames.
Each duration is 20..60000 ms. `matrix.play(repeat=1)` starts finite buffered
playback; repeat=0 explicitly loops. `stop()` holds the current frame;
`clear()` stops and blanks it. Python loops can draw frames directly as well.
Avoid polling faster than needed for a small 8x13 display.

`with board.watch() as observer` reads shared asynchronous events;
`observer.get(timeout=.2)` raises `queue.Empty` on timeout. `observer.latest`
returns the latest cached state. Gaps require a snapshot; this is not a durable
record of every transient event. Several Torque observers share one MCU
subscription. A `Board` connection owns outputs after its first write and releases
them on close. A second writer is rejected; status rendering remains paused.
After a program closes, Torque restores its latest status cue, so a blank
framebuffer is not the expected final idle display.

## Firmware maintenance

The managed source lives under the selected release's `firmware/uno-q/controller`;
the deployed Arduino app has a stable path under `/var/lib/torque/device/uno-q`.
Ordinary programs use this running firmware. Starting a different Arduino app
can replace it and make Torque's hardware interface unavailable.

For new MCU capabilities, change firmware in a development checkout, compile
with `python3 scripts/prepare-controller.py --resolve`, and deploy only through
a deliberate coordinated release installation. The installer records the prior
app/default and checks a fresh firmware boot. It selects the stable app for
startup. App CLI may compile/load/upload when starting that app at boot.

Inspect current apps and explain what will be replaced before a requested upload.
Never deploy as a hidden side effect of diagnostics or a model turn. Controller
0.2.0 has binary matrix frames and telemetry, but no device-side output expiry,
font renderer, TFT support, or grayscale API.
