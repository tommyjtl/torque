# Torque runtime implementation

The current component, firmware-layer, boot and data-ownership reference is
[ARCHITECTURE.md](../ARCHITECTURE.md). This page retains implementation decisions
and validation history.

| Verified bundle | Evidence |
|---|---|
| `0.1.0-f39b997888b0` | Fresh privileged install, same-bundle reinstall, Linux reboot, pre/post-boot agent and MCU checks |
| `0.1.0-9271b389ad23` | Default auto policy, direct hardware tools, retained on/off state, ask denial, natural program execution and same-boot restart adoption without actuator replay |
| `0.2.0-140757cc8a97` | Administrator bootstrap, user-owned application layout, fixed restart grant, protected root-owned service/launcher |
| `0.2.0-51f1c6df08f3` | Actual noninteractive SSH activation without a password; new release/epoch, no-op and repeat checks, preserved settings/firmware/default/stock fx |

As verified on 2026-10-26, the controller/SDK is **0.4.0 / protocol 1.3**, with
grayscale frames and nine resident preset slots deployed. Idle uses Heart Pulse;
working uses Half Helix. See the
[controller guide](../firmware/uno-q/controller/README.md) for its release boundary.
Physical visibility remains a separate human observation.

## Current Linux update workflow

The validation board has completed unattended-update bootstrap. For authorized
Linux changes, the normal account runs `torque update prepare/apply/status/recover`
over SSH outside the service. Do not request another sudo activation script on
this configured board. `gc` is available for validated unused managed releases.
The service/launcher/policy remain root-owned; application releases are user-owned.
The running Torque agent retains `NoNewPrivileges` and does not self-update.

