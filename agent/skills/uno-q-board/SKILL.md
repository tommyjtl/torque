---
name: uno-q-board
description: Inspect Torque and Arduino UNO Q readiness, distinguish Linux and MCU components, and diagnose missing board services or model access.
---

# UNO Q inspection

Use `torque doctor` or the read-only `device_snapshot` tool. `torque status --json`
reports local readiness, active session and pending approvals. An idle boot does
not make a cloud request. Local readiness does not prove network or key validity.

Read [hardware.md](references/hardware.md) when choosing a component or processor.
Read [troubleshooting.md](references/troubleshooting.md) for vendor CLI details;
its prototype source-checkout commands are developer diagnostics, not startup
requirements for installed Torque.

Linux controls the user RGB LED through sysfs. The STM32 controls the 8x13 matrix
and RGB LEDs 3 and 4 through the resident firmware. Use the Torque Python SDK
for MCU programs; it routes requests through the daemon rather than creating
another native Router subscriber.

Check live CLI help, `/etc/arduino-app-cli/AGENTS.md` and installed headers for
version differences. Report inactive/missing vendor services or denied access.
Do not change services, boot defaults, groups or firmware just to pass a query.
Never dump the environment or read credential values into a transcript.
