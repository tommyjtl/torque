# Storage cleanup and bounded retention

**Date:** 2026-10-26

**Status:** Immediate cleanup completed; automatic retention proposed for discussion

The documentation refresh ran out of space while preparing a release under
`/opt/torque`. The user then requested cache cleanup and a durable way to prevent
storage from accumulating. This entry records the actual cleanup separately from
the proposed automation; no new automatic storage policy has been deployed.

## Two filesystems, two kinds of growth

The UNO Q has separate ext4 filesystems:

| Location | Filesystem size | Main Torque use |
| --- | --- | --- |
| `/` (including `/opt/torque` and `/var/lib/torque`) | 9,956 MiB, about 9.7 GiB | Installed releases, durable sessions and system data |
| `/home/arduino` | 18,324 MiB, about 17.9 GiB | Deployment/build cache, downloads and user workspace |

Free space in home cannot satisfy an allocation on `/opt/torque`. Earlier free-
space reports from a home staging folder were therefore not measurements of the
installation filesystem. The current updater checks its installation filesystem,
but its 64 MiB safety margin needs a stronger peak-space/headroom policy.

The historical workflows left eleven obsolete installed releases and many full
runtime/vendor copies in `~/.cache/torque`. Before cleanup, the home cache was
about 7.2 GiB, with about 3.4 GiB under `staging/`. The normal unattended updater
already builds at permanent release paths; it does not need those old home copies.

## Completed release cleanup

The installed `torque update gc` removed eleven validated, inactive managed
releases. It preserved:

- Current `0.2.0-51f1c6df08f3`.
- Verified rollback `0.2.0-140757cc8a97`.
- Any prepared target or live release lease under the existing policy.

Root filesystem free space rose from 228 MiB to 3,318 MiB: about 3.0 GiB
reclaimed. Both retained releases are about 294 MiB each. User projects,
configuration, credentials, controller app/default and stock fx were outside
the deletion scope. No service restart or firmware upload was needed.

## Completed home-cache cleanup

Before removing cached payloads, read-only inspection found no references from
the active/rollback runtime links, console scripts, venv configuration or `.pth`
files, running account processes, stock fx launcher, or running-container mounts.
The deployment lock was held during cleanup, and process references were rechecked.

Only known Torque payload roots carrying a valid release manifest were selected.
The cleanup removed 62 heavy `runtime`, `node_modules`, `build` and `dist`
components from expired staging/rollout copies. Source snapshots, logs, original
manifests, deployment receipts and firmware preflight data were retained. Each
affected payload received `cache-pruned.json` with `rebuild_required: true`.

Estimated allocated space reclaimed was 7,099 MiB (about 6.9 GiB). Home free
space rose from 7,435 MiB to 14,534 MiB. There were no skipped/error components.
Arduino's `.arduino15` installation/toolchains (about 2.2 GiB), vendor caches,
Docker data and personal workspace contents were not pruned.

The readable Torque cache now totals about 250 MiB. `du` cannot enter the
root-owned historical E2E `system-backup` directory, so that cache total excludes
the protected backup. It was preserved. The filesystem availability figures above
come from `statvfs`/`disk_usage` and include all allocated data, including that backup.

The application stayed ready in status mode with no foreground owner. Audit
receipts are under `~/.cache/torque/updater-docs-a31uk9y2/`:
`retention.json`, `cache-cleanup-plan.json`, and `cache-cleanup-result.json`.

The documentation/agent-instruction refresh then published successfully through
the unattended updater as `0.2.0-24c65403d19f`, with Python code and firmware
unchanged. Explicit post-publication GC kept that release plus verified rollback
`0.2.0-51f1c6df08f3` and removed the superseded `0.2.0-140757cc8a97` rollback.
That cleanup was invoked by the operator; automatic post-commit retention remains
part of the proposal below. Publication evidence is `documentation-acceptance.json`.

## Recommended next implementation

The detailed [managed-storage design draft](../design-spec/2026-10-26-managed-storage-retention.md)
now defines policy, registry/protection, per-filesystem admission, cleanup recovery,
proposed commands and acceptance. The defaults below remain proposals.

Use the existing updater rather than adding another privileged service:

1. Run release retention automatically after a verified commit, and before a
   prepare that would otherwise fail for space. Keep current plus one verified
   rollback, live leases, in-flight transactions and explicitly pinned artifacts.
2. Delete a completed temporary runtime/vendor staging payload once its permanent
   replacement is verified and has no cache references. Keep source snapshots
   for seven days and small receipts/logs for thirty days.
3. Bound Torque-managed home cache to a proposed **2 GiB**. Expire unpinned,
   abandoned prepared/incomplete builds after **24 hours**; retain source/receipt
   metadata separately. A prepared plan based on an old current release is stale
   and can be reclaimed after it is marked unusable, subject to pins/leases.
4. Require a proposed **1 GiB free on the installation filesystem after peak
   build demand**, accounting for the candidate copy and temporary Python seed.
   Check home separately for cache/source work. Prune only eligible managed
   artifacts; refuse with a report if protected data prevents meeting the floor.
5. Add storage reporting and a dry-run GC plan with bytes, reason, protection,
   filesystem and before/after availability. Use an artifact registry with owner,
   kind, lifecycle and lease/pin data; do not infer recurring deletion authority
   from arbitrary folder names or age alone.

Cleanup after a successful deployment is best effort: its failure must not roll
back a verified application or repeat service activation. It shares the updater's
existing lock and must not recursively reacquire that lock from `finish()`.
Unknown caches, user projects, credentials, conversation/session data, OS logs,
Docker images and vendor toolchains stay outside automatic deletion.

The proposed defaults are open for discussion. Sharing content-addressed immutable
Node/libfx dependency bundles is a later optimization; bounding lifecycle/retention
is sufficient before changing the runtime layout or sharing venv files.

See the [updater design](../design-spec/2026-10-25-unattended-runtime-updates.md)
and [current CLI](../cli.md#unattended-linux-runtime-updates).
