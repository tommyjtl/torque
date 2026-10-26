---
name: uno-q-apps
description: Create and debug finite UNO Q matrix and MCU RGB programs using Torque's resident controller, shared telemetry, and Python SDK.
---

# UNO Q programs

Use `matrix_fill`, `matrix_clear`, `matrix_draw` or `rgb_set` for direct control.
These retain user state without a generated Python file. Read `device_snapshot`
or `device_capabilities` when needed. Use `matrix_release` only when returning
the display to session feedback is requested.

For a requested program use `from torque import Board, Frame` and `run_program`.
Create files under `projects/<name>/`. Read
[app-workflow.md](references/app-workflow.md) for API examples and firmware boundaries.

Matrix: eight rows by thirteen columns, binary pixels, at most 32 buffered
frames. MCU LEDs 3 and 4: boolean RGB channels. New patterns need Python changes;
they do not need another sketch or an Arduino app restart.

Read state using `device_snapshot` before changing outputs. Snapshot RGB readback
comes from GPIO; matrix data comes from the firmware framebuffer, not a camera.
For finite programs use `with Board() as board` and cleanup appropriate to their
requested duration. Direct on/off/static frames use retained tools instead.
Torque yields the status
matrix while a program owns the device and restores the status cue on disconnect.
An MCU observer lease is not an output watchdog; hard-kill cleanup is limited.

Creation alone does not authorize running a demo. When execution is requested,
obey the requested behavior and duration. Do not flash firmware,
change services, widen permissions, or bypass a denied tool as a prerequisite.
Report missing controller readiness and use deliberate maintenance for firmware
changes. Distinguish successful RPCs from physical observation.
