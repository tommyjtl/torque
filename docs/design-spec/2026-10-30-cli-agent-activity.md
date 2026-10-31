# Live agent activity in the terminal

**Date:** 2026-10-30, America/Los_Angeles

**Status:** Draft for review. No CLI behavior, runtime or firmware is changed by
this document.

## Intended experience

While Torque works, show **one updating line: a spinner followed by the latest
observed activity**. Replace that line when the activity changes. Keep the chat
readable without accumulating a transcript of every tool call.

The user initially selected verbose activity, then refined the preference to
this single-line display. This is the proposed default for an interactive TTY.
A complete activity history is an optional later feature, not required for the
first implementation.

Illustrative successive states of the same row:

```text
⠋ Waiting for model response · 3s
⠙ Checking microphone availability · 4s
⠹ Reading uno-q-input/references/audio-api.md · 5s
⠸ Writing projects/audio-recorder/main.py · 9s
⠼ Running audio-recorder/main.py · 11s
```

These are examples, not observations of the recorder in the user's screenshot.
The elapsed value is total time since the turn began. In a long program phase,
the row can additionally show the time in that phase. Neither is a progress
percentage or an estimate of time remaining.

Assistant messages still stream normally and remain in scrollback. Approval
questions, errors and the final response remain visible. Successful transient
activity rows disappear when work finishes; a failure leaves a concise error.

## What the current code already provides

| Current implementation | Consequence for this feature |
| --- | --- |
| [worker.mjs](../../engines/fx/worker.mjs) forwards libfx hooks with `captureContent:false` and streamed output events | Use genuine lifecycle observations without enabling content capture or modifying libfx |
| [install/verify.py](../../install/verify.py) checks model, tool, turn and wait start/end hooks | The existing integration has a verified lifecycle surface; confirm exact payload fields on the pinned version before normalizing them |
| [daemon.py](../../packages/session/src/torque/daemon.py) publishes worker events and handles host tools/approvals | Add authoritative host execution phases here rather than infer execution from model prose |
| [cli.py](../../packages/session/src/torque/cli.py) prints only `text_delta` and `worker.error` from that feed | Tool/model activity can be happening while the terminal appears blank |
| The daemon collects program stdout/stderr until the process exits | A recorder's readiness message is currently not live CLI output |
| The event ring holds 512 entries, with cursors, gap detection and daemon epochs | The current phase must also exist in a bounded snapshot for attach and event loss |
| Managed tool processes currently have a 120-second deadline and 64 KiB combined output limit | A progress display must preserve those limits; microphone capture's separate five-minute cap does not extend a managed program's lifetime |

The screenshot alone does not establish whether that turn is waiting on the
model, generating a tool call or running a program. This feature should make
the observed phase visible instead of guessing the agent's internal activity.

## Activity semantics

Trace means observable execution metadata: model requests, tool dispatch,
permission waits, process state and tool outcomes. Do not display model reasoning
content, raw provider responses, prompts, file contents or arbitrary tool JSON.
Keep libfx content capture disabled.

Use these sources and labels:

| Observed phase | Single-line label | Authority |
| --- | --- | --- |
| Prompt admitted; worker starting | Starting agent | Daemon admission/worker lifecycle |
| Model request in progress | Waiting for model response | Verified libfx `model.start`/`model.end` |
| Supported read/discovery tool dispatched | Reading NAME / Checking microphone / Checking keypad | Validated host tool request |
| File write executing | Writing projects/NAME | Daemon immediately before execution |
| Program executing | Running projects/NAME | Daemon process lifecycle |
| Permission required | Waiting for approval | Actual pending approval; spinner pauses |
| Turn ends | Clear transient row; show normal answer | Daemon terminal outcome |
| Connection lost/restarted | Connection lost / Torque restarted | Frontend connection and epoch checks |

Receiving a proposed tool call does not establish that its effect ran. Publish
the executing phase only after validation and authorization. A successful
process spawn means running, not successful completion; a nonzero exit remains
a failure even if the model describes success.

For overlapping tools, show the most recently started **still-active** tool and
an `(+N active)` suffix. When it ends, return to another active tool or the
current model/wait phase. Maintain a bounded active set rather than letting the
last completion message overwrite ongoing work. Approval waiting takes
precedence and names how many approvals need attention.

## Proposed data flow

Add a small normalized activity contract in Torque, independent of raw libfx
event shapes. Each activity carries a schema version, daemon epoch, turn ID,
activity ID, kind, start/update/end phase, bounded safe label, outcome and
daemon-observed timing. Tool activities also carry the host request ID. IDs must
remain distinct when worker-local tool serials restart on the next turn.

The daemon owns the reducer and includes its current activity snapshot in
status/events replies. Use daemon monotonic timing for duration calculations;
do not compare process-local clock origins or subtract wall-clock timestamps
across machines. Publish bounded elapsed durations for clients to extrapolate
locally between polls.

Use host tool lifecycle events as the canonical source for tool state and libfx
hooks for model lifecycle. Deduplicate overlapping hook/output observations;
they must not produce two starts or two completions for one tool. Unknown hook
types are ignored for presentation. Missing metadata falls back to `Working`
with elapsed time, without invented activity.

Terminal outcomes clear remaining activities for that turn. Late events from a
completed or superseded turn cannot replace the current row. On attach or an
event gap, restore the current row from the snapshot; do not replay historical
activity rows or resend prompts/tools. Existing epoch mismatch handling remains
an explicit restart notice. A disconnected frontend stops its spinner and must
not imply that an observed task was cancelled.

## Terminal rendering

