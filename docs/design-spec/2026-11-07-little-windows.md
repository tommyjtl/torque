# Little Windows on UNO Q

## Purpose

Provide an on-demand desktop shortcut for the 640 × 480 UNO Q display that
opens Windows 95 in a browser. It is independent
of the Little Macintosh project and the Torque service. It does not change
boot defaults or start, stop, or flash an Arduino app.

## Version 0.1.3

`projects/little-windows/` contains the launcher, Python
loopback server, browser page, icon, build script and source/provenance notes.
`~/Desktop/Little-Windows.desktop` calls `~/torque/projects/little-windows/latest/launch.sh`;
the relative `latest` symlink points to a checksummed versioned release.
Chromium uses a dedicated user profile. Alt+F4 closes Chromium and the server.

The page runs the official v86 WebAssembly runtime. The prepared Windows 95
startup state is derived from v86's public demo and configured to 640 × 480.
The emulator's base disk parts are fetched from the fixed v86 image host and
cached under `~/.cache/little-windows/v86-images-v1`. The server binds only to
loopback, accepts only aligned ranges from the Windows 95 disk path, and
validates each part's length before writing the cache. First access to uncached
parts requires internet; the cache is not guaranteed to be a complete offline
copy and may grow as additional disk areas are accessed. No automatic pruning
is configured. The guest has no configured network relay.

## Data and rights

The current guest disk overlay lives only in browser memory. Changes, files,
and display settings made during a session do not persist when it ends. A
startup snapshot is not a user-data backup. Do not present the demo as having a
persistent hard disk. Windows 2000 was removed from the current launcher after
an isolated restart test failed; the older release and caches are retained.
Windows is proprietary; v86's
BSD license does not convey rights to Windows images. The sources and derived
states are described in the project's `PROVENANCE.md` and excluded from Git.

## Verification and open work

On 2026-11-07, all 11 release files matched their SHA-256 manifest on the board.
A headless UNO Q trial launched Windows 95 directly at 640 × 480; an earlier
trial's [Windows 95 screenshot](../../projects/little-windows/evidence/0.1.2/uno-windows95.png)
shows the same prepared desktop. The previous release also tested
[Windows 2000](../../projects/little-windows/evidence/0.1.2/uno-windows2000.png).
These trials do not establish touchscreen, physical-screen, GUI responsiveness,
or guest-shutdown behavior. Guest persistence, offline completeness and
touchscreen input need separate design and validation before being promised.
