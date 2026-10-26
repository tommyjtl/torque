# Buffered matrix sweep

Python uploads thirteen column frames and asks the MCU to play them three times
at 100 ms per frame. The MCU schedules the animation from memory. Status polling
observes completion; it does not supply each frame.

Prepare and deliberately deploy the
[base controller](../../firmware/uno-q/controller/README.md) first, with intended
router access for the current user. From the workspace root, when execution is
requested:

```bash
packages/device/.venv/bin/python examples/04-matrix-animation/main.py
```

The script requests clear after completion, Ctrl-C, or SIGTERM. To demonstrate
that the MCU can finish after Python exits:

```bash
packages/device/.venv/bin/python examples/04-matrix-animation/main.py --detach
```

Detached playback remains finite and holds the last column afterward. Clear it
with `packages/device/.venv/bin/unoq-control clear`. Cleanup after a hard kill or connection
loss is not guaranteed. Resetting the MCU discards its animation buffers.

Copy the folder into `projects/<name>/` and change frames/durations to create a
variation. Use 1..32 frames and accepted durations of 20..60,000 ms. The accepted
duration range is not a measured physical refresh-rate guarantee.
