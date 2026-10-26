# Ctrl-C reset and installed-package parity

**Date:** 2026-10-25, America/Los_Angeles

**Status:** Correction activated and installed acceptance passed.
The previous installed Ctrl-C acceptance was incomplete; this correction replaces it.

## User report and changed behavior

The user interrupted an agent turn running Breakout. The frontend raised
`AttributeError: 'Connection' object has no attribute 'reconnect'` and exited.
They requested that interrupting active work also perform the supported hardware
reset. This supersedes the earlier cancellation-only choice.

Active chat Ctrl-C now requests the same daemon operation as `/reset`: stop the
turn/managed programs, reset matrix and MCU RGB outputs to standby, verify
readback, and return to chat. One-shot ask/attach use the same behavior and exit
to the shell. Idle chat Ctrl-C still clears input. Model selection/probe interrupts
and standalone example/program cleanup retain their narrower scopes.
`torque cancel` remains cancellation-only. A failed/busy output reset must be
reported without claiming full cleanup or bypassing an external owner.

## Packaging failure

Read-only inspection of release `0.2.0-56a1a1ed2c76` found:

- Source `packages/session/src/torque/protocol.py` contained `reconnect()`.
- Both `build/lib/torque/protocol.py` and the installed module lacked it.
- Source and stale build files shared the same whole-second mtime, with different
  contents. Only `protocol.py` differed among the application Python modules.

The updater inherited a build directory from the previous runtime, and an
incremental wheel build retained that module. Source-overlay tests and basic
model/reset acceptance did not detect the mismatched installed client API.

Python builds now force application source copies, runtime preparation removes
generated root build/dist directories, and a read-only byte comparison verifies
every installed application module against the bundled source. Missing/extra
modules are rejected; bundled examples are treated separately as data. Preparation,
activation preflight and installed acceptance perform this check using isolated
Python imports so `PYTHONPATH` cannot mask a stale wheel.

## Regression and live acceptance

The real-terminal control test now checks cancellation plus matrix/RGB reset and
return to the prompt. It can launch the frontend through the staged installed
interpreter with no source overlay. Further cases cover stale same-second module
contents, missing/extra modules and refusal to activate an inconsistent wheel.

The host suite passed **243 tests, two platform skips**. All **26 ARM64 control
checks** passed with the child frontend launched through the staged wheel and
without `PYTHONPATH`. All **12 installed application modules** matched their
bundled source.

A separate live test used that installed interpreter/frontend, an isolated
daemon and a managed program routed through the existing board SDK. Setup lit
all matrix pixels and set MCU RGB test colors. Sending actual Ctrl-C through a
PTY stopped the managed program, restored standby and verified both RGB LEDs off,
returned the chat prompt without a traceback, then exited cleanly on `/exit`.
The MCU boot was unchanged during the test and no inference requests were made.
Production model/conversation state and output ownership were restored afterward.
This is framebuffer/GPIO evidence, not an optical measurement.

The reviewed bundle is `0.2.0-f71b4f8765d6`; its no-change preflight passed. The
installed-wheel live receipt is
`~/.cache/torque/interrupt-update-9909bc724c81/live-interrupt.json`.
Firmware, vendor services, SSH/sudo policy and user projects remain outside the
correction. Activation uses the existing private sudo step and no firmware upload.

## Activation

The user ran `~/.cache/torque/apply-interrupt.sh` with private sudo authentication.
Production now selects `0.2.0-f71b4f8765d6`. Both `applied.json` and
`acceptance.json` in the update directory report success. Installed/source parity
matches all 12 modules; blank retention, steady standby and MCU RGB-off readback
passed. Firmware boot 2126796425, the service unit, boot default, user settings,
conversation and permission mode were preserved. No inference or firmware upload
was performed during activation acceptance.
