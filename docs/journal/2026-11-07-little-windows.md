# Little Windows first rollout

Built and copied the separate `projects/little-windows` 0.1.2 release to the
validation UNO Q, verified its 13 file hashes, and installed the Little Windows
desktop shortcut and a `latest` symlink. The existing Torque service remained
active. No service, firmware, Arduino app, or boot setting was changed.

Both public v86 Windows demos initially displayed at 1024 × 768. In isolated
Mac-hosted trials, the guest display settings were changed to 640 × 480, and
new initial VM states were saved. Separate headless board trials restored each
prepared state at 640 × 480. Windows 95's first uncached cold boot was slow;
the prepared state avoids that boot path. Touch, physical visibility, and
performance during real use have not been checked. Screenshots and remaining
limitations are linked from the [design](../design-spec/2026-11-07-little-windows.md).

The image cache and derived startup states contain proprietary Windows data;
provenance is in the project. They are local-only runtime artifacts excluded from
Git. The cache is populated on demand from v86's public host, so internet is
needed for uncached data. User changes are scratch and do not survive closing
the browser. A Mac-hosted experiment that rebooted the Windows 2000 demo after a
settings change failed to start due to an unavailable or corrupted system
registry file; guest restart is not an accepted workflow. Closing and reopening
restores the prepared snapshot.

## Windows 95-only release

At the user's request, 0.1.3 removes the Windows 2000 choice after that failed
restart test. Since only one guest remains, the shortcut now launches Windows
95 directly rather than presenting a chooser. It does not delete the older
release, snapshot or cache. All 11 release files passed SHA-256 verification;
an isolated headless UNO Q launch reached the 640 × 480 Windows 95 desktop.
The desktop shortcut was validated, `latest` was switched to 0.1.3, and Torque
remained active. Physical touchscreen interaction is still unverified.
