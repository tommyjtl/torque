# BeOS and NeXTSTEP on UNO Q

## Goal and packaging

Add BeOS Release 3 to the Little Macintosh chooser and provide NeXTSTEP 3.3
through a separate Little NeXT desktop shortcut. Both are on-demand user
processes: they do not start an Arduino app, modify firmware, install a service,
or alter boot defaults. Existing Little Macintosh releases remain available.

Little Macintosh 0.1.11 contains its existing system images plus a copy of the
common proxy and adds BeOS to the chooser. Little NeXT 0.1.0 contains its own
copy of that proxy, pinned HTML shell, license and launcher; it does not depend
on the Little Macintosh release. Each project has checksummed, numbered
releases selected by its `latest` symlink. Alt+F4 closes the relevant browser
and server. Launching a later release does not alter an already-running one.

## Runtime and data

The shared source lives in `projects/retro-infinite-proxy/`. A fixed HTML shell
pins the Infinite Mac production asset names; a loopback-only Python server
retrieves those assets and their disk chunks from the fixed Infinite Mac HTTPS
origin. It does not forward browser cookies, credentials, or arbitrary request
headers. Files are cached in `~/.cache/torque-infinite-retro/v1`, shared by the
two launchers; the first request for an uncached asset needs internet. The cache
is not necessarily a complete offline image and may grow; no automatic pruning
is configured. Upstream assets might eventually disappear, so the pinned shell
and cache are not a guarantee of long-term availability.

Infinite Mac's source is Apache-2.0, but the operating-system images, ROMs, and
applications have separate rights. The disk images are not bundled in the
repository. Infinite HD and Saved HD are disabled; guest disk writes are
scratch and are not promised to persist. The server only fetches fixed-origin
GET resources; it does not act as a general network proxy for either guest.

## Display and acceptance

BeOS runs on an emulated Power Macintosh 7300 through DingusPPC at 640 × 480.
NeXTSTEP uses the Previous NeXTstation emulator, whose native display is
1120 × 832 and is scaled down to fit 640 × 480. Thus NeXTSTEP text will be
small. The host pointer is hidden over the guest screen. Headless desktop
screenshots establish emulated output, not a person's physical observation,
touch accuracy, normal-session performance, guest shutdown, or persistence.
Both emulators require relative mouse input; upstream handles touch as a
trackpad gesture rather than an absolute tap-to-position interface. Physical
touchscreen usability must be assessed separately.

The first tested UNO Q NeXTSTEP boot reached its desktop after roughly nine
minutes; cached or subsequent boot times have not been measured. BeOS also
reached its desktop in an isolated headless board trial. See the
[rollout journal](../journal/2026-11-07-beos-nextstep.md) for evidence.
