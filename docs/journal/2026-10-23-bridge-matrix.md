# Python control of the UNO Q LED matrix through Bridge

**Date:** 2026-10-23, America/Los_Angeles

**Status:** Deferred proposal for a future example.

**2026-10-24 follow-up:** The
[base controller design spec](../design-spec/2026-10-24-base-controller.md) expands this
idea into shared MCU firmware, a native Python client, and buffered animations.
Use that draft as the current implementation plan; this entry preserves the
original matrix discussion.

The 2026-10-24 implementation now lives under `firmware/base-controller/` and
`python/src/unoq_control/`. Software checks and compilation pass, and live router
access is confirmed. Version 0.1.0 was deployed and its RGB/matrix outputs were
confirmed by the user. The earlier standalone apps
were consolidated without maintaining an archive copy.

The goal is to upload matrix firmware once, then change images and animations
from Python on Linux without recompiling the MCU sketch for every pattern.
This would make the matrix convenient to control from fx on the board.

## Current foundation

The UNO Q has two processors: Linux runs fx and Python; the STM32 MCU controls
the onboard 8-row by 13-column blue LED matrix. Bridge carries calls between
them. A programmed MCU can continue running after a Linux app stops.
[Arduino hardware overview](https://docs.arduino.cc/hardware/uno-q/)

At the time of this entry, separate MCU matrix sweep and Python-to-MCU LED
examples had compiled successfully. They were consolidated into the
[shared base controller](../../firmware/uno-q/controller/README.md) on 2026-10-24.
A Bridge-controlled matrix is a proposed combination of those examples, not an
implemented feature. No physical Bridge-matrix verification has been performed.

## Proposed MCU firmware

Use `Arduino_LED_Matrix` and Router Bridge to expose a small RPC interface:

| Working method name | Purpose |
|---|---|
| `draw_frame(pixels)` | Validate and draw exactly 104 monochrome pixel values |
| `clear()` | Blank the matrix |
| `status()` | Optional firmware identity and protocol version check |

Use row-major indexing, `pixels[row * 13 + column]`, with pixel values restricted
to 0 or 1. Reject malformed frames before changing the display and return an
explicit success or failure. Confirm the installed Bridge's encoding and message
limits rather than treating the raw pixel count as the complete wire payload.

Serialize matrix updates. Check whether the installed Router Bridge version's
main-loop-safe callbacks fit this use, or protect access with an explicit mutex.
The firmware should start with a blank display.

## Proposed Python helper

The helper would build and validate frames, call the MCU methods, and provide
bounded timeouts and useful errors when the MCU is unavailable or running a
different sketch. Start with a static heart or smiley and a clear command.
Add animations after single-frame updates work reliably.

The expected change boundary is:

- A new image, frame sequence, or Python rendering algorithm needs new Python
  code or data, with the same MCU protocol.
- A new MCU command, protocol format, driver change, or firmware fix needs
  recompilation and another upload.

## Runtime questions to resolve

1. **Where does the helper run?** Reuse App Lab's managed Python runtime and
   `arduino.app_utils.Bridge`, or use the native Python Bridge package on Linux.
   Preserve the project's goal that users do not need to install uv manually.
2. **How do updates avoid an upload?** Keep the MCU firmware resident and send
   frames through the existing router connection. Verify the actual workflow:
   editing an App Lab file and restarting its entire app may trigger an upload.
   Do not assume App Lab always skips unchanged MCU firmware.
3. **What happens after an MCU restart?** Detect readiness and firmware identity;
   reconnect with a bounded policy instead of retrying indefinitely.
4. **What happens on disconnect?** Choose whether the MCU retains the last frame
   or clears it after a timeout. Cleanup on the host cannot guarantee clearing
   after a hard kill or power loss.
5. **How fast should animation run?** Measure a modest initial frame rate on the
   installed Bridge stack before selecting a limit or adding buffering.

No new network service is needed for the initial design; use the existing local
Arduino Router. See the [Bridge API reference](https://docs.arduino.cc/software/app-lab/bridge/bridge-api).

## Validation plan

First test frame length, value bounds, row and column mapping, malformed input,
timeouts, and reconnect behavior without hardware. Compile and build a complete
Arduino App using the existing pinned profile.

For physical verification, deliberately select the app or MCU sketch to replace
and perform one initial upload. Then show a frame, clear it, change the Python
pattern, and show a second frame without another compile or upload. Test an MCU
restart and confirm the helper reports or recovers from it as designed.

Keep fx permission checks enabled. A malformed shell call is a separate issue
from Linux permissions; the existing
[troubleshooting guide](../../agent/skills/uno-q-board/references/troubleshooting.md)
records the `request.action` requirement observed in fx 0.0.14.

## Resume point

Revisit this as a possible `examples/05-bridge-matrix/`. Begin by deciding where
the Python helper runs and proving that its frame-update path does not restart
or reflash the MCU. Then combine the current matrix and Bridge examples with
`draw_frame` and `clear`; keep animations out of the first physical test.
