# Observe controller state

With firmware/SDK 0.2.0 or newer, this passive example prints a snapshot and
observes state events for fifteen seconds. It does not change LEDs, clear a
frame, start playback, deploy firmware, or take the output-writer lock.

From the workspace root:

```bash
packages/device/.venv/bin/python examples/05-state-observer/main.py
```

Run an RGB or matrix demo from another terminal while observing. RGB values
separate the requested state from GPIO readback. Matrix pixels describe the
firmware framebuffer, not an optical measurement. Closing this observer leaves
outputs unchanged. Only one observer is supported at a time; snapshots remain
available to other clients.

Equivalent CLI commands:

```bash
packages/device/.venv/bin/unoq-control snapshot
packages/device/.venv/bin/unoq-control health
packages/device/.venv/bin/unoq-control watch --duration 15 --jsonl
```

Treat snapshots and resync events as updates to current state. This is a bounded,
best-effort state stream; it is not a durable history of every transient change.
Future fx event routing can consume the JSONL stream without turning each frame
update into a model request.
