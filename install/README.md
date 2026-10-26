# Runtime updates and controller maintenance

## Linux application updates

The validation UNO Q completed bootstrap and a real unattended activation on
2026-10-26. Use the normal account over SSH; no further sudo activation script
or administrator bootstrap is needed for routine Linux changes:

```bash
torque update prepare --source ~/torque-src
torque update apply UPDATE_ID
torque update status UPDATE_ID
torque update recover UPDATE_ID
torque update gc
```

These commands preserve the controller, Arduino app/default, system unit,
credentials, model and permission settings. No routine Python helper runs as
root. The [CLI guide](../docs/cli.md#unattended-linux-runtime-updates) documents
source scopes, busy admission, recovery, no-op updates and retention.
Use `recover` only for an interrupted/failed transaction; `gc` is optional
maintenance, not a required step after every activation.
It currently manages installed releases only and runs explicitly. Home staging
caches need separate, reference-aware cleanup; automatic lifecycle/budget policy
is documented as a [proposal](../docs/journal/2026-10-26-storage-cleanup-and-retention.md).
The detailed [storage design draft](../docs/design-spec/2026-10-26-managed-storage-retention.md)
separates proposed automation from the commands currently installed.
Measure `/opt` and home independently when they are on different filesystems.

## Enable unattended updates once

This section is for a board that has not completed bootstrap. The validation
board is already configured. An inactive service or missing permission is reported
for explicit resolution; setup must not silently change unrelated services.

For an existing working board, first prepare this checkout's update-capable
runtime using the pre-delegation staging helper. Keep Torque idle and close old
frontends/programs during the migration; old clients predate process leases.

```bash
python3 install/update-runtime.py prepare --source . --output ~/.cache/torque/runtime-update
python3 -I install/bootstrap-runtime-updates.py --stage ~/.cache/torque/runtime-update
sudo python3 -I install/bootstrap-runtime-updates.py --stage ~/.cache/torque/runtime-update --apply
```

Preflight is the default and may take a couple of minutes to hash existing
managed releases. Protected sudo-policy checks are repeated during administrator
apply. The standalone bootstrap uses only stdlib in its privileged phase. It
builds, imports and tests application code after dropping to the runtime UID,
at a new permanent prefix. It installs the update-capable daemon, migrates only
validated application directories using no-follow descriptors, and adds:

```sudoers
arduino ALL=(root) NOPASSWD: /usr/bin/systemctl restart torque.service
```

The rule applies to the account; service children retain `NoNewPrivileges` and
cannot use sudo. The unit, launcher, system binaries, credentials, workspace,
Bluetooth/router/input access and Arduino boot default remain unchanged.
No MCU flash is involved. The administrator journal is
`/var/lib/torque-runtime-bootstrap.json`; rerun the same reviewed command after
an interrupted bootstrap. The migration release retains an identity derived
from its reviewed stage; subsequent releases use canonical input identities.

Global sudo syntax is checked with explicit `visudo -cf /etc/sudoers`; every
parsed file must remain root-owned and not group/world-writable. Existing Arduino
vendor fragments may use root-owned 0644 permissions and are preserved. Torque's
own fragment must be 0440. An interrupted setup resumes from its recorded phase;
a verified app is not reinstalled or restarted just to finish bookkeeping.

After delegation, the old `update-runtime.py` refuses prepare/apply: use
`torque update` and never sudo a user-writable application helper. For a fresh
installation, `./setup.sh --enable-unattended-updates` explicitly adds this
bootstrap after the normal full setup. Fresh setup retains its existing
controller-install authorization requirements; do not use it for a Linux-only
update on a working board.

To revoke delegation, an administrator removes only the dedicated
`/etc/sudoers.d/torque-runtime-restart` rule and bootstrap marker. This does not
stop or reflash the board; restoring root ownership is a separate deliberate
maintenance action.

## Deliberate controller maintenance

The source installer, release manifest, and post-upload verification share
firmware **0.4.0 / protocol 1.3** through `torque_bundle.py`. A staged bundle
with another identity is rejected before installation. An explicitly requested
upgrade can start from controller 0.2.0, 0.3.0, or 0.4.0; another identity is reported
for inspection. The setup installer remains the full onboarding workflow.

For a controller/runtime update on an already working UNO Q, use
`stage-controller-update.py` and `update-controller.py`. Preparation does not
activate the release, change services, or flash. It copies the existing matched
release, preserving its engine/dependencies, overlays the new firmware, Python
packages, installer, and Dot Matrix Animations example, builds the packages in
that private copy, and verifies a successful pinned firmware compile.
Credentials and user configuration remain outside the release.

Run preparation on the UNO Q from this source checkout:

```bash
python3 scripts/prepare-controller.py --resolve
python3 install/stage-controller-update.py \
  --compiled .cache/base-controller \
  --output ~/.cache/torque/controller-update
python3 install/update-controller.py --stage ~/.cache/torque/controller-update
```

Use a new output directory for each preparation. The updater also accepts the
isolated compile snapshot layout used for the first grayscale deployment:
`firmware/uno-q/controller/` and `build/*.bin` beneath `--compiled`.
No model request is made. Preparation may download normal Python build tools;
its package installation is confined to the staged virtual environment.

Only after a deliberate request to replace the MCU sketch and restart Torque:

```bash
sudo python3 install/update-controller.py \
  --stage ~/.cache/torque/controller-update --apply
```

The preflight checks release hashes, compiled artifacts, old firmware identity,
the active app, the existing boot-default path, and the absence of an active
turn or device program. The update keeps that stable app path, service unit,
boot selection, and access settings. It saves the previous runtime and controller
sources, activates the matching runtime, starts/verifies the new MCU controller,
then checks Torque readiness. It does not automatically reflash after an error.
Missing administrator/router permissions or inactive services are reported.

Readiness polling belongs to the updater itself. Older staged `system.py`
modules need only the original `run`, `app`, `verify_stage`, and `copy_release`
functions; missing required helpers are reported before activation. A valid
completed receipt plus matching live firmware makes a repeat invocation return
`already_applied` without flashing or restarting, including when run via sudo.

The result is written to `applied.json` in the stage. This proves command and
framebuffer state, not that a person observed the physical LEDs. New example
files are copied to `~/torque/projects/dot-matrix-animations/` for explicit use.
If that folder contains another version or edited files, a fresh folder with
the release ID appended is selected during preflight; user files are preserved.
The update does not start the animation program.
