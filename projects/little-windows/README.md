# Little Windows for UNO Q

An on-demand browser-based Windows 95 experiment using v86.
The runtime is served from the board at `localhost:18794`; disk image pieces
are fetched on demand from v86's public demo CDN and cached under
`~/.cache/little-windows/v86-images-v1`. First use of an uncached disk area
requires internet. The cache is not a complete offline copy and may grow as
the system accesses more of the image. Windows 95 uses a locally prepared
640 × 480 startup snapshot stored in the release.

Guest disk writes are scratch: **changes and files do not persist across
restarts**. Do not store important data in the guest. The v86 code is
BSD-licensed; the hosted Windows demo images are proprietary Microsoft
software with separate rights. Their presence on the public demo does not
establish permission to redistribute them. See `PROVENANCE.md`.

Build with `python3 build.py`, then deploy a new numbered release and point
the board's `latest` symlink at it. From the desktop, open the Little Windows
shortcut to start Windows 95 directly, and use Alt+F4 to exit. No boot-time or service
settings are changed. The current version does not provide guest networking.
