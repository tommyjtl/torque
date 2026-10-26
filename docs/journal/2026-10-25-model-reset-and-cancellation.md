# Model selection, output reset and Ctrl-C cancellation

**Date:** 2026-10-25, America/Los_Angeles

**Status:** Deployed as `0.2.0-56a1a1ed2c76`. Installed model/text/tool and
blank/standby reset acceptance passed. The first activation's cache error and
its correction remain recorded below.

### First activation and cache-layout correction

The user activated `0.2.0-6b59d8596260`; firmware boot `411099270`, startup app and
service configuration were preserved. The post-install verifier then failed at
`model list --refresh`. Live inspection found the enclosing `~/.cache/torque`
directory owned by UID 1000 with mode **0775**. The writer correctly rejected a
shared parent, but placing the catalog directly there was an implementation error
missed by tests using private fixture parents.

The corrected default is `~/.cache/torque/model-catalog/catalog.json`: create a
private mode-700 child and a mode-600 file, preserving the shared parent's mode.
A regression test uses the actual 0775 layout. No chmod/chown of existing cache,
runtime ownership, service privileges or sudo policy is part of this correction.
The runtime itself remains ready while the narrow fix is prepared; the first
post-install acceptance result must not be reported as passed.

The ARM64 terminal test also exposed an expected peer-disconnect error escaping
the socket close path after Ctrl-C reconnected the frontend. Cleanup now tolerates
that closed-pipe condition; a direct regression check covers it. This changes no
authorization decision or tool effect.

The corrected code passed **240 host tests (two platform skips)** and **26 ARM64
control checks**. A live authenticated catalog refresh using the corrected source
returned six models, preserved the shared parent's 0775 mode, created a 0700
catalog directory and a 0600 file, and confirmed the credential was absent from
that cache. The reviewed correction is staged as `0.2.0-56a1a1ed2c76`, based on
`0.2.0-6b59d8596260`; its no-change preflight passed. Activation still requires
the board's private sudo entry; no sudo policy was changed to avoid it. The user
then applied the corrected bundle and the installed acceptance run passed.

### Successful installed acceptance

The corrected runtime was activated through the user's private SSH/sudo terminal.
The saved receipt is
`~/.cache/torque/controls-update-dd195b1d0423/acceptance.json`.

| Installed check | Result |
|---|---|
| Model discovery | Online; cache successfully written privately |
| Current model | `MiniMaxAI/MiniMax-M3.1-Flash`, unchanged |
| Native text/tool probe | Passed, three requests, zero external effects |
| Blank reset | Matrix and both MCU RGB readbacks passed; blank retained after the command |
| Standby reset | Matrix/RGB readbacks passed; standby framebuffer restored |
| MCU firmware/boot | 0.4.0 / protocol 1.3; boot `411099270`, unchanged |
| User settings | Byte-for-byte unchanged by acceptance |
| Conversation and permissions | Preserved |
| Final state | Device ready, idle, auto policy, no owner or pending approvals |
| Optical measurement | None; framebuffer/GPIO evidence |

Root activation preserved the Arduino app/default and service-unit hash. No
firmware upload or sudo-policy/ownership change was performed. The model/reset
commands, revised Ctrl-C behavior and keypad foundation are now in the matched
managed runtime. Start a fresh `torque` frontend to use the revised bindings.

## User decisions

The [design spec](../design-spec/2026-10-25-model-selection-and-device-reset.md)
defines model discovery/selection/testing and reset to standby or blank.
The user subsequently reported reopening Torque after Ctrl-C and finding the
previous turn still active, with an output-gap message. Read-only status confirmed
an active worker and no pending approvals; the bounded terminal event buffer had
lost older output. This did not establish lost durable conversation history.

The user explicitly chose revised Ctrl-C behavior: cancel the active turn and
managed programs, then return to chat. Full component cleanup remains an explicit
reset. At the chat prompt Ctrl-C clears input; `/exit`/Ctrl-D leaves. Disconnecting
SSH can still leave accepted work running.

## Implementation

- [`models.py`](../../packages/session/src/torque/models.py) discovers authenticated
  exact IDs, maintains an owner-only one-hour cache, applies curated metadata or
  a conservative experimental profile, and records profile/version-bound probes.
  Credentials never enter cache files. Redirects, oversized/malformed responses
  and invalid IDs are rejected; refresh failure does not silently change models.