Use a small presenter separate from CLI control/approval logic. The normal view
needs one in-place row, no full-screen application or terminal takeover.

- Refresh animation locally at no more than 8–10 frames per second. Do not poll
  the daemon or call the model for each spinner frame. The current roughly
  150 ms event poll is sufficient for activity changes.
- Reserve the spinner prefix, label and elapsed suffix within the terminal
  width. Sanitize controls and truncate by display width so resizing, Unicode
  paths and narrow SSH windows cannot wrap the row into scrollback.
- Clear the row before printing assistant deltas, permanent errors or approval
  prompts. Suspend animation while assistant text is streaming and while input
  is being requested; resume for the next observed tool/wait phase. Preserve
  every assistant delta exactly once and its existing streaming behavior.
- Do not print each animation frame with a newline. Use a plain ASCII fallback
  when the terminal cannot render the selected spinner glyphs.
- Animate only with suitable terminal streams and terminal capabilities. When
  output is piped or `TERM=dumb`, use plain output without cursor controls;
  an explicit activity option can print phase changes to stderr. Assistant
  output remains on stdout. `--quiet` can suppress transient activity in a TTY
  while preserving answers, errors and approval questions.
- Ctrl-C, EOF, normal completion and exceptions all restore the cursor/line
  state. Keep the current cancellation/reset behavior and approval authority.

A spinner means that the frontend is waiting on active work. It is not evidence
that the model is generating tokens or making useful progress. A long quiet
period should show its actual phase and elapsed time, not trigger retries or
cancel otherwise authorized work.

## Program output and the recorder case

The first implementation can show a reliable `Running audio-recorder/main.py`
row with the existing tools. Showing `Ready — press 1 to record` or `Recording`
requires a live program-output path as a follow-up part of this design.

Read program output continuously as today, while also publishing bounded
request-scoped output updates. Start managed Python with unbuffered output so a
flushed readiness message can reach the frontend promptly. Keep collecting the
existing bounded final tool result for the model; presentation does not change
the tool's return value or authorize another execution.

Treat arbitrary stdout as program-reported text, not authoritative lifecycle or
permission events. In the single-line view, show only the latest safe line with
a `Program:` prefix. For critical prompts that require a response, use an
explicit supported interaction contract; do not guess that a stdout sentence
requires agent approval. Keypad handling remains inside the recorder's local
event loop and does not wait for a model round trip.

Coalesce high-frequency meter/progress lines. Bound update size/rate and total
presentation memory, retaining the latest line and a dropped-update count.
Dropping intermediate presentation updates must not drop PCM, block capture,
restart a process or change its existing execution/output limits. A slow or
disconnected terminal is never the lifetime owner of a program.

The 120-second managed-program deadline is a separate product constraint for a
long-running recorder. Do not silently extend it as a side effect of tracing.
Describe it when running such a program; design any lifetime changes separately.

## Content and storage boundaries

Build labels from allowlisted metadata: tool name, resource-relative path,
numeric duration/count and bounded outcome. Omit full write/read content,
shell commands, program arguments, provider bodies and environment values from
the transient row. The actual approval prompt still identifies the exact action
being approved through its existing control path.

Program output is arbitrary user content. Apply credential redaction before
publishing it, including secrets split across chunks, and sanitize terminal
control sequences before presentation. Keep UTF-8 decoding state across chunk
boundaries. Do not enable raw hook dumps as a substitute for this contract.

Keep activity state in memory. No new trace files, persistent log collection or
retention job is needed for the initial feature. Existing engine history and
tool results keep their current behavior. Do not copy microphone PCM or saved
recording contents into progress events. Any later export/history mode needs
an explicit bounded format and storage policy, consistent with the
[retention draft](2026-10-26-managed-storage-retention.md).

## Implementation and acceptance

1. Verify pinned hook payloads and their correlation IDs with synthetic fixtures
   and a bounded installed-engine probe when execution is authorized. Implement
   normalized host/model activity and the snapshot reducer without patching
   libfx or altering permission checks.
2. Add the one-row TTY presenter to interactive chat, one-shot `ask` and `attach`.
   Show real model/tool/approval phases, elapsed time and terminal outcomes.
3. Add bounded live program-output updates, including unbuffered Python and
   chunk-safe redaction/decoding. Keep execution limits unchanged.
4. Document the implemented behavior and options in [docs/cli.md](../cli.md).
   This draft does not add unreleased commands to that reference or change the
   root README.

Meaningful acceptance checks:

- A delayed model response displays a spinner/elapsed phase before its first
  text delta; repeated redraws occupy one row rather than accumulating lines.
- A read/write/run sequence replaces the row correctly; tool errors and denied
  approvals never appear as successful execution.
- Overlapping activities, repeated notifications, late events and new worker
  serials preserve the correct active phase.
- Assistant text and approval input remain readable with partial lines, Unicode,
  terminal resize, narrow width and Ctrl-C mid-redraw. Non-TTY output contains
  no animation escapes.
- Attach, ring gaps and epoch changes recover truthful state without another
  model request or repeated effect.
- A finite synthetic program emits readiness before exit; output flooding is
  bounded and cannot stall execution. UTF-8/control sequences and a fixture
  secret split between chunks are handled before display.
- Validate on a real SSH TTY with an authorized harmless program. No microphone
  recording is required to test activity rendering. Report measured display
  delay separately from model latency.

This is a Linux application feature. It needs no MCU firmware upload, Arduino
app replacement, boot-default change, service-policy change or new inference
provider. A later deployment uses the existing unattended updater after the
active user turn and programs have finished.
