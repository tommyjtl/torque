# Keypad input for agent-built projects

**Date:** 2026-10-25, America/Los_Angeles

## Implementation

The user requested a design spec and implementation so Torque can consider the
paired Keychron as input when building games and interactive projects. An explicit
autoplay request must still produce autoplay. The
[design](../design-spec/2026-10-25-keypad-project-input.md) records the scope.

Added:

- [`torque.input`](../../packages/session/src/torque/input.py): verified device
  discovery, project leases, press/release/repeat events, held state, overrun
  resync and disconnect cleanup. Python standard library only.
- [`uno-q-input`](../../agent/skills/uno-q-input/SKILL.md): automatically discoverable
  guidance, an exact API reference and a finite playable paddle template.
- A read-only `input_capabilities` host tool, wired through worker, daemon and
  normal argument/authorization checks. Metadata only; no queued events or held
  keys are returned.
- Project instructions that consider input for games/menus even when the user
  does not name a keypad, while preserving explicit autoplay and durations.

Input events remain local to the project. No inference occurs for each keypress.
The manual capture utility is not used by games, and raw input streams are not
persisted. The helper exposes only its named project controls. Project leases
coordinate cooperating readers without grabbing input away from the OS.

## Parallel-work boundary

Another session owns example CLI/catalog/manifest and packaging changes. This
implementation leaves `cli.py`, example manifests, `setup.py`, the existing
animation gallery and `docs/cli.md` untouched. The playable template lives in
the new skill's assets. `torque.input` is imported explicitly rather than changing
the shared SDK root exports. Later gallery/catalog integration remains separate.

## Software checks

- The full repository suite passed **211 tests, two platform-specific skips** in
  the final recorded run. The count includes concurrent example work available
  at that moment.
- All **17 project-input tests** passed independently on the Mac and UNO Q.
- Skill validation, JavaScript syntax, offline preview and documentation links
  passed. The offline preview was verified not to open input or board connections.

Tests exercise descriptor identity, unreadable/multiple devices, fragmented input,
initial held keys, repeat edges, overruns, lease contention, close/disconnect,
read-only capability inspection, policy validation, game movement/collision/pause,
finite fallback and cleanup.

## Physical keypad and matrix check

The user woke the keypad in its existing Bluetooth slot. Metadata discovery
found one readable matching keyboard; it did not read events or change pairing,
permissions, groups or services.

A deliberate **30-second manual paddle game** ran against the existing daemon
and MCU using a temporary staged copy of the new source. Numpad 4/6 and knob
rotation moved the paddle; 5/knob press paused it. The user explicitly confirmed
that movement and pause/resume worked.

Independent readback recorded:

| Check | Result |
|---|---|
| Program exit | Success after the finite duration |
| Samples matching the paddle/falling-pixel layout | 129 |
| Distinct game frames observed | 106 |
| Game outcome | 10 catches, 5 misses |
| Application actions | 64 left moves, 63 right moves, 4 pause toggles |
| MCU boot | Unchanged |
| MCU RGB state | Unchanged |
| Device ownership | Released |
| Final matrix | Expected standby framebuffer restored |
| Keypad reader/lease | Closed; a fresh reader opened successfully afterward |
| Raw keystroke recording | None |

Movement counts include held-key movement and are not physical keypress counts.
Frame observations came from firmware state; the user's observation is separate
physical confirmation, not a camera/optical measurement by the verifier.

## Agent behavior check

An isolated libfx worker uses the staged instructions/skill/tool and its own
workspace/session state. It neither replaces the production daemon nor installs
global input bindings. The first trial discovered input, read the keypad API and
template, and generated a game importing `torque.input`. Its broader acceptance
result failed because the fixture denied syntax-check programs, after which the
agent attempted two shell checks that correctly required approval and were denied.

A corrected trial supplies read-only board metadata, permits routine syntax-check
programs and disconnects generated programs from the production output socket.
It used a simple game request without naming the keypad. The agent called
`input_capabilities`, read the keypad guide/template and saved a Snake project
importing the shared API, with **zero approval requests**. That turn ended with
an engine error after saving/reading the project. A follow-up resumed the same
session and completed with `end_turn`; no native engine code or permissions were
changed to obtain recovery. The original error's detailed cause was not retained
by this trial's result recorder, so it is not classified as a provider or SDK bug.

The generated source parsed, but its render block was unreachable in the saved
version. The generation trial is therefore **not a fully passed playable-game
acceptance test**. It proves automatic input discovery and shared-API adoption;
the separate user-confirmed paddle test proves the helper/template controls.
The skill now reminds the agent to verify state changes reach rendered frames,
rather than treating a syntax check as proof of playable input. The isolated
Snake project is a private test artifact, not a shipped example or user project.

## Deployment boundary and receipts

The active release observed during testing was `0.1.0-b1bc26696382`. **The new
helper, tool and skill were not activated in that earlier managed release.** The
subsequent model/reset rollout activated them together in `0.2.0-56a1a1ed2c76`;
see the [installed acceptance record](2026-10-25-model-reset-and-cancellation.md).
During the original input development proofs, no firmware upload, service
restart, boot-default change or modification of the Node/libfx binaries was performed.

Private board-local receipts and isolated generated projects are under:

```text
~/.cache/torque/keypad-proof-920d924b0809/
  capabilities.json
  live-game.json
  agent-proof.json
  agent-proof-corrected.json
  agent-recovery.json
```

These files contain metadata and aggregate results, not the provider credential
or a raw key sequence. The matched runtime now contains `torque.input` and
`input_capabilities`; do not install only the new skill into an older runtime
lacking those interfaces.
