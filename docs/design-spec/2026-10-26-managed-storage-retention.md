# Managed storage and automatic retention

**Date:** 2026-10-26

**Status:** Draft for review. The cleanup journal records completed manual work;
the policy, commands and hooks below are proposed and are not enabled yet.

## Problem and intended result

An application documentation update could not prepare because `/opt/torque` was
nearly full. Home still had several GiB available, but it is a different filesystem.
Manual cleanup reclaimed roughly 3 GiB of obsolete releases and 6.9 GiB of old
deployment payloads. The [cleanup journal](../journal/2026-10-26-storage-cleanup-and-retention.md)
contains the measurements, reference checks, preserved data and receipts.

Normal updates should reclaim their disposable artifacts without another manual
cleanup session. Keep the active application, one verified rollback, recovery
evidence and anything in use. Before building, account for peak allocation on
each actual filesystem and leave operating headroom. If protected data prevents
a safe build, report the problem before allocating a candidate or stopping work.

This extends the [unattended Linux updater](2026-10-25-unattended-runtime-updates.md).
It requires no firmware, Arduino app/default, system-unit, group, sudo-policy or
vendor-service change. Mutating housekeeping runs as the runtime account through
the external SSH updater, outside `torque.service`. No new daemon or scheduled
privileged task is introduced in the first version.

## Current implementation and gaps

| Existing behavior | Change needed |
| --- | --- |
| `Updater.gc()` holds the deployment lock and protects current, rollback and release-use leases | Reuse its protection rules and expose a common planner/executor |
| GC is an explicit command | Add post-commit and low-space prepare hooks |
| Every `prepared` transaction protects its target forever | Define stale/expired/discarded states and reference-aware reclamation |
| `prepare()` requires a release-sized copy plus 64 MiB | Estimate peak allocation and preserve a larger filesystem-specific floor |
| Normal builds create venvs at permanent paths | Retain that layout; do not reintroduce moved venvs or duplicate home staging |
| `smoke-*` and bootstrap smoke scratch live under update state | Put future disposable scratch in registered home cache and retire known completed scratch |
| Legacy cache cleanup used a one-time manifest/reference audit | Register new artifacts at creation; do not turn that audit into an arbitrary directory-name sweeper |
| The deployment journal already survives interruption | Journal cleanup separately so an interrupted delete never repeats activation |

Implementation starts from [update.py](../../packages/session/src/torque/update.py)
and [runtime.py](../../packages/session/src/torque/runtime.py). Application source,
installed artifacts, borrowed checkouts, durable state and caches remain distinct.

## Scope and exclusions

Automatic deletion is limited to validated Torque-managed application releases
and registered artifacts created by Torque's update/build tooling. Registry
membership alone is insufficient: identity, location, ownership, lifecycle and
protection must all pass at execution time.

Always exclude user projects/custom skills/workspace instructions, credentials,
model settings, conversations/session storage, the deployed controller app,
stock fx and its history, OS logs, Docker data, `.arduino15` and vendor caches.
Do not chmod/chown protected or inaccessible data to make cleanup succeed.

The root-owned historical E2E `system-backup` remains an opaque protected backup.
It is not an ordinary cache entry and gets no automatic expiry. Its deletion
would require a separate explicit administrator maintenance decision.

## Proposed defaults

Use binary units: GiB = 2^30 bytes, MiB = 2^20 bytes. Defaults are proposals for
the validation board, not claims of a universal device storage layout.

| Policy | Default | Meaning |
| --- | --- | --- |
| Verified installed history | Current + one rollback | Keep additional releases while leased, pinned or required by an in-flight operation |
| Installation headroom | 1 GiB | User-available free space remaining after estimated peak build allocation |
| Cache-filesystem headroom | 512 MiB | Independent floor for additional cache/temp allocations |
| Managed home-cache budget | 2 GiB | Evict eligible artifacts to approach this limit; never override a protection to meet it |
| Completed temporary runtime/vendor payload | Eligible immediately | Permanent replacement is verified and no runtime/process/container reference remains |
| Unapplied prepared candidate | 24 hours | Unpinned, unused candidate may expire; an in-flight activation never expires by age |
| Failed/incomplete build | 24 hours | No producer lease or recovery reference; only recognized updater-created builds qualify |
| Managed source snapshot | Up to seven days | May be evicted earlier under budget pressure; borrowed original checkouts never qualify |
| Unreferenced receipts and logs | Thirty days | Keep current/rollback/recovery anchors and referenced records regardless of age |
| Individual transient build log | 5 MiB, two rotations | Bound output without keeping unlimited copies |

