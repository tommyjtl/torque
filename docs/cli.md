# Torque command reference

This guide covers the current Torque CLI, checked against its implementation and
the validation board's installed help on 2026-10-26. Torque is the user command;
stock `fx` remains a separate application with its own commands and settings.

The validation board has model/reset, revised Ctrl-C behavior and unattended
Linux updates installed. See the [Linux-only update workflow](../install/README.md)
for first-time bootstrap on another board.

## Start a conversation

On the UNO Q:

```bash
cd ~/torque
torque
```

From your Mac:

```bash
ssh -t arduino@tommy-uno-q.local 'cd ~/torque && torque'
```

Describe the outcome at the Torque prompt:

> Light up the entire LED matrix now.

Then:

> Turn it off.

You can also ask for a program, such as “Make a heart blink for ten seconds.”
The agent chooses the implementation and creates files when needed. Routine
matrix on/off/pattern requests use direct board tools and retain the requested
state. They do not require a Python file or a firmware upload.

Interactive Torque continues the latest conversation if one exists. If a turn
is already active, it first attaches to that work. The configured workspace is
normally `/home/arduino/torque`, regardless of the shell directory from which
you launch the chat.

## Shell commands

Run these at the Linux shell, outside the interactive Torque prompt.

| Command | Purpose |
|---|---|
| `torque` | Open interactive chat; continue the latest conversation |
| `torque ask "PROMPT"` | Submit one prompt in a new conversation, display its result, then exit |
| `torque ask --resume "PROMPT"` | Continue the latest conversation with one prompt, then exit |
| `torque attach` | Observe the current/latest turn and respond to pending approvals without resending its prompt |
| `torque cancel` | Request cancellation of the active turn |
| `torque model` | Pick a Modular model interactively |
| `torque model list [--refresh] [--json]` | Discover/list models without inference |
| `torque model use MODEL_ID` | Save a model for subsequent turns, preserving conversation history |
| `torque model test MODEL_ID` | Run small billable text/tool compatibility probes |
| `torque reset [--blank] [--json]` | Cancel work and restore managed matrix/RGB outputs |
| `torque status` | Show model, workspace, device readiness, session outcome and permission mode |
| `torque status --json` | Print the detailed local state as JSON |
| `torque doctor` | Show the same readiness summary, with connection-error guidance when unavailable |
| `torque doctor --json` | Print the same detailed local state as `status --json` |
| `torque device snapshot` | Read the current firmware snapshot, including matrix/RGB state, as JSON |
| `torque device health` | Read firmware uptime, command/result counters and telemetry queue/drop diagnostics as JSON |
| `torque run SCRIPT [ARGS...]` | Run an existing Python program under the configured workspace's `projects/` directory |
| `torque example` | List bundled examples and their launch modes; works without the daemon |
| `torque example SLUG [ARGS...]` | Run a bundled reference example with its manifest defaults |
| `torque example --mode MODE SLUG [ARGS...]` | Select a manifest mode, such as offline preview or Linux LED status |
| `torque update prepare --source CHECKOUT [--scope application\|examples]` | Build and check a frozen Linux release without activating it |
| `torque update apply UPDATE_ID` | Activate a prepared release after exclusive admission |
| `torque update status UPDATE_ID` | Read a local transaction record, including while the daemon is stopped |
| `torque update recover UPDATE_ID` | Finish verified bookkeeping or restore the previous runtime |
| `torque update gc` | Reclaim validated unused releases, keeping current, rollback and leased releases |
| `torque --help` | Show top-level command syntax |
| `torque COMMAND --help` | Show syntax for a subcommand, such as `ask`, `device` or `run` |

There is one active model turn at a time. If another is running, attach to it or
request cancellation before submitting a new prompt.

### One prompt and a follow-up

```bash
torque ask "Light up the entire LED matrix now"
torque ask --resume "Turn it off"
```

`--resume` selects the latest conversation; the current CLI does not accept a
session ID or offer a session picker. An interactive conversation is convenient
when you expect several follow-ups.

### Run a saved program

For an existing script, replace the example path and arguments with its own:

```bash
cd ~/torque
torque run projects/heart/main.py
torque run projects/heart/main.py 10
```

The script path is resolved from your current shell directory and must be under
the configured workspace's `projects/`. Torque uses its managed Python
interpreter, runs with the script's directory as the working directory and
forwards trailing arguments to the program. No environment activation is needed.

`torque run` directly executes the program you selected. It does not make a model
request or show the agent's tool-approval prompts. Board programs use the public
Python API, `from torque import Board, Frame`.

