# Little NeXT

An on-demand NeXTSTEP 3.3 browser experiment for the UNO Q. Open the Little
NeXT desktop shortcut, or run `bash launch.sh` from this release in an existing
graphical session. Alt+F4 closes Chromium and the local server. This is separate
from Little Macintosh, Torque services, firmware and boot defaults.

The NeXT display is 1120 × 832 and is scaled to fit the 640 × 480 board
display, so text can be small. The emulator and disk chunks are fetched on
demand from Infinite Mac and cached under `~/.cache/torque-infinite-retro/v1`.
First access needs internet; the cache may not be a complete offline copy and
can grow. No automatic cache pruning is configured. Guest writes are scratch
and are not saved between sessions. NeXTSTEP software and ROMs have rights
separate from Infinite Mac's source license.
