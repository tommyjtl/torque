# Little Macintosh for UNO Q

Version 0.1.11 is an experimental, on-demand classic desktop, with a native
chooser for System 7.5.3, Mac OS 8.0, Mac OS 8.5, or BeOS Release 3 before
Chromium opens.
It uses the macemu WebAssembly runtime based on Infinite Mac/Basilisk II.
The ROM and system image are separate from the emulator source license. The
disk is scratch storage; changes are not guaranteed to persist.

Build on the Mac with `python3 build.py` after preparing the adjacent
`retro-mac-browser` checkout. Each release has a SHA-256 file manifest. Do not
overwrite a release that might be under test; increment VERSION in `build.py`
before building another. The board copy is under
`~/torque/projects/retro-mac-uno/releases/0.1.11/`.
The board's `latest` symlink points to the chosen release, currently `0.1.11`.
Its **Little Macintosh** desktop shortcut uses that symlink, so updating the
link after validating a new release updates the shortcut as well. The SVG icon
and desktop entry are kept alongside this README for maintenance.

On the board, from its graphical desktop terminal, run `bash launch.sh` in
the release directory. The page requests kiosk exit when the emulator reports
guest shutdown. If the guest does not emit that event, Alt+F4 closes Chromium
and its local server.
The server
listens on the board's loopback port 18791 only. This is not an Arduino app
and does not start, stop, or flash the MCU. It does not install a service or
enable automatic launch. The launcher's separate browser profile is under
`~/.local/share/torque-retro-mac/`.
The page hides the Linux cursor while the pointer is over the emulator. The
Macintosh's own pointer remains part of the emulated display.
Mac OS 8.0 mounts a separate MacPaint disk, with the MacPaint application in
its top level. Before opening it, choose **Black & White** from the display
color control in the bottom-left Control Strip: its tools do not render
properly in the 256-color mode. The setting resets when this scratch system
disk is restarted. Both disks use scratch storage: changes are not persistent.
The disk was constructed by `prepare-macpaint.py` using `machfs` from the
locally sourced macemu MacPaint image; see `NOTICE-macpaint.md` for provenance.

BeOS uses a separate Infinite Mac emulator and a local cache under
`~/.cache/torque-infinite-retro/v1`. Uncached assets are fetched from
infinitemac.org on demand, so first use needs internet; the cache may not be a
complete offline copy. BeOS writes are scratch and are not saved after exit.

The bundle contains a copy of the macemu license and its emulator notices.
The builder forwards the bundled Emscripten wrappers' quit callbacks to the
existing worker hook; it does not modify the upstream checkout or the WASM.
