# Torque

**A small agent with reach.**

Torque is a resident agent project for programmable hardware. The vision is an
agent you can ask to program its own device, operate your home, work on GitHub
pull requests, and carry out other tasks through tools and CLIs. A physical
interface shows its work and gives you a way to interact with it.

The first platform is the Arduino UNO Q: a Qualcomm Linux processor runs the
agent and tools, while an STM32 MCU controls board hardware. Models run through
[Modular Cloud](https://docs.modular.com/quickstart). The current foundation uses
the unmodified [libfx](https://fx.sh/docs/lib) engine inside Torque, shared
base-controller firmware, and a coordinated Python device API. Torque is the working name for the broader project.

Read [ARCHITECTURE.md](ARCHITECTURE.md) for the firmware layers, runtime
components, boot sequence, installed paths and source layout.

## Why libfx

Torque reuses the unmodified fx engine through libfx while owning its terminal,
session controller, tool policy and device interface. Cloud inference leaves the
board available for local programs and I/O. See the
[component boundaries](ARCHITECTURE.md#runtime-components-and-communication).

## What we're building

- **Our own agent harness and session controller**, with model execution, tool
  activity, user input, and visual feedback connected through clear interfaces.
  Reuse the verified libfx engine while owning the Torque application.
- **A device that can develop new capabilities:** generate, run, inspect, and
  revise programs on the device using tools and CLIs.
- **An agent controller with reach:** extend the toolset to home services,
  GitHub workflows, and other systems accessible through command-line tools.
- **A visible, interactive session:** start with LED matrix feedback, then add
  a TFT and physical controls using the same session model.

Read the [project vision and architecture](docs/design-spec/2026-10-24-torque-vision.md)
for the responsibilities, event/control boundaries, and open decisions.

## Current status

| Component | State |
|---|---|
| Agent and model access | Native libfx 0.0.14 with Modular; ARM64 model/tool/denial/session checks passed. Stock fx remains available separately. |
| Board control | Controller/SDK 0.4.0 / protocol 1.3 deployed: MCU RGB LEDs, binary/grayscale matrix frames, resident animation presets, snapshots and async telemetry. |
| Display design | Local [Session Studio](tools/session-studio/index.html) with editable regions, animation frames, and simulated event replay. |
| Torque harness and live session feedback | Implemented daemon/client with real engine events, automatic routine-tool policy, explicit approval modes and retained user display state. Idle uses Heart Pulse; working uses Half Helix. Fresh installation/reboot and agent/hardware E2E passed. Studio layouts remain separate. |
| Linux runtime updates | Verified normal-account `torque update` over SSH after one administrator bootstrap; exact restart grant, admission fencing, release checks and recovery. |
| Grayscale | Controller/SDK 0.4.0 / protocol 1.3 deployed. The [Dot Matrix Animations example](examples/06-dot-matrix-animations/) has nine keypad presets plus Heart Pulse by name. |
| TFT/DSI, physical agent controls, home and GitHub adapters | Experimental or planned; integration choices remain open. |

The installed user command is `torque`. This is Torque’s own terminal frontend,
powered by libfx; stock `fx` keeps its separate settings and history. See
[the runtime implementation notes](docs/torque-runtime.md) for verified results
and version boundaries.

## Roadmap

This is an implementation sequence, with no committed release dates.

| Stage | Status | Deliverable |
|---|---|---|
| Foundation | Implemented | Modular-backed fx, board skills, shared firmware, Python control, snapshots, and telemetry. |
| 1. Onboarding and readiness | Initial implementation verified | Fresh install, readiness diagnostics, deliberate deployment and actual reboot passed. Public release/bootstrap and a laptop launcher remain separate work. |
| 2. Torque harness and session contracts | Initial implementation verified | libfx worker, daemon/CLI, typed tools, permission modes, session persistence and retained output ownership. |
| 3. Matrix session feedback | Basic live cues; Studio integration pending | Connect real events to display regions; deploy matched grayscale firmware/SDK and selected animation families. |
| 4. TFT and interactive controls | Later | Choose display/input hardware; show richer session information and route answers, approvals, and cancellation to the active session. |
| 5. External CLI workflows | Later | Select and implement useful home and GitHub PR workflows through explicit CLI adapters; report their activity and outcomes through the same session model. |
| 6. Repeatable device-software iteration | Later | Generate and revise device programs and tools with reviewable changes, verification, and recovery to a working version. |

The initial integrated milestone has passed real model/tool turns, permission
checks, MCU readback and restart adoption. Richer regional display composition
and physical session controls remain the next integration work. See the
[vision](docs/design-spec/2026-10-24-torque-vision.md#existing-foundation-and-next-milestone)
and [animation reference review](docs/design-spec/2026-10-24-animation-reference-review.md).

## Hardware

See the [bill of materials](docs/bom.md) for the required Arduino UNO Q and
additional hardware, with in-use/planned status, product links and prices.

## Requirements

An initialized Arduino UNO Q running Debian Linux ARM64, network access, a
Modular key, Bash and Python 3.11 or newer. Arduino Router, App CLI and Arduino
CLI come from the board setup. An administrator step installs the normal-user
service and selects the controller at boot.

You do not install uv or activate a virtual environment. Setup stages private
Python and Node environments without upgrading unrelated system software.

Setup currently runs in a terminal on the UNO Q, reached through SSH or an
attached local terminal. Sudo is used for initial installation and optional
unattended-update bootstrap. After bootstrap, application releases are user-owned;
the service, launcher and restart policy remain root-owned. Everyday usage and
authorized Linux updates run as the normal board user.
A laptop launcher could automate the transfer and SSH connection while showing
the hidden key/password prompts, so users would not need to log in manually.
That launcher is not implemented yet. Setup with no SSH transport would need a
local device interface or a preinstalled image.

## Set up from a checkout

**Source/deployment boundary:** controller/SDK 0.4.0 / protocol 1.3 is deployed
on the validation board, along with model/reset, input, example and unattended
update commands. Editing the checkout does not alter the running board; use
`torque update` to deploy subsequent authorized Linux changes. See the
[update guide](install/README.md) and
[installed-versus-source snapshot](ARCHITECTURE.md#installed-system-versus-source-checkout).

Transfer a reviewed checkout to the board, then run:

```bash
bash setup.sh
```

Setup reads the key through a hidden terminal prompt. For this pilot board,
`bash setup.sh --reuse-fx-key` privately imports the existing owner-only Modular
credential. Never supply the key on the command line. `--replace-key` prompts for
a replacement; `--model MODEL_ID` chooses a visible known model.

The installer discovers models using the key, selects a compatible default,
builds a versioned release, compiles the pinned controller without uploading,
and seeds `~/torque` without overwriting user instructions, projects or skills.
It then invokes the concrete sudo installation step. `--stage-only` stops before
that administrator step and prints its exact command.

System installation can stop the prototype controller and upload the selected
0.4.0 firmware. It deploys to a stable app path and selects that app for startup.
A normal agent launch or program does not upload firmware. Arduino App CLI may
compile/load/upload when starting the selected app, including at boot.

After installation and a successful readiness check:

```bash
cd ~/torque
torque
```

See the [Torque command reference](docs/cli.md) for all shell and interactive
commands, follow-up prompts, permissions, reconnecting and running saved programs.

Torque ships the reference examples in its Python package:

```bash
torque example
torque example dot-matrix-animations
torque example --mode preview dot-matrix-animations
```

Each example owns an `example.toml` manifest and its own argument parser.
New examples are discovered and bundled automatically; the launcher needs no
per-example argument definitions. See [the manifest guide](docs/cli.md#add-an-example-to-the-catalog).

A first prompt:

> Light up the entire LED matrix now.

Then: “Turn it off.” Direct on/off/pattern tools retain the requested display
until changed or explicitly released; ordinary control needs no Python file.
For an actual program, describe the outcome, such as “Make a heart blink for ten
seconds.” The agent chooses the implementation and uses the managed environment.

Default `auto` policy permits validated board tools, bounded reads, project writes
and Python programs under `projects/`. Advanced shell commands require approval.
Auto is a tool-authorization policy, not an OS sandbox: programs execute with the
normal board user's OS access. Use `--permissions ask` for explicit approvals or
`--permissions full` for an explicit turn/session choice without human prompts;
argument/path validation and output ownership still apply. Modes are not a
global permission bypass and a full-mode turn does not change the next default.

```bash
torque ask --permissions auto "Light up the entire matrix"
torque ask --permissions ask "Show a heart"
```

In the updated CLI, Ctrl-C stops active work, resets managed outputs to standby
and returns to chat; `/exit` leaves
the frontend. SSH disconnects can still leave accepted work running, and
`torque attach` observes it without resending the prompt. `torque cancel` requests
cancellation from another shell. `/new` begins a conversation.
Noninteractive clients deny requests which need approval.

Use `torque model` or `/model` to choose a model, and `torque reset` or `/reset`
to restore managed outputs. See the [command reference](docs/cli.md) and
[Linux update workflow](install/README.md).

```bash
torque doctor
torque status --json
torque device snapshot
torque run projects/heart/main.py
```

## Installed data and boot

The managed runtime is separate from the user workspace at `~/torque`.
`torque.service` runs as the normal board user; the selected Arduino app starts
our MCU sketch. Ordinary prompts use RPC without a firmware upload.

See [firmware layers](ARCHITECTURE.md#the-firmware-and-software-layers),
[boot and deployment](ARCHITECTURE.md#boot-and-deployment),
[display ownership](ARCHITECTURE.md#requests-authorization-and-output-lifetime)
and [installed paths](ARCHITECTURE.md#installed-paths-and-user-ownership).

## Verification and maintenance

Read-only verification uses the installed Python environment:

```bash
/opt/torque/current/runtime/python/bin/python /opt/torque/current/install/verify.py
```

Opt-in checks make small model requests and run finite matrix demonstrations:

```bash
/opt/torque/current/runtime/python/bin/python /opt/torque/current/install/verify.py \
  --exercise-agent --exercise-device
```

That verifier selects ask policy and approves only its exact `uname -m`, generated
source, and finite program execution; it does not switch off checks. It also verifies shared telemetry,
exclusive device ownership, client detach, and actual GPIO/framebuffer evidence.
Physical visibility needs a person looking at the board.

The real [fresh-install E2E](docs/fresh-install-e2e.md) passed on the UNO Q,
including pre/post-reboot model, permission, generated-program and hardware
checks. Its opt-in runner is `python3 install/e2e.py prepare`; it archives only
managed installation data and requires one sudo authorization.

Firmware changes belong to a coordinated release installation, with the previous
app/default recorded and a verified new boot. Keep user projects and credentials
when replacing runtime files. Keep appropriate recovery artifacts. There is no public curl bootstrap or
published Torque release yet; the project repository is `tommyjtl/torque`.

## Repository layout

Linux runtime updates can run over SSH without another password prompt after
the explicit administrator [bootstrap](install/README.md#enable-unattended-updates-once).
Use `torque update prepare/apply/status/recover` as the normal account. The
delegation permits only the fixed Torque restart command; firmware remains a
separate workflow. See [CLI usage](docs/cli.md#unattended-linux-runtime-updates).

See the [source structure in ARCHITECTURE.md](ARCHITECTURE.md#source-structure).
Implementation evidence lives under `docs/`; future proposals live under
`docs/design-spec/` and are distinct from shipped behavior.

## Design specs

- [Model selection and device reset](docs/design-spec/2026-10-25-model-selection-and-device-reset.md)
  defines model discovery/picking, conservative profiles for new models,
  compatibility checks and a hardware reset to standby or blank. Implemented in
  source and installed; subsequent Linux changes use the coordinated updater.

- [Torque installation and runtime refactor](docs/design-spec/2026-10-24-torque-runtime-and-onboarding.md)
  defines the daemon, managed runtime and user workspace, boot readiness,
  coordinated firmware updates, and targeted cutover. Implementation status
  is tracked in the runtime notes.

- [Torque vision and architecture](docs/design-spec/2026-10-24-torque-vision.md)
  records the broader agent/controller scope, ownership of the harness, CLI
  integrations, physical feedback and control, and open implementation decisions.

- [Animation reference review](docs/design-spec/2026-10-24-animation-reference-review.md)
  assesses all 90 Dot Matrix gallery entries, with primary 5×5 and compact 3×3
  references for eight-level adaptations now used by the example and status cues.

- [Matrix pixel art, fonts, and animations](docs/design-spec/2026-10-24-matrix-graphics-and-fonts.md)
  proposes description-driven pixel assets, direct grid editing, local bitmap
  fonts, and Python-streamed marquees without image-processing dependencies.

- [Session display studio](docs/design-spec/2026-10-24-session-display-studio.md)
  explores separate display regions for session, model, tools, attention, and
  connection signals. Open the [local HTML designer](tools/session-studio/index.html)
  to edit layouts, paint animations, and rehearse simulated events.

- [Controller telemetry](docs/design-spec/2026-10-24-controller-telemetry.md)
  defines read-only snapshots, GPIO readback, asynchronous state events, and a
  live observer, implemented and tested end to end in version 0.2.0.

- [UNO Q base controller](docs/design-spec/2026-10-24-base-controller.md) records
  shared MCU firmware and a Python client for LEDs, matrix images, and buffered
  animations. Version 0.2.0 has passed deployment and LED/matrix checks on the
  validation board.

- [Grayscale deployment and Half Helix playback](docs/journal/2026-10-24-grayscale-half-helix.md)
  records the 0.3.0 rollout, readiness-helper recovery, and exact live framebuffer
  verification. The saved updater now owns readiness polling and detects completed updates.

- [Unattended runtime updates](docs/design-spec/2026-10-25-unattended-runtime-updates.md)
  implements user-owned application releases and an exact service-restart grant
  for Codex over SSH, with admission fencing, release checks and recovery.
  Bootstrap and a real password-free activation passed on 2026-10-26; see the
  [rollout record](docs/journal/2026-10-25-unattended-runtime-updates.md).

- [Managed storage and retention](docs/design-spec/2026-10-26-managed-storage-retention.md)
  drafts automatic cleanup, protected rollback/leases, root/home budgets and
  peak-space admission. The manual cleanup is complete; this policy is not enabled yet.

- [Configurable fx hardware feedback](docs/design-spec/2026-10-24-fx-hardware-feedback.md)
  proposes showing harness activity on the matrix, with user-selected states and
  themes, a small fx integration, and future RGB or TFT outputs.

## Project journal

- [2026-10-26: Storage cleanup and retention proposal](docs/journal/2026-10-26-storage-cleanup-and-retention.md)
  distinguishes root/home storage, records reclaimed obsolete releases and
  staging payloads, and proposes bounded automatic retention.

- [2026-10-26: Unattended Linux updates verified](docs/journal/2026-10-25-unattended-runtime-updates.md)
  records bootstrap, the vendor-policy correction, a real password-free SSH
  activation, unchanged firmware/defaults, and no-op/repeat behavior.

- [2026-10-24: Compact DSI display investigation](docs/journal/2026-10-24-compact-dsi-display.md)
  records the experimental Waveshare 2.8-inch DSI candidate, compatibility gaps,
  current board kernel, alternatives and next checks.

- [2026-10-24: Plain-language control and approvals](docs/journal/2026-10-24-natural-language-control-and-approvals.md)
  records the original eight-approval matrix session, four product priorities,
  and the uncoached acceptance gate and implementation progress.


- [2026-10-24: Keychron K0 Max Bluetooth setup](docs/journal/2026-10-24-keychron-k0-max-bluetooth.md)
  records pairing, Linux input surveys and wake-assisted reconnection checks.

- [2026-10-23: Python control of the matrix through Bridge](docs/journal/2026-10-23-bridge-matrix.md)
  records the deferred design for uploading matrix firmware once and changing
  patterns from Python, including runtime questions and the validation plan.

- [2026-10-23: Empty fx shell arguments during the LED demo](docs/journal/2026-10-23-fx-empty-shell-arguments.md)
  records the rejected calls, required argument shape, suggested recovery, and
  unresolved model/provider/client boundary.

## Development checks

Host checks use Python 3 and Bash; the firmware state-machine test also uses a
C++17 compiler when available. No key, cloud requests, or hardware are needed:

```bash
python3 -m unittest discover -s tests -v
bash -n setup.sh scripts/doctor.sh
```

CI also runs ShellCheck. Actual sketch compilation requires the board's Arduino
core/libraries; physical LED observation and firmware upload are separate checks.
Installing `packages/device/` together with this project enables the additional native Bridge integration test,
which uses a private simulated router socket without actuating hardware.

## License

Torque's original source and documentation use the [Apache License 2.0](LICENSE).
See [NOTICE](NOTICE) for attribution. Dependencies and upstream reference
materials retain their respective licenses and notices.

See [validation results and boundaries](docs/validation.md) for checks actually
run, including the distinction between compilation and physical observation.

References: [fx skills](https://fx.sh/docs/capabilities/skills),
[fx custom connections](https://fx.sh/docs/configure-fx/custom-model-connections),
[UNO Q manual](https://docs.arduino.cc/tutorials/uno-q/user-manual/), and
[Arduino App CLI](https://github.com/arduino/arduino-app-cli).
