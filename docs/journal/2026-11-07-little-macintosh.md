# Little Macintosh on UNO Q

This on-demand project runs classic Mac systems in a browser on the UNO Q's
640 × 480 desktop. The local sources and release builder are in
`projects/retro-mac-uno/`; the emulators and disk material come from macemu
and Infinite Mac, with their notices included in the release. System images
and ROMs have their own rights. They are stored as local build inputs, not
committed to Torque.

## Versions

- **0.1.0** packaged System 7.5.3, a loopback-only Python web server and a
  Chromium kiosk launcher. A headless Chromium trial on the UNO Q reached the
  Finder; [the screenshot and measurements](../../projects/retro-mac-uno/evidence/0.1.0/RESULTS.md)
  record what was observed. A desktop shortcut and custom Macintosh SVG icon
  point through the board's `latest` symlink.
- **0.1.1** hid the host cursor over the fullscreen page, leaving the guest
  cursor rendered by the emulator. A headless board check verified CSS cursor
  settings and emulator initialization; no physical observation was made.
- **0.1.3** adds a GTK chooser before browser launch, System 7.5.3 and Mac OS
  8.5 images, a guest-exit callback and a touchable × to close the kiosk
  process and server. The callback needs physical shutdown testing; the × is
  a fallback for guest systems that do not report an exit event.
  Its SHA-256 manifest covers the packaged files. The image is scratch storage:
  the upstream 8.5 welcome text mentions a Saved HD, but this package does not
  mount one and changes should not be treated as persistent.
- **0.1.4** removes the floating × at the user's request. The guest-exit
  callback remains, and Alt+F4 is the fallback if the guest does not report
  an exit event. Menu-triggered exit still needs an on-device test.
- **0.1.5** fixes guest shutdown reporting. The runtime worker provides a
  `quit` callback, but the bundled Emscripten wrappers discarded it. The
  release builder forwards the quit call in both JavaScript wrappers, checking
  the exact upstream anchor before patching; the WASM and upstream checkout
  are unchanged. In separate headless Mac-hosted browser trials, selecting
  Special → Shut Down in both System 7.5.3 and Mac OS 8.5 caused the launcher
  to receive its shutdown request and exit Chromium and the server. The UNO Q
  release passed all 550 SHA-256 checks and `latest` points to 0.1.5. A
  physical touchscreen shutdown test remains outstanding. The Python suite
  passed 568 tests (15 skipped).
- **0.1.6** adds Macintosh SE with MacPaint 1.5 to the pre-launch chooser. The
  image and Mini vMac runtime are local, and the image provenance notice is
  included in the release. A headless Mac-hosted browser trial opened MacPaint
  with a blank document. After quitting MacPaint, the guest's Shut Down command
  showed the original “safe to switch off” screen instead of exiting the
  emulator, so Alt+F4 remains necessary for this SE image. Drawings are scratch
  data and do not persist reliably. The Python suite passed 568 tests (15
  skipped). All 628 release files were verified on the UNO Q before switching
  `latest` to 0.1.6. A headless browser on the board opened MacPaint and drew
  a line via simulated mouse input; [the screenshot](../../projects/retro-mac-uno/evidence/0.1.6/uno-macpaint-drawing.png)
  records that result. Physical touchscreen testing remains outstanding.
- **0.1.7** replaces the Macintosh SE/MacPaint choice with Mac OS 8.0 on a
  Quadra 650, preserving System 7.5.3 and Mac OS 8.5. Its 759 release files
  matched their checksums on the UNO Q, and a headless board trial reached the
  [Mac OS 8.0 desktop](../../projects/retro-mac-uno/evidence/0.1.7/uno-macos-8.0.png).
  `latest` points to 0.1.7. The older 0.1.6 release remains available for
  rollback. The Python suite passed 568 tests (15 skipped). Physical touchscreen
  interaction and shutdown for this image remain unverified.
- **0.1.10** mounts an additional 4 MiB HFS disk named MacPaint when launching
  Mac OS 8.0. It contains MacPaint 1.5 in the top level, derived with its
  resource fork from the 0.1.6 image by `prepare-macpaint.py`; the associated
  provenance notice is included. In the default 256-color mode, MacPaint's
  tool palette rendered blank; selecting Black & White from the Control Strip
  restored it. A headless UNO Q browser trial opened MacPaint and drew a line
  using simulated mouse input ([screenshot](../../projects/retro-mac-uno/evidence/0.1.10/uno-macos-8-macpaint.png)).
  All 763 release files passed checksum verification and `latest` was switched
  to 0.1.10. Color mode changes and drawings are scratch data and reset after
  exit; the physical touchscreen remains unverified. The Python suite passed
  568 tests (15 skipped).

Version 0.1.3's 550 files were verified on the UNO Q and `latest` was switched
to it. An isolated headless board trial of the identical 8.5 emulator and disk
from 0.1.2 reached Finder and opened the welcome notes, taking several minutes;
the [screenshot](../../projects/retro-mac-uno/evidence/0.1.3/uno-macos-8.5.png)
records the board-rendered result. In an isolated local-browser trial, the ×
sent the shutdown request and the owned Chromium process and server exited.
The guest's actual Shut Down menu triggering the callback and the GTK selector
on the physical desktop remain unverified. The full Python suite passed 568
tests (15 skipped); the required shell syntax checks passed.

## Operating boundaries

The desktop shortcut launches a user process and does not modify services,
boot defaults or MCU firmware. `latest` is switched only after a release is
copied and checked; a running instance keeps its old release until closed.
The server accepts a shutdown request only from its own localhost origin with
the expected request header, and only terminates the browser process that it
started. Alt+F4 is a fallback way to close the browser and server. Physical
touch, cursor visibility and guest shutdown must be checked on the display;
headless screenshots do not establish those observations.