### Run a bundled example

The manifest-driven catalog lists the bundled examples. List examples, then
run one by its stable slug, from any shell directory:

```bash
torque example
torque example dot-matrix-animations
torque example dot-matrix-animations --frame-ms 40
torque example state-observer
```

| Slug | Default behavior | Extra mode |
|---|---|---|
| `linux-rgb-led` | Cycle the Linux user RGB LED, restoring its original state | `status` reads LED state |
| `mcu-rgb-led` | Cycle MCU LED 3, then request off | — |
| `matrix-patterns` | Display the heart and orientation border, then clear | — |
| `matrix-animation` | Play three buffered column sweeps | — |
| `state-observer` | Observe snapshots/events for fifteen seconds without changing outputs | — |
| `dot-matrix-animations` | Run the nine-preset Keychron/gallery example | `preview` generates SVGs offline |

For the dot-matrix gallery, keys **1–9** select continuous loops and **Escape**
exits. Without a readable Keychron it plays three finite gallery rounds and
exits. The default frame time is 25 ms. Resident-preset firmware/SDK 0.4.0
preloads the clips once for fast switching.

The gallery uses shared `torque.input.Keypad` discovery and the project input
lease. One verified matching keypad is selected automatically; several require
`--keyboard-address "<KEYPAD_BT_ADDRESS>"` using local discovery. A busy lease or
an unavailable explicit selection reports an error before taking matrix ownership.
No personal Bluetooth address is packaged in a preset, example or skill.

Heart Pulse is also available by name, without a number-key binding. The
default live gallery still uses nine presets; offline preview includes all ten.
To match the idle status animation:

```bash
torque example dot-matrix-animations --animation heart-pulse --peak 5 --frame-ms 50 --repeat 3
```

Launcher options go **before the slug**. Everything after the slug belongs to
the example's own argument parser:

```bash
torque example --mode preview dot-matrix-animations
torque example --mode status linux-rgb-led
torque example dot-matrix-animations --animation echo-ring --repeat 2
torque example dot-matrix-animations --animation crt-glide --repeat 2
torque example dot-matrix-animations --input terminal
torque example dot-matrix-animations --help
```

Listing, example help, and preview work without a running daemon. Hardware
modes report missing readiness/capabilities through existing checks. They do
not start services, alter permissions, start an Arduino app, flash firmware,
or make model requests. Linux LED modes use the Linux processor; MCU examples
use the resident controller through the public Torque API.

Reference files ship inside the selected Python package. Generated output and
the child working directory are under `WORKSPACE/projects/examples/SLUG/`,
normally `~/torque/projects/examples/SLUG/`. The reference stays read-only.
Mode defaults precede forwarded arguments; explicit script options can override
ordinary argparse defaults. No Python environment activation or versioned
project-folder path is needed. Editable variations still belong in `projects/`
and run through `torque run`.

From the Mac, allocate a terminal for terminal-input mode:

```bash
ssh -t arduino@tommy-uno-q.local 'torque example dot-matrix-animations --input terminal'
```

### Add an example to the catalog

Add `examples/<folder>/main.py` and an `example.toml` alongside it:

```toml
schema_version = 1
slug = "my-animation"
title = "My animation"
description = "A short description for the example list."
entrypoint = "main.py"

[modes.run]
args = ["--play", "--output-dir", "{output_dir}"]
requires = ["daemon", "matrix-grayscale"]

[modes.preview]
args = ["--output-dir", "{output_dir}"]
requires = []
```

The script defines its own argparse options, including safe `--help` handling
before hardware access. Add or change those options in the script; there is no
second argument definition in the launcher. The manifest contains launch
defaults and requirements, not executable hooks. Requirement names other than
`daemon` are queried as controller capabilities. Optional inputs such as the
Keychron stay the example's responsibility.

`{workspace}` and `{output_dir}` are the only argument substitutions. Use doubled
braces for literal braces in defaults. Read bundled assets relative to
`__file__`; write generated files to the output directory. Ordinary local helper
files/assets are bundled automatically, excluding hidden files and build caches.
Entry/resource paths must stay inside the example folder, and slugs must be
unique. Firmware replacement utilities such as `idle-sketch` stay outside this
catalog.

The build discovers manifests and includes them in the wheel and source
distribution. Adding a folder and manifest needs no Python registry, manual
index, or launcher change. It becomes available when that next Torque release
is installed. Python callers use the same catalog:

