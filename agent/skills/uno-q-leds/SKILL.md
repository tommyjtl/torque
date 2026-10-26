---
name: uno-q-leds
description: Create, change, or run finite RGB LED demos on the Arduino UNO Q Linux-controlled user LED, without flashing an MCU sketch.
---

# Linux user RGB LED

Find the workspace's `examples/01-linux-rgb-led/main.py`. Read its README and
implementation, then copy the example into a new `projects/<name>/` directory
when creating a variation. Resolve paths from the workspace root, not from the
shell's current directory or an assumed home-directory name.
The shared standard-library driver is `packages/device/src/unoq_control/leds.py`; read it
when changing restoration behavior. The example locates it from the checkout,
so the direct Linux LED path still needs no package installation or Bridge.

Use only `red:user`, `green:user`, and `blue:user` for ordinary demos. Read each
channel's `max_brightness`; do not assume a fixed range. Snapshot its brightness
and active trigger before writing. Temporarily select `none` for a running demo,
then restore brightness and the original triggers on completion or interruption.
Keep loops finite by default and retain restoration when editing the example.

Creation and read-only `--status` checks can proceed as requested. Run the LED
code when execution is requested; creating an example alone does not imply a
physical demo. Do not change permissions or services to make it work. Report
missing access clearly. Do not redirect a demo to panic, WLAN, or Bluetooth LEDs.

Torque shell calls use a flat `command` field and require approval for the exact
action. A tool validation error is different from Linux access denial.

Verify Python syntax and behavior against simulated LED files before a physical
run. A physical run should finish or be stopped, with the prior state restored.
Report what the software did separately from what the user saw on the board.
