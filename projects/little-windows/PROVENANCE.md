# Provenance

`libv86.js`, `v86.wasm`, BIOS binaries and the Windows 2000 initial state were
downloaded from the official [v86 demo](https://copy.sh/v86/) and its image
host. The local launcher and cache are independent project code. The v86
source is at https://github.com/copy/v86 and its BSD license is included.

Disk pieces are obtained on demand from the official demo host `i.copy.sh`:
`windows95-v3`. The image contains proprietary Microsoft
Windows software. Their distribution and use are governed by their own rights;
the v86 code license does not license Windows. The disk cache is local to the
user's board, excluded from Git, and not a distribution package.

`windows95-local-640.zst` is a derived v86 state created from the public
Windows 95 demo after selecting 640 × 480 and dismissing startup dialogs.
The older 0.1.2 release also contains a derived Windows 2000 state; that option
was removed in 0.1.3 after an unsuccessful guest restart test.