```python
from torque import examples

catalog = examples.discover()
examples.run("dot-matrix-animations", mode="preview")
```

## Interactive commands

Type these inside `torque` at its `›` prompt:

| Command | Purpose |
|---|---|
| `/help` | Show the supported interactive commands and policy guidance |
| `/new` | Make the next prompt start a new conversation |
| `/status` | Print detailed local status as JSON |
| `/model` | Choose a model; `/model list`, `/model use ID` and `/model test ID` also work |
| `/reset` | Cancel active work and restore standby; `/reset --blank` retains a blank matrix |
| `/exit` or `/quit` | Leave the frontend |

Ctrl-C during a turn cancels that turn and its Torque-managed programs, resets
the managed matrix/MCU RGB outputs to standby, then returns to the chat prompt.
At an empty/partially typed chat prompt, Ctrl-C clears
the input. `/exit`, `/quit` or Ctrl-D leaves chat. An SSH disconnect can still
leave accepted background work running. To reconnect or request a stop from
another shell:

```bash
torque attach
torque cancel
```

Cancellation requests a stop; it does not undo completed tool effects. Attach
shows the available buffered output and may report a gap for older output.
Cleanup can take a few seconds. In one-shot `ask` or `attach`, Ctrl-C stops work,
resets outputs and returns to the Linux shell. `torque cancel` remains the
explicit cancellation-only command. Interrupting a reset view leaves its bounded cleanup
running in the daemon; inspect status afterward.

## Choose a model

```bash
torque model
torque model list --refresh
torque model use google/gemma-4-31b-it
torque model test google/gemma-4-31b-it
```

The picker marks the current model. Listing uses the authenticated Models API
with a one-hour owner-only cache and stale/offline fallback. It makes no inference
requests. Being listed is separate from passing a tool compatibility check.
Configured models use curated metadata; new IDs receive a clearly marked
experimental profile with vision disabled and a conservative 16,384-token client
budget, not an advertised context-window claim. Tool support remains unverified
until tested. No model is silently substituted when discovery/inference fails.

Selection is saved for subsequent turns, including follow-ups. It preserves
history and needs no sudo/service restart. Finish or cancel an active turn before
changing models. Use `/new` for a fresh conversation. `model test` uses a temporary
in-memory session and a harmless nonce tool, with bounded requests/tokens/time;
it does not change your selection/history or operate hardware. Use `--json` with
`list`, `use` or `test` for structured results.

## Reset managed outputs

```bash
torque reset
torque reset --blank
```

Reset cancels active work and pending approvals, stops managed programs and
matrix playback, turns MCU RGB LEDs 3/4 off, and verifies readback. Default reset
restores standby; `--blank` retains an all-zero matrix instead. An independently
launched program still owning the device is reported busy rather than killed.
The Linux user RGB LED is reported unmanaged/skipped in this version.

Reset preserves projects, skills, conversation history, credentials, model choice,
permissions, resident animation clips and firmware. It does not reboot or restart
services. Partial failures are reported per component with a nonzero exit status;
uncertain writes are not automatically replayed. Ctrl-C during active agent work
uses this standby reset. Use `torque cancel` to stop work without requesting an
additional output reset.

## Permissions

The installed default is `auto`. You can choose a policy when launching chat or
submitting a one-shot prompt:

```bash
torque --permissions auto
torque --permissions ask
torque ask --permissions ask "Show a heart"
torque ask --permissions auto "Light up the entire LED matrix"
```

| Mode | Behavior |
|---|---|
| `auto` | Validated board actions, bounded reads, project writes and workspace Python execution proceed automatically; advanced shell commands require approval |
| `ask` | Effectful agent tools require approval for the exact action |
| `full` | Explicit turn/session choice without human approval prompts; tool validation, device ownership and OS permissions still apply |

To explicitly select full mode, the syntax is `torque --permissions full` or
`torque ask --permissions full "PROMPT"`. Auto is normally sufficient for routine
board use. A one-shot override does not change the configured default for future
commands. A policy selected when opening chat applies to prompts in that chat.
Auto is a tool-authorization policy, not an OS sandbox.

An approval prompt accepts `y` for that exact action; other answers deny it.
Noninteractive clients deny actions that require approval, so use an interactive
terminal when expecting such requests. `ssh -t` supplies that terminal remotely.

## Readiness and maintenance

`status`, `doctor` and device queries do not make model requests. Device-ready
means local controller infrastructure is available; it does not establish that
cloud authentication or network access will succeed. Device state is firmware
framebuffer/GPIO evidence, not optical observation.