- [`control_cli.py`](../../packages/session/src/torque/control_cli.py) shares
  model/reset parsing between shell commands and interactive slash commands.
  Listing/selection make no inference requests. The explicit test announces its
  bounded billable scope.
- The daemon serializes selection with turn startup, persists only model-related
  settings, preserves session identity/history, and cancels managed process
  groups. The worker supplies an explicit per-session model override to libfx.
- [`model-test.mjs`](../../engines/fx/model-test.mjs) uses a temporary in-memory
  agent, a text marker and a harmless nonce tool. It bounds requests, tokens,
  time and output and exposes no project/shell/hardware tools.
- The device coordinator gates new writers during reset, respects external
  ownership, aborts tracked uploads, stops playback and verifies matrix/RGB
  readback. Uncertain writes are not replayed. Resident clips and MCU boot are
  preserved by the existing draw/reset contract; Linux user RGB is explicitly
  unmanaged/skipped.
- Ctrl-C reconnects an interrupted frontend stream before cancellation, then
  returns to the interactive prompt. Completed effects are preserved. Reset is
  separate, and interrupted reset views do not abandon cleanup halfway through.

The Linux-only updater now includes `engines/`, `agent/` and `config/` alongside
the Python package and examples. This keeps host tools, skill instructions and
the model probe matched without replacing Node/libfx binaries or firmware.
The existing example command and manifests were preserved.

## Live model evidence

An isolated daemon used private configuration/cache/session directories and the
existing owner-only credential path. Production selection/history were not changed.

1. Authenticated discovery returned six IDs.
2. MiniMax M3.1 Flash stored a continuity marker and completed its turn.
3. Model selection changed the private saved default to `google/gemma-4-31b-it`.
4. A new daemon/worker loaded that configuration and resumed the same session.
   Gemma returned the exact continuity marker. Native `model.start` events identify
   MiniMax for the first turn and Gemma for the follow-up, with the same session ID.
5. Gemma's text/tool probe passed with three requests and zero external effects.

A separate native test used a synthetic response transport with zero network
requests. It verified that the unknown-model profile's 16,384-token client budget,
disabled vision and unspecified tool capability are accepted by the pinned engine,
and that the engine attempts sending tools. This does not establish any real
unknown model's capabilities or actual context window.

## Reset and terminal evidence

The live source reset was exercised through the existing public SDK while the
production daemon was idle. Setup lit the matrix and set MCU RGB 3/4 to test
colors. Blank and standby reset both passed independent framebuffer/GPIO reads.
MCU boot ID remained **411099270**. Cleanup restored production standby and
released ownership. No firmware, service or boot-default change was part of
these development tests.

Because this proof used a private coordinator layered over the existing SDK,
blank was verified while that SDK connection owned the output. Actual retained
blank after a production reset command is a post-activation acceptance check.
Preset contents were not individually dumped; the reset path does not reboot,
reload or delete them, and existing controller state tests cover draw preserving
resident clips. Physical brightness was not optically measured.

Control tests cover cache/credential changes, unknown profiles, exact-ID selection,
busy rejection, failed persistence, temporary/cancellable model probes, settings
and history preservation, reset busy/partial failures and readback. A real POSIX
terminal test sends Ctrl-C to the frontend while an independently grouped managed
Python process is running. The daemon terminates that process and the frontend
returns to its prompt, then exits cleanly on `/exit`.

The final host suite passed **240 tests, with two platform-specific skips**.
All **26 ARM64 control checks** passed, including a real terminal interrupt,
discovery cancellation, cache-layout regression, large-catalog wire bounds,
closed-pipe cleanup and acceptance-default guards.
See the [CLI guide](../cli.md) for the new commands and interruption
semantics; older installed bundles retain their prior behavior until updated.

## Private receipts and rollout

Development receipts live on the board under:

```text
~/.cache/torque/controls-proof-e3da690c494a/
  model-proof.json
  reset-proof.json
```

The production runtime observed after the parallel example rollout was
`0.2.0-d744b9972b29`, with controller 0.4.0 / protocol 1.3. The next application-only
bundle keeps that MCU identity and includes the keypad foundation from the
[input journal](2026-10-25-keypad-project-input.md). Apply through the existing
[Linux-only updater](../../install/README.md), then verify real commands and
restart persistence while preserving the user's original model and outputs.

Reference: the pinned [libfx session API](https://fx.sh/docs/lib/api)
documents a model override per session object/turn; the independent native hook
and continuity evidence above verify this behavior with Modular on ARM64.
