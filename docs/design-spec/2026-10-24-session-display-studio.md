# Agent session display studio

**Status:** Exploratory design and local browser prototype, 2026-10-24.
This is a place to make layout decisions before the
[fx feedback integration](2026-10-24-fx-hardware-feedback.md).

## Intent

Reserve different areas of a display for different aspects of an agent session.
Model output, running tools, and a request for user input can coexist. Do not
reduce all of them to one icon that constantly replaces the previous activity.

Keep three responsibilities separate:

1. An adapter reports agent events, independently of any output hardware.
2. A session model tracks current activities and outcomes.
3. A layout binds named regions to session information. Each region selects a
   visual clip for its current state; a renderer composes the result.

The first target is the UNO Q's 13-column, 8-row monochrome matrix. A future TFT
can use the same session model with its own regions, text, and graphics. Its
resolution, driver, and wiring are undecided. Matrix coordinates are layout
assets, not part of the agent event contract.

## Prototype channels and events

These names are proposals to explore, not verified native fx hooks.

| Channel | Information retained | Example events |
|---|---|---|
| Session | Ready, working, completed, failed, cancelled | `session.opened`, `turn.started`, `turn.finished` with outcome |
| Model | Idle, waiting, producing output | `model.started`, `model.output_started`, `model.finished` |
| Tools | Idle, running, last tool failed; active tool count | `tool.started`, `tool.finished` with outcome |
| Attention | Quiet, needs an answer, needs approval | `user_wait.started`, `user_wait.finished` |
| Connection | Event source connected or lost | `source.disconnected`, `source.reconnected` with a fresh snapshot |

Activities carry identifiers and a turn identifier. Finishing one tool only
removes that tool. A failed tool does not end the turn. Waiting for approval
means the harness actually requested user action; automatic permission checks
do not count. Model activity describes observable execution, not inferred
internal reasoning. A finished turn closes its remaining activities; late
events from an old turn cannot change a new one.

The prototype models one foreground session. Source loss preserves the last
session information but visibly marks it stale. Reconnection replaces it with
a supplied snapshot; it never fabricates successful completion. Device health
and the controller's existing telemetry are separate from agent lifecycle events.

## Initial spatial experiment

The editable starting layout reserves a large left region for the session, two
small right regions for model and tool activity, a narrow attention strip, and
a bottom connection strip. These choices are a starting point, not a final
theme. The user can move, resize, rebind, disable, add, and remove regions.

The first prototype renders blue binary pixels, matching the current controller
API. The hardware also supports eight grayscale levels (0–7); these are a target
for a subsequent studio/controller revision. Colored boundaries exist only as
editor guides. Regions paint an opaque rectangle: higher layer numbers cover
lower layers, including their off pixels. The editor reports overlaps and the
number of reserved pixels. Overlap is allowed deliberately rather than silently
prevented. Unreserved pixels are off.

## Studio behavior

- Show an animated composed preview, with optional region guides and a small
  unguided preview to judge the display at a glance.
- Edit a selected region's name, channel, position, size, and layer. Drag a
  rectangle on the main grid to redefine its bounds.
- Select any state of the region's channel, paint binary frames, choose frame
  duration, duplicate/add/remove frames, and choose loop or hold-last playback.
- Replay successful work, approval, tool failure/recovery, and source-loss
  fixtures. Scrub the timeline and inject individual events, including
  overlapping tools, while inspecting the event log and active counts.
- Save the layout locally in the browser. Export/import a validated, versioned
  JSON layout; include undo/redo and a deliberate reset to the starter layout.

An edited clip is previewed explicitly, separately from the live session view.
Changing a region's dimensions resets its clips to matching-size starter clips;
undo can restore the previous design. Moving a region preserves its clips.

## Export and controller boundary

The draft export has `schema_version`, `kind`, a target descriptor, and regions.
Each region contains its rectangle, channel, layer, enabled flag, and clips
keyed by channel state. Each clip has playback policy and frames containing
binary row strings and a duration in milliseconds. Event payloads contain no
pixel coordinates or asset names.

Each regional clip respects the current 1..32-frame and 20..60,000-ms input
limits. The browser composes independently timed region clips. **A layout export
is not a directly uploadable MCU animation.** A later renderer must bake or
otherwise schedule the composed image within the controller's single 32-frame
animation buffer and validate timing. Independent region cycles need not fit
that buffer as one exact repeating clip.

The prototype is a static, offline-capable HTML/CSS/JavaScript tool. It uses
simulated events and has no connection to fx, Arduino Router, or the board.
It does not deploy firmware or define a final transport protocol. Version 0.2.0
already supplies command, snapshot, and telemetry primitives; it does not supply
the proposed expiring feedback display lease. An observer lease is not display
ownership. Those integration concerns stay with the feedback design.

## Review and acceptance

Use the studio to decide whether the reserved areas are large enough, which
events deserve a persistent region, and whether attention/outcome indications
should cover other regions. Compare simulated overlaps before choosing icons.

Check bounds, binary frame data, opaque layer composition, concurrent activity,
stale-turn rejection, source-loss behavior, and import/export round trips in
host tests. Check region editing, painting, playback, and save/reload in a browser.
Visual fidelity, physical LED orientation, and real timing require later board
observation. A successful browser preview is not a hardware test.

## Animation reference review

The [Dot Matrix reference review](2026-10-24-animation-reference-review.md) covers
all 90 gallery entries and identifies candidates for the next iteration.
Treat 5×5 as a primary animation size alongside compact 3×3 patterns. A proposed
layout fits two 5×5 regions, an attention strip, and two bottom status bands on
the 13×8 display. The review proposes eight-level brightness, reusable motion
families, and separate behavior for loops and one-shot outcome accents.
Those proposed assets and the alternative layout are not yet implemented in
the binary prototype.

The [matrix grayscale implementation](2026-10-24-matrix-grayscale.md) starts with
firmware/SDK support and an offline Half Helix reference example. Studio format
migration, grayscale painting, and preset integration remain subsequent work.