See [CLI usage](cli.md#unattended-linux-runtime-updates),
[bootstrap and recovery](../install/README.md), and the
[verified rollout](journal/2026-10-25-unattended-runtime-updates.md), including
the vendor sudoers-mode correction. Fresh controller installation, firmware
maintenance and reboot E2E remain separate explicit operations. The remaining
sections retain evidence from earlier installation/harness milestones.

## Engine decision

Use the unmodified native `libfx@0.0.14` addon with a private Node 24.22.1 runtime.
The stock `fx` binary and its global configuration/history remain separate.

The [native FX runtime option](journal/2026-10-24-native-fx-runtime-option.md)
records a future ACP/MCP alternative, current resource measurements and the
acceptance needed before considering a switch. The selected runtime remains
Node/libfx.

The stock ACP server provides useful events and checked tools, but its 0.0.14
profile paths are tied to `~/.fx`. The selected library integration provides
private configuration and session storage without faking HOME. Torque supplies
host tools, validates their arguments and enforces authorization before effects.
The library's instrumentation never grants permission.

The first pilot required approval for shell commands and file writes. The
installed 9271b389ad23 update superseded that policy with default auto and explicit
ask/full turn/session choices; see [current authorization](../ARCHITECTURE.md#requests-authorization-and-output-lifetime).
Torque owns this policy rather than inheriting stock FX's automatic reviewer.

The ARM64 proof made five small Modular requests. It verified native backend,
MiniMax M3.1 Flash, managed and user skill instructions, one actual `uname -m`,
a denied write with no shell effect, durable context across agent recreation,
no repeated tool effect, real turn/model/tool/wait hooks, unchanged global FX
settings and no API key in session state. Peak sampled process RSS at the end
of that proof was 119 MiB; this was not a continuous peak measurement.

A subsequent staged daemon/client turn independently requested an approval,
ran exactly `uname -m`, returned `aarch64`, loaded all three packaged skills,
and emitted the expected engine hooks. The validation daemon's sampled RSS
while waiting for an unavailable controller was about 24 MiB. These measurements
do not establish the installed system's ready/active memory budget.

## Runtime and deployment reference

Architecture details have moved to the root document:

- [Runtime components and communication](../ARCHITECTURE.md#runtime-components-and-communication).
- [Authorization and retained display ownership](../ARCHITECTURE.md#requests-authorization-and-output-lifetime).
- [Firmware layers and Zephyr loader/sketch relationship](../ARCHITECTURE.md#the-firmware-and-software-layers).
- [Boot and coordinated deployment](../ARCHITECTURE.md#boot-and-deployment).
- [Installed paths and user ownership](../ARCHITECTURE.md#installed-paths-and-user-ownership).

The following records describe the actual tested milestones, rather than a
compatibility promise for every newer source revision.

## Verification

Host unit tests cover denial and exact approval binding, symlink/path isolation,
key redaction, sanitized shell environments, bounded output/events, interruption,
workspace preservation, artifact tampering and exclusive device ownership.
Existing firmware/state/codec tests remain in the same suite.

`install/verify.py` is read-only by default. Its explicit flags authorize only
small model checks and finite device tests. The agent test detaches the submitting
client before observing the same turn. Hardware tests use an independent reader,
shared event observer and a competing writer which must be denied. The combined
test asks the agent to write/run a finite matrix program and checks its actual
framebuffer output. No permission mode is disabled.

Software framebuffer and GPIO checks are separate from a person looking at the
board. The fresh-install E2E separately verified reboot into the selected controller
and a fresh SSH launch. The natural-language rollout separately verified
retained-state adoption across a daemon restart.

Sources: [ACP server](https://fx.sh/docs/using-fx/acp),
[libfx Node runtime](https://fx.sh/docs/lib/node),
[host tools and authorization](https://fx.sh/docs/lib/tools),
[durable sessions](https://fx.sh/docs/lib/durability),
[skill loading](https://fx.sh/docs/lib/skills),
[FX 0.0.14 profile paths](https://github.com/vercel-labs/fx/blob/v0.0.14/src/core/shared/profile_paths.zig).

## Pilot installation retry and hardware evidence

The first administrator attempt copied the release but stopped before firmware,
startup selection or service installation: its restricted subprocess PATH omitted
`/usr/sbin`, so it could not find the installed `runuser` binary. The installer now
resolves required system executables explicitly, checks them before installation
changes, and verifies the requested normal-user execution context. It does not
install another copy of util-linux or weaken sudo/SSH configuration.

Live deployment checks also covered App CLI's `apps: null` empty-list response
and its misleading `default: false` process-list field for an external app.
The authoritative `properties get default` FullPath is checked separately from
the running app ID. Matching deployed source, startup path and live firmware
identity allow a retry to reuse the prepared controller without another upload.

The controller was prepared as the normal board user at
`/var/lib/torque/device/uno-q/controller`, with firmware 0.2.0, protocol 1.1 and
new boot ID 1689392559 verified. The startup property points at that stable path.
The source checkout and existing Matrix Heart app were preserved.

The staged daemon then passed the combined opt-in verifier: actual `uname -m`,
submitting-client detach, lifecycle and approval events, independent framebuffer
readback, denial of a competing device writer, shared telemetry, and restored
status ownership. The model wrote and ran a finite heart program under the user
workspace without uploading firmware. An independent final read confirmed the
exact standby framebuffer, playback stopped, both MCU RGB LEDs off via GPIO
readback, no pending approvals, no output owner, queue depth zero and zero dropped
MCU events. Credential availability was checked without printing the key.

Reports are private board-local artifacts under `~/.cache/torque/`, including
`controller-preparation.json` and `full-verification.json`. These were software
observations from the earlier milestone. Later
[fresh-install E2E](fresh-install-e2e.md) completed the system-service boot checks;
physical visibility remains a separate observation.

Installation currently needs a terminal on the board, either SSH or a local
terminal. Sudo is required only for system installation. A laptop launcher can
hide the manual login step by using an SSH TTY for the private prompts; it does
not remove the one-time administrator authorization. A setup with no SSH transport
would require a local provisioning interface or a preinstalled Torque image.

## Earlier harness milestone

The [plain-language control journal](journal/2026-10-24-natural-language-control-and-approvals.md)
records the installed update, the original user interaction, literal on/off
acceptance with zero routine approvals, explicit ask denial, automatically chosen
program implementation and the restart-probe correction. The final restart-only
check preserved the blank frame and MCU boot with actuator counter **45 → 45**.
No actuator command was replayed. The service remained enabled/active after
removal of the legacy `~/projects` directory; the current workspace is `~/torque`.
