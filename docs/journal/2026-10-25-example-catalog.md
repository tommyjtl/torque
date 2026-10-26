# Packaged example catalog

**2026-10-26 follow-up:** The catalog is deployed and
[unattended Linux updates](2026-10-25-unattended-runtime-updates.md) are enabled.
The manual authentication below records the original rollout; current activation
uses `torque update` without another sudo script on the configured board.

Implemented a shared `torque.examples` catalog and the `torque example` shell
command. Each of the six reference programs carries `example.toml`; launch
modes specify default arguments and requirements. Scripts retain their own
argument parsers, so future flags do not require launcher edits. The build
automatically includes registered folders and resources in the wheel/sdist.
`idle-sketch` remains outside this Python catalog.

The application wheel and source distribution built successfully. A clean
temporary environment outside the checkout listed all six entries and generated
nine SVGs through preview mode without a daemon. The full suite passed 214
tests with two local native-Bridge skips at initial deployment.

The user authenticated the Linux-only update. Release
`0.2.0-d744b9972b29` became active; `unoq-control`/firmware stayed 0.4.0,
protocol [1,3]. MCU boot ID remained **411099270** before and after. The Arduino
app was not started/stopped, no sketch was uploaded, and boot default/service
configuration were preserved. The software updater restarts Torque only.

Installed checks used a deliberately nonexistent `TORQUE_SOCKET` for listing,
MCU-example help, and `--mode preview`. All succeeded. Forwarded
`--animation echo-ring --frame-ms 40` produced a 32-frame SVG with a 1.280-second
cycle. No hardware example was started during catalog verification. The command
and manifest authoring guide is in [cli.md](../cli.md).

## CRT Glide follow-up

Key 3 was replaced with an original CRT Glide adaptation of the reviewed
`dotm-square-10` reference: five stepped row positions, a fading wake, dark rows
ahead, and six frames per position. The clip has 30 frames / 0.750 seconds
nominally at the 25 ms default. Core Spiral is removed from the preset registry;
all eight other renderer outputs were verified identical.

The follow-up suite passed 233 tests with two local native-Bridge skips. One
unrelated oversized-shell-output cleanup test initially hit a transient macOS
process-group PermissionError; its isolated recheck and the subsequent full run
passed. The existing installed application code was preserved while preparing
the animation-only candidate `0.2.0-0fc326137cde`. The user authenticated its
Linux-only activation. The MCU stayed at firmware 0.4.0 / protocol [1,3], boot
ID **411099270**. Boot default and service configuration were unchanged.

The installed CLI successfully generated CRT Glide's SVG through preview mode
with a deliberately nonexistent `TORQUE_SOCKET`. Its animation duration is
0.750 seconds and all 104 cells have discrete animation data. The installed
registry maps key 3 to `crt-glide` and has no `core-spiral` entry. No physical
animation was started during this follow-up verification; optical observation
is still separate.