Pins and leases are stronger than age/budget limits. A protected set may exceed
2 GiB; report the excess and refuse additional allocations when necessary.
Do not call a budget satisfied by omitting inaccessible data. Cache reporting
distinguishes measured managed bytes, visible unknown bytes and opaque paths.
Filesystem availability comes from `statvfs`, independent of inventory visibility.

User overrides live outside releases in proposed
`~/.config/torque/storage.toml`, owned by the account with mode 600. Missing file
uses versioned defaults. Invalid keys/values stop mutation with an explanation.
Policy changes cannot disable ownership/path checks, current/rollback protection,
leases or in-flight recovery protection. An upgrade never overwrites user policy.

## Storage roots and artifact ownership

| Root | Use |
| --- | --- |
| `/opt/torque/releases/` | Permanent managed applications and incomplete candidates |
| `~/.cache/torque/managed/` | New source snapshots, downloads and build/smoke scratch |
| `/var/lib/torque/updates/storage/` | Private registry, policy diagnostics and cleanup journals |
| `/var/lib/torque/updates/transactions/` | Deployment records and essential recovery references |

Root paths come from the verified installation/account configuration. Do not
hardcode block-device names or infer that `/opt` and home share space. Group
allocations by the current `st_dev`; mount identity is rechecked on each run.

Artifact kinds are `release`, `build_work`, `temporary_payload`, `source_snapshot`,
`download`, `receipt` and `log`. A release's own runtime, wheels and vendor
directories belong to that release; they cannot be evicted as standalone cache.
New caches use disjoint deletion roots. Never delete a parent that contains
protected child artifacts.

The registry uses private atomic JSON records, one per artifact, recording:

- Schema, artifact ID, kind, creator and configured root plus relative path.
- Owner UID and captured device/inode/type identity for the root entry.
- Creation/completion time, lifecycle, expiry, last actual use and measured bytes.
- Deployment/release/source identity and incoming/outgoing protection references.
- Pin/reason, producer/use lease, cleanup phase and the last outcome.

No credentials, environment dumps, conversation content or arbitrary user-file
contents belong in this registry. Store normalized paths and artifact metadata.
Reading a report does not refresh age or last-use timestamps.

Register an allocated artifact before populating it, and mark it complete only
after its producer succeeds. Producer crash leaves a recognized incomplete entry.
Use shared inherited artifact-use descriptors for managed consumers; acquire an
exclusive artifact lease before reclamation. Keep existing release-use leases
and the global deployment/program admission locks.

`--source CHECKOUT` is borrowed input, even when it happens to sit under `.cache`.
Never enroll it for deletion merely because of its location. Only a snapshot
created and recorded by Torque is managed. The prepare flow leases its managed
inputs and records references until the candidate no longer needs them.

Legacy releases can be enrolled after full manifest/path/owner validation.
Unregistered legacy cache directories remain report-only by default. A separate
explicit adoption plan can use release manifests plus runtime, process, console-
script, venv, stock-fx and container-reference inspection. Missing inspection
access is a protection/report condition, not proof that a path is unused.
The one-time cleanup's `cache-pruned.json` markers remain historical evidence.

## Protection and transaction expiry

Calculate a protection graph under the existing deployment lock. It includes:

1. Resolved `current` and its last verified rollback.
2. Every artifact referenced by the active transaction, recovery or a producer.
3. Live release/artifact leases and pinned artifacts.
4. Unexpired prepared candidates and their managed source/build inputs.
5. Minimal deployment records proving those heads/references and cleanup recovery.

