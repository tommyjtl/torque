# Session Studio

A local HTML designer for assigning parts of the UNO Q matrix to agent-session
signals. Open `index.html` directly in a browser, or serve this directory:

```bash
python3 -m http.server 8765 --bind 127.0.0.1 --directory tools/session-studio
```

Then open <http://127.0.0.1:8765>. No dependencies or build step are required.
The page loads no remote scripts, fonts, or assets. Browser storage keeps your
layout when available; export JSON to keep or share a design independently.

1. Select a region. Set its channel, coordinates, size, layer, and visibility.
   Use **Draw region bounds** to drag a new rectangle on the main grid.
2. Choose a channel state and paint its frames. Use **Play motion** to preview
   the clip, or **Live session** to see current simulated session information.
3. Play or scrub an event scenario. Fire individual events to try overlapping
   tools, user waits, cancellation, or connection loss.
4. Export a layout and import it later. **Save current frame** exports the
   composed image as binary rows and the controller's 26-character hex encoding.

Resizing or rebinding a region regenerates its starter clips. Moving it preserves
them. Undo/redo covers design edits, including a reset or import. Overlapping
regions use opaque rectangles; higher layer numbers cover lower ones. Colored
borders are editor guides; the actual matrix preview uses blue binary pixels.

The exported layout is a proposed design format, not a firmware animation.
Independent regional clips need a later composition strategy to fit the MCU's
single 32-frame animation buffer. Outcomes remain visible in the rehearsal until
the next turn or reset so they can be inspected; transient outcome duration is
an integration decision. TFT hardware and rendering are future work.

This studio sends no commands to the board or fx. It does not capture real
agent activity. Its event names are proposals awaiting integration verification.
Read the [studio design](../../docs/design-spec/2026-10-24-session-display-studio.md)
and [feedback proposal](../../docs/design-spec/2026-10-24-fx-hardware-feedback.md).
The [animation reference review](../../docs/design-spec/2026-10-24-animation-reference-review.md)
assesses all 90 Dot Matrix gallery entries for a future grayscale revision,
including primary 5×5 animations and compact 3×3 alternatives.

Run the focused behavior checks with Node 18 or newer:

```bash
node --test tools/session-studio/core.test.cjs
```