When the matrix is available for session status, normal standby loops Heart
Pulse (1.4 seconds per double beat) and active work loops Half Helix (0.96
seconds per cycle). Approval waiting and errors keep their static symbols.
Retained drawings and foreground programs take priority. Ctrl-C/reset leaves
the steady standby dot with playback stopped; normal animation resumes at the
next status transition or explicit `matrix_release`. The gallery's 25 ms frame
default is independent of these cues. See the
[status animation design](design-spec/2026-10-25-status-animations.md).

The CLI's `doctor` command currently reports local state rather than running a
separate comprehensive diagnostic suite. If the daemon is unavailable, inspect:

```bash
systemctl status torque.service --no-pager
```

Installation and controller updates use deliberate setup workflows. See the [setup guide](../README.md#set-up-from-a-checkout),
[controller update guide](../install/README.md),
[architecture](../ARCHITECTURE.md) and
[runtime validation record](torque-runtime.md).

## Unattended Linux runtime updates

This workflow is enabled and verified on the validation UNO Q as of 2026-10-26.
It completed a real batch-SSH update without a password prompt. Do not repeat
bootstrap or use a sudo activation script for routine updates on that board.

After the administrator [bootstrap](../install/README.md), updates run as the
ordinary board account over SSH, outside `torque.service`. The bootstrap makes
application releases user-owned and delegates only the fixed Torque restart
command. It preserves the root-owned service/launcher and `NoNewPrivileges`.
Firmware installation remains a separate explicit workflow.

```bash
torque update prepare --source ~/torque-src
torque update apply UPDATE_ID
torque update status UPDATE_ID
```

Preparation returns the update ID, base and target. It builds Python at the final
release path, validates installed/source parity, console scripts, offline example
previews and the existing native libfx bundle. It does not activate the release,
open a second controller observer, reset outputs or make a model request. The
default `application` scope includes the selected checkout's application files;
freeze/review that checkout before preparing. For example data/manifests only:

```bash
torque update prepare --source ~/torque-src --scope examples
```

The examples scope uses the active application's code and dependencies. An
identical resulting source/dependency identity returns `unchanged` without a
restart. New Python/Node/device-SDK dependencies or a different controller bundle
require a separately reviewed update; they are not repaired automatically.

Apply refuses active turns, approvals, model operations, reset, device owners and
managed programs. It never cancels them to make room. `torque run` and live example
children inherit a shared process lease, including Linux/keypad-only programs;
that lease survives a frontend disconnect until the child exits. Listing, help,
offline previews and read-only example status remain usable without the daemon.
Programs started outside these launchers are outside the managed-project guarantee.

Activation is serialized, checks its expected base, fences new writes/work,
stops the verified service process as its normal UID and switches `current`
atomically. The only sudo operation is the exact password-free Torque restart.
Readiness must identify the intended release/version, a new daemon epoch and
systemd invocation, with unchanged MCU boot, configuration and user settings.
Retained user output is adopted through existing readback rather than replayed.

Interrupted SSH/signals and failures leave private records under
`/var/lib/torque/updates`. Use `recover UPDATE_ID`; an already verified target is
finalized without repeating activation. Failed startup restores the previous
release. If the selected CLI itself cannot start, use the saved base interpreter:

```bash
/opt/torque/releases/BASE_RELEASE/runtime/python/bin/python -m torque.cli update recover UPDATE_ID
```

`gc` preserves current, its rollback, prepared targets and releases with live
leases. It also recognizes this updater's incomplete builds. Unknown or modified
release trees are skipped. It does not remove user projects, credentials or
unrelated cache folders. See the
[runtime-update design](design-spec/2026-10-25-unattended-runtime-updates.md).

GC is currently explicit; it is not an automatic post-deployment hook and does
not prune `~/.cache/torque` staging payloads. Root and home are separate
filesystems on the validation board. The
[storage cleanup journal](journal/2026-10-26-storage-cleanup-and-retention.md)
records the one-time cache audit/cleanup and proposed automatic budgets/expiry.
The [storage design draft](design-spec/2026-10-26-managed-storage-retention.md)
specifies the proposed implementation; its new flags/commands are not current CLI features.

The [model/reset design](design-spec/2026-10-25-model-selection-and-device-reset.md)
records the control boundaries and acceptance criteria.

If terminal lines appear staggered or run together, restore the terminal's line
settings with `stty sane` in the Mac shell before reconnecting. This affects that
terminal, not board services or SSH security settings.
