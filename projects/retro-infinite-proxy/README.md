# Infinite Mac local asset proxy

Common source for the on-demand BeOS Release 3 and NeXTSTEP 3.3 launchers.
The launcher serves a pinned HTML shell on loopback and fetches matching
content-addressed Infinite Mac production assets from the fixed
`https://www.infinitemac.org` origin, caching them under
`~/.cache/torque-infinite-retro/v1`. It does not forward browser cookies or
credentials. Initial access to uncached files requires internet; the cache may
not contain all data needed for offline use and has no automatic pruning.

The shell pins the deployed `main-Bw9bLu8v.js` and related versioned assets.
Increment the consuming projects' release versions when changing this source.
The Infinite Mac source is Apache-2.0 licensed (see `LICENSE-infinite-mac`);
guest images, ROMs, and application software have their own rights. Saved HD and
Infinite HD are disabled; guest disk writes are scratch and do not persist.

The guest screen fills the browser without an emulated bezel. BeOS requests
640 × 480; NeXT hardware outputs 1120 × 832, scaled to fit the UNO Q display.
Alt+F4 closes the browser and its local server.
