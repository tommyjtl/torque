# BeOS and NeXTSTEP rollout

Selected BeOS Release 3 on a Power Macintosh 7300 and NeXTSTEP 3.3 on a
NeXTstation Turbo Color. The implementations and resource boundaries are in
the [design](../design-spec/2026-11-07-beos-nextstep.md).

Both reached their desktops in isolated Mac-hosted browser trials. The BeOS
0.1.11 release was copied to the UNO Q and its 766 file hashes matched; an
isolated headless UNO Q trial reached the BeOS desktop at 640 × 480
([screenshot](../../projects/retro-mac-uno/evidence/0.1.11/uno-beos-r3.png)).
The NeXT 0.1.0 release was also copied and its five files verified. An isolated
headless UNO Q test reached the [NeXTSTEP desktop](../../projects/little-next/evidence/0.1.0/uno-nextstep-3.3.png)
after roughly nine minutes on its first tested boot. Its emulated display is
1120 × 832 scaled to fit 640 × 480, and the text is correspondingly small.
Physical touch and screen visibility are not yet observed. The Little
Macintosh `latest` symlink was switched to 0.1.11 after its BeOS test. A
separate Little NeXT shortcut and `latest` symlink were installed and the
desktop entry validated; test browser processes and ports were closed.

Both guests fetch uncached Infinite Mac assets on demand into a local cache.
Guest writes are scratch, no cache retention policy is installed, and neither
launcher changes Torque services, boot defaults or firmware. The Python suite
passed 577 tests (15 skipped), including a local proxy cache test; shell syntax
checks passed.