Retain a small verified-head anchor independently of ordinary receipt expiry, or
retain the referenced head receipts in full. Never expire the only record from
which the current GC derives its rollback. If that proof is missing/corrupt,
protect the uncertain releases and report repair instead of guessing.

Prepared targets become `expired` at their deadline or `superseded` when their
expected base has been replaced by a committed update. Persist that state before
reclamation. A pin can preserve their bytes but cannot make a stale plan apply.
Multiple transactions may reference the same canonical target; deletion requires
that all remaining references permit it.

An active fence, stopped service, partially activated update or recovery record
does not expire by age. Unsupported/corrupt records fail closed. If timestamps
are inconsistent or the clock moves behind creation, skip age-based deletion
and report the uncertainty.

After receipt expiry, an old ID must report that it has expired and perform no
activation. Recoverable/in-flight IDs and required head anchors never age out.

## Space admission on the correct filesystem

Use user-available bytes (`f_bavail * f_frsize`), not total free/reserved blocks.
Report both allocated bytes and logical size, but estimate a full copy using a
conservative logical upper bound; sparse-file allocation must not be understated.

For each filesystem, estimate additional peak demand from:

- The new permanent release copy and source/package build outputs.
- The extra fresh Python environment while its old dependency seed still exists.
- Temporary wheel/log/preview work, filesystem metadata and a measured allowance.
- Managed source/download allocations on the cache filesystem.

For each device require:

```text
available_before >= additional_peak_demand + applicable_headroom
```

When install/cache roots share a device, sum concurrent allocations once and use
the larger floor; do not double-count free space or sum independent safety floors.
Future build `TMPDIR` and smoke scratch use registered private cache directories
rather than leaking unbounded scratch under durable state or assuming `/tmp`
tmpfs has capacity. Continue building the venv at its permanent prefix.

Perform this check before allocating a candidate and before any admission fence,
signal or service restart. If short, plan and reclaim only eligible artifacts on
the constrained filesystem, then remeasure once. Deleting home data cannot fix
an installation-filesystem shortage. Refuse with required/available bytes and
protection reasons if the floor is still unmet. Recheck before later large build
phases; concurrent outside allocations can still cause ENOSPC, which leaves a
recoverable incomplete candidate and never forces deletion of protected data.

## Planner, executor and interruption safety

Introduce one shared planner returning keep/remove/skip entries with ID, kind,
path, filesystem, estimated bytes and reason. Reports distinguish policy expiry,
budget eviction, stale plan, unknown ownership, use/pin/recovery protection and
opaque/unregistered data. A dry-run makes no lifecycle, registry or deletion
changes and does not signal/fence the service.

Execution regenerates or revalidates the plan under the deployment lock and
exclusive artifact leases. A saved plan is evidence, not authority to delete
paths later without rechecking. Revalidate configured-root containment, lstat
identity/UID/type, ancestry and all references immediately before each action.
Use no-follow directory descriptors and do not traverse symlinks or mount/bind
boundaries. Refuse special files or unexpected hardlinks. Never repair access
through chmod/chown or new privilege grants.

Journal each deletion intent before acting. Move an eligible artifact into a
private trash area on the same filesystem, persist the phase, then remove it
without following links. Do not move home artifacts into root-filesystem trash.
Resume a recognized partial deletion by its recorded identity after interruption.
Unknown trash entries are reported, not swept. When retaining a partial parent
such as source/receipts beside a temporary payload, delete only registered
components and leave an explicit rebuild/pruned marker.

Before deleting candidate bytes, persist transaction expiry/discard state.
Before pruning an old receipt, preserve required head/reference information.
Dry-run/reporting does not initialize missing storage state just to inspect it;
if a consistent lock cannot be acquired, report busy/partial inventory.

## Lifecycle hooks and failure semantics

Refactor `Updater.gc()` into lock-aware planner/executor helpers shared by manual
GC, low-space prepare and post-commit housekeeping. `finish()` currently executes
inside `store.lock()`; it must not call the public lock-acquiring `gc()` recursively.

After durable verification/commit and release of the daemon fence, invoke bounded
best-effort cleanup under the owned lock, protecting the just-selected rollback.
Cleanup may run while the new service operates; it must not touch active/leased
artifacts or cancel projects. Record cleanup results separately from activation.

