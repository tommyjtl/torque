# Unattended Linux runtime updates

**Date:** 2026-10-25

**Status:** Bootstrap complete; unattended activation verified on 2026-10-26

The user authorized implementation after choosing Codex over SSH as the first
update actor. The installed starting release is `0.2.0-7b6b751f2f9c`, with
firmware 0.4.0/protocol 1.3 and boot 2126796425. Heart Pulse is idle status;
Half Helix remains working status. No firmware change is part of this work.

The implementation adds `torque update prepare/apply/status/recover/gc`, final-
prefix venv builds, explicit source scopes, deterministic no-op identity,
source/dependency integrity, persistent admission fencing, pidfd shutdown,
atomic activation and bounded recovery. Project children inherit flock leases,
including Linux/keypad-only programs. Those leases outlive a disconnected
frontend. Read-only examples/help stay independent of daemon availability.

The stdlib administrator bootstrap validates root-owned execution configuration
and all managed trees, runs candidate builds/imports under the runtime UID,
migrates only application ownership through no-follow descriptors, and installs
the exact `NOPASSWD: /usr/bin/systemctl restart torque.service` rule. It preserves
service configuration, boot selection, input/router access, user state and
credentials. A separate permanent migration release avoids moving a built venv.

The host suite has passed 290 tests with two skips. Focused tests cover stale and
concurrent activation, busy admission, program inheritance, rollback, interrupted
receipt completion, source mutation, dependency/controller changes, retention,
unsafe filesystem graphs, sudo scope, service privilege prefixes, readiness
identity and verified pidfd signaling. A real temporary venv rebuild matched all
16 installed application modules, with all console scripts at their final paths.

Read-only audit on UNO Q validated all 11 existing managed releases. That scan
took 88.2 seconds; the one-time bootstrap repeats privileged checks before any
ownership/policy change. The UNO Q suite passed all 290 tests with four skips
for its missing host C++ compiler; the corresponding C++ checks ran on the Mac.
The native Bridge tests ran on the UNO Q against private simulated Router sockets.

## Administrator setup and vendor-policy correction

The user rebooted the board before migration; the bootstrap baseline boot was
1203245458. The first administrator run installed the update-capable
`0.2.0-140757cc8a97` app and transferred application ownership, but its global
`visudo -c` check rejected Arduino's pre-existing root-owned 0644 fragments.
The dedicated Torque restart fragment itself was valid, root-owned 0440 and
already loaded. No vendor permission was changed.

The check now validates global/include syntax through explicit
`visudo -cf /etc/sudoers`, verifies safe ownership/write permissions on every
parsed file, and retains the strict 0440 requirement for Torque's own fragment.
A regression test covers this distinction. The healthy app's fence was released
through verified bootstrap completion, then the user resumed the same setup
command to finish its root-owned marker. The resumed setup did not reinstall or
restart the app. `/etc/torque-runtime-updates.json` now reports completion.

## Real unattended activation

From noninteractive batch SSH, the normal account prepared and activated the
bootstrap correction using the installed `torque update` CLI. Transaction
`3fa1eb2ec9ef44008a90d30739f766cd` committed
`0.2.0-140757cc8a97` → `0.2.0-51f1c6df08f3` in 11.2 seconds with no password
prompt. The daemon epoch and resolved release changed. General `sudo -n true`
still required a password, proving the successful restart did not depend on a
general cached sudo grant.

Examples-only preparation returned unchanged. After activation, same-source
application preparation and repeated apply returned without another restart;
PID and epoch stayed constant. All 16 installed application modules matched
source. Firmware 0.4.0/protocol 1.3, boot 1203245458, service-unit hash, Arduino
boot default, settings/model/permissions, conversation and stock fx launcher
were preserved. Heart Pulse is playing in normal idle with no foreground owner.
No inference or firmware upload occurred, and physical LEDs were not optically
measured. Retained user-scene adoption was covered by software tests; the live
trial started in status mode and did not create a new retained scene.

Receipts live under `~/.cache/torque/unattended-6myih5wz/`, including
`unattended-acceptance.json`, `trial-applied.json`, `trial-baseline.json`, and
`software-tests-final.log`. Private transaction records are under
`/var/lib/torque/updates/transactions/`.

See the [design](../design-spec/2026-10-25-unattended-runtime-updates.md) and
[command reference](../cli.md#unattended-linux-runtime-updates).

## Documentation handoff

The repository `AGENTS.md` now directs coding agents to activate authorized
Linux updates autonomously through the configured SSH updater, with explicit
source scope, busy/recovery rules and no repeated sudo/bootstrap request.
Packaged `agent/AGENTS.md`, board troubleshooting and the workspace seed explain
that the service itself must not self-update. Existing personal workspace
instructions are preserved.

README, architecture, runtime reference, setup and CLI guides now agree on
user-owned application releases and root-owned system policy/launchers. Earlier
rollout journals and the original onboarding/E2E design carry dated follow-ups
instead of presenting historical root-only activation as current guidance.