A verified update remains `committed` if housekeeping fails. Record a warning/
pending cleanup outcome and retain a successful update exit status; never roll
back or repeat restart to retry cleanup. Explicit GC can report its own I/O error.
Unchanged prepare and repeated completed apply do not repeat activation or
unnecessarily rerun cleanup; explicit GC can retry it independently.

Candidate/source/cache operations are registered before work and finalized in
success/failure paths. Cleanup is opportunistic on updater operations in v1;
no always-running timer is promised. An idle board with no updates has no new
background storage worker.

## Proposed operator interface

Only `torque update gc` exists today. The additions below are part of this draft:

```bash
torque update storage
torque update storage --json
torque update gc --dry-run
torque update gc
torque update pin ARTIFACT_ID --reason "keep for investigation"
torque update unpin ARTIFACT_ID
torque update discard UPDATE_ID
```

`storage` reports per-filesystem availability and complete/partial inventory,
effective policy, current/rollback, eligible bytes and protected/opaque paths.
`discard` applies only to unused prepared work; active or interrupted activation
requires `recover`, not discard. Pinning cannot bypass admission or path safety.
GC retains its structured JSON outcome for automation. No routine command uses
sudo, restarts Torque, or makes a model request just to report/prune storage.

## Implementation and rollout

1. Add a standard-library `torque.storage` policy/inventory/planner layer and
   tests. Initially expose reporting/dry-run without deletion.
2. Integrate verified installed-release protection, prepared expiry/discard,
   incomplete-build cleanup and peak-space admission into the existing lock.
3. Add bounded post-commit cleanup with independent receipts; test it cannot
   change a successful activation into rollback or cause another restart.
4. Register new managed source/build/download/smoke artifacts and inherited
   use leases; add cache budget/expiry/pins. Keep unknown/legacy data excluded.
5. Review a real board dry-run and exercise only registered disposable fixtures.
   Deploy through the existing external SSH updater, with no new admin setup.
6. Verify a documentation-only update, repeat/no-op behavior and resulting
   current/rollback/cache use. Update CLI/setup/AGENTS guidance and the journal.

Defer shared dependency stores, mutable hardlink deduplication, moving the
installation to another partition, general OS/Docker cleanup and session-history
retention. Two normal installed releases were about 588 MiB after cleanup;
lifecycle bounds should be established before changing that layout.

## Acceptance

Software checks must cover:

- Root low/home high, shared-device roots, peak seed/build demand and reserve
  blocks; no candidate/service effects when admission cannot meet the floor.
- Current/rollback anchors, absent/corrupt head proof, leases surviving frontend
  exit, pins, producers and in-flight recovery overriding budgets/age.
- Stale and expired plans, two records sharing a target, discard and protection
  of borrowed source paths, workspace, credentials, sessions and vendor data.
- Unknown/opaque roots, path/symlink/mount/hardlink/UID swaps and registry/path
  mismatches; a changed artifact is skipped rather than guessed safe.
- Dry-run causing no storage-state writes, correct reason/byte totals and a
  budget that remains visibly unmet when all excess data is protected.
- Two deployers/GC workers, source use during preparation, no recursive-lock
  deadlock, clock anomalies, permission errors and ENOSPC during cleanup.
- Crash before/after trash rename, partial deletion and receipt compaction;
  only the matching operation can resume it.
- A committed update surviving cleanup failure, plus no-op/repeated apply
  retaining PID/epoch and never reactivating to retry housekeeping.

On UNO Q, record filesystem measurements and the dry-run plan, then expire/prune
registered throwaway artifacts. Confirm current plus verified rollback remain
bootable, no live managed project is interrupted, and firmware boot, Arduino app/
default, system-unit/launcher/policy, model/settings and existing user data remain
unchanged. No hardware demo, inference, reboot or firmware upload is needed for
this acceptance; physical LED observation is separate from software evidence.

Proposed defaults are ready for review. This document authorizes no additional
cleanup and does not claim the automatic policy has been implemented.
