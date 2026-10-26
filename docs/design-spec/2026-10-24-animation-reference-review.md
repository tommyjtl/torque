# Dot Matrix animation references for agent-session feedback

**Status:** Reference review, 2026-10-24. Covers all **90 gallery entries** visible
on [Dot Matrix](https://dotmatrix.zzzzshawn.cloud/): 20 square, 20 circular,
20 triangle, 10 hexagonal, and 20 compact 3×3 animations.

## Review basis

Reviewed the rendered gallery and every corresponding component's motion logic,
including shared factories, path helpers, and CSS keyframes. Source was inspected
from [zzzzshawn/matrix](https://github.com/zzzzshawn/matrix) at revision
[`e30b80a9c5e6fe388ecbbbac15abfd14f24d0dd3`](https://github.com/zzzzshawn/matrix/tree/e30b80a9c5e6fe388ecbbbac15abfd14f24d0dd3).
The website does not expose its deployed commit identity, so source observations
refer to that reviewed revision. No upstream component code is added to this repo.

Suitability, suggested roles, and rankings below are our design judgments.
They describe candidate references, not measured results on the physical LEDs.
Every reference name links to its specific playground entry; repeated names
are disambiguated by the group and component ID.

The major finding is that the useful motion is overwhelmingly **brightness on
fixed dots**. The spin factory rotates a binary glyph between cell positions and
crossfades the result; it does not require physically rotated LEDs. Optional
web color gradients, variable dot shapes, glow filters, and layout scaling are
not the essential animation. Hexagonal row staggering needs a spatial adaptation.
Some registry descriptions do not match current motion code; the table calls out
notable examples rather than relying only on names.

## Display assumptions

- Use eight brightness levels, **0–7**, including off. The authoring API could
  accept 0–255, but preview the quantized result. The
  [UNO Q driver](https://github.com/arduino/ArduinoCore-zephyr/blob/1.0.0/libraries/Arduino_LED_Matrix/src/Arduino_LED_Matrix.h#L69)
  documents these eight output levels.
- **5×5 is a primary design size**, alongside 3×3 for smaller signals. Both fit
  the 13×8 matrix. Circular entries are masks on a regular 5×5 grid, so they
  do not require a round display.
- Triangle components use a 7×7 canvas with only ten active dots. Their occupied
  rectangle is **7×4** after cropping the empty top and bottom rows; they can
  fit the matrix without scaling.
- Hex entries use 19 dots in staggered rows of 3, 4, 5, 4, 3. An approximate
  5×5 redraw is possible. Preserving their horizontal half-column offsets on
  integer cells needs a **9×5** footprint, with different physical aspect ratio.
- Original loop speeds are examples. Start slower for a physical indicator,
  adjust brightness on the board, and compare simultaneous regions at a glance.

The current base controller and first studio prototype still implement binary
frames. This review proposes grayscale assets for a later revision; it does not
claim that those assets can already be sent through the existing binary API.

**Implementation follow-up:** The
[grayscale controller spec](2026-10-24-matrix-grayscale.md) now defines the 0.3.0
firmware/SDK extension and the Half Helix reference example. The installed
controller and the studio remain binary until their respective upgrades.

## Suggested first set

| Session signal | Main 5×5 reference | Compact option | Behavior to build |
|---|---|---|---|
| Waiting for a model | Echo Ring, or Heart Pulse | Echo Rings | Slow pulse; distinct from an urgent request for input. |
| Producing output | CRT Glide, Half Helix, or Sound Bars | Row Sweep or Column Flux | Choose one traveling texture; it expresses activity, not percentage progress. |
| Tools executing | Core Rotor or Core Spiral | Frame Chase or Comet Trail | Continuous chase while the active tool count is nonzero. |
| Needs an answer / approval | Pulse Pair or Heart Pulse | A stable attention glyph with a brightness pulse | Keep the identifying mark visible while the agent waits. |
| Turn accepted | Origin Wave | Core Echo or Drop Ripple | One expansion, then switch to current activity. |
| Completed | A newly drawn upright check, borrowing Check Spin's crossfade | Upright 3×3 check | Brief reveal and hold, then ready; no endless spinning. |
| Failed / cancelled | A deliberate cross / stop glyph | Same, simplified | Stable recognizable outcome; these loaders do not supply a complete error vocabulary. |

The associations are renderer choices. Agent events remain independent of asset
names and region coordinates. Do not use two different diagonals as the only
distinction between two critical states. Likewise, a loop with two or three
moving heads is decorative unless head count is deliberately connected to actual
activity count.

## A layout with two 5×5 regions

This is a proposed alternative to the first studio layout, not a committed
hardware UI. Coordinates start at the upper-left, with x increasing to the right.

```text
MMMMM.TTTTT.A
MMMMM.TTTTT.A
MMMMM.TTTTT.A
MMMMM.TTTTT.A
MMMMM.TTTTT.A
.............
SSSSSSSSSSSSS
CCCCCCCCCCCCC
```

`M`: main model/session activity at (0,0), 5×5. `T`: tool activity at (6,0),
5×5. `A`: attention at (12,0), 1×5. `S`: session/outcome band at y=6.
`C`: connection band at y=7. Dots are reserved gaps, not permanently lit pixels.
A band can use only a small part of its area rather than lighting the whole row.
An outcome can temporarily take the main region if it needs a recognizable glyph.

Two 5×5 regions are a useful experiment, not a requirement to animate both all
the time. Compare a quiet model pulse against a tool chase and attention request
together. Keep connection mostly steady so it does not compete with session work.

## Complete per-animation review

**First** means include in the first comparison set. **Useful** means a strong
additional style option. **Alternative** means feasible but less distinctive.
**Adapt** means retain the useful motion while changing its status semantics.
**Redraw** means adapt its layout to square cells. **Defer** means a weaker fit
for the first session theme, not a hardware impossibility.

Review totals: **First: 14**, **Useful: 36**, **Alternative: 21**, **Adapt: 3**, **Redraw: 7**, **Defer: 9**.

### 5×5 square patterns

| Reference | ID | Decision | Candidate role | Adaptation / reason |
|---|---|---|---|---|
| [Neon Drift](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-square-1) | `dotm-square-1` | Useful | Response activity | Diagonal brightness bands are easy to rasterize; reserve one direction for a consistent meaning. |
| [Pulse Ladder](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-square-2) | `dotm-square-2` | Alternative | Long-running work | The unusual column-jumping path is harder to follow than a simple chase; simplify its route. |
| [Core Spiral](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-square-3) | `dotm-square-3` | First | Tool execution | A clear inward path with a fading tail; 25 positions fit a 32-frame clip before adding intermediate fades. |
| [Twin Orbit](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-square-4) | `dotm-square-4` | Useful | Concurrent activity | Two nested counter-rotating paths look good at 5×5; keep them decorative rather than implying exactly two tasks. |
| [Prism Sweep](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-square-5) | `dotm-square-5` | Useful | Response activity | A diagonal path with a tail is readable; retain contrast when the trail crosses nearby rows. |
| [Flux Columns](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-square-6) | `dotm-square-6` | Useful | Parallel work | Alternating upward/downward column motion is a strong texture; slow it down beside another busy region. |
| [Block Drop](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-square-7) | `dotm-square-7` | Defer | Playful alternate theme | Falling blocks attract attention and suggest accumulating progress; weak default meaning for an agent session. |
| [Strobe Stack](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-square-8) | `dotm-square-8` | Defer | Alternate theme | Fill, blink, and drain has too many beats for an everyday status; avoid the all-on flashes as a default. |
| [Glyph Pulse](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-square-9) | `dotm-square-9` | Alternative | Custom status glyphs | Reuse the idea of discrete brightness motifs, but assign deliberate symbols instead of cycling unrelated glyphs. |
| [CRT Glide](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-square-10) | `dotm-square-10` | First | Producing output | The moving scanline and fading wake read clearly; drop the tiny column warp if it disappears after quantization. |
| [Echo Ring](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-square-11) | `dotm-square-11` | First | Waiting for model | A gentle outward pulse and weaker echo make a distinct waiting rhythm; keep its peak below urgent attention. |
| [Origin Wave](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-square-12) | `dotm-square-12` | First | Turn accepted / transition | Use one outward expansion as an acknowledgment; looping it is also a valid waiting alternative. |
| [Core Rotor](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-square-13) | `dotm-square-13` | First | Tool execution | Eight clear blade directions make a compact spinner; retain an upright, stationary center hub. |
| [Prism Bloom](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-square-14) | `dotm-square-14` | Useful | Completion accent | Use a single short bloom as an outcome accent, then hold a recognizable result symbol. |
| [Helix Glow](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-square-15) | `dotm-square-15` | Useful | Producing output | Mirrored wave strands give a different texture from a spinner; avoid squeezing it into a three-row region. |
| [Helix Core](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-square-16) | `dotm-square-16` | Useful | Narrow model activity | The middle band can be cropped to about 3×5; its vertical rhythm is useful in a narrow region. |
| [Half Helix](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-square-17) | `dotm-square-17` | First | Producing output | A single traveling strand is legible and less crowded than twin strands; a good alternative to the scanline. |
| [Sound Bars](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-square-18) | `dotm-square-18` | First | Producing output | The changing bar silhouette is readable at 5×5; label it as activity, not measured audio or percentage progress. |
| [Infinity Run](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-square-19) | `dotm-square-19` | Alternative | Long-running work | The crossing path is attractive at 5×5, but multiple heads and the central pulse compete for attention. |
| [Mobius Run](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-square-20) | `dotm-square-20` | Alternative | Tool execution | Outer-edge motion works; simplify the second train and interior flashes so it stays distinct from other chases. |

### 5×5 circular masks

| Reference | ID | Decision | Candidate role | Adaptation / reason |
|---|---|---|---|---|
| [Halo Drift](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-circular-1) | `dotm-circular-1` | Useful | Producing output | A diagonal strand works on the square LED grid with the unused corners kept off. |
| [Tri Orbit](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-circular-2) | `dotm-circular-2` | Alternative | Tool execution | Three orbiting highlights are feasible but crowded; do not imply three tools unless driven by a real count. |
| [Plasma Veil](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-circular-3) | `dotm-circular-3` | Useful | Tool execution | Current source uses two fading perimeter chases, despite the plasma description; prefer one clear head for status. |
| [Radar Arc](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-circular-4) | `dotm-circular-4` | Useful | Search / tool activity | The rotating beam is recognizable at 5×5; reserve a scanning meaning if using it alongside a tool spinner. |
| [Nova Wheel](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-circular-5) | `dotm-circular-5` | Alternative | General work | The pinwheel is portable, but multiple blades are harder to distinguish than Core Rotor. |
| [Phase Orb](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-circular-6) | `dotm-circular-6` | Alternative | Model activity | The off-center glow is feasible but can look like another spinner; compare it against other assigned regions. |
| [Gate Shift](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-circular-7) | `dotm-circular-7` | Defer | Decorative alternate theme | Current source blends angular, radial, and diagonal brightness fields; it is more texture than a clear gate state. |
| [Heart Pulse](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-circular-8) | `dotm-circular-8` | First | Waiting / attention cadence | Its double-beat timing is a useful reference; pair attention with a stable identifying shape rather than rhythm alone. |
| [Star Compass](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-circular-9) | `dotm-circular-9` | Useful | Attention / directional cue | Four sector accents give distinct beats; avoid using direction as a status encoding without a clear convention. |
| [Binary Bloom](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-circular-10) | `dotm-circular-10` | Alternative | General work | Stepped brightness groups suit eight levels, but their coded appearance does not convey a specific session fact. |
| [Lunar Breathe](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-circular-11) | `dotm-circular-11` | Alternative | Quiet waiting | The crescent silhouette is recognizable at 5×5; reduce rotation speed if used for an ambient waiting state. |
| [Arc Beacon](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-circular-12) | `dotm-circular-12` | Useful | Search / tool activity | Directional beam steps are easy to sample; simpler than a soft continuous radar when brightness is quantized. |
| [Twin Helix](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-circular-13) | `dotm-circular-13` | Useful | Producing output | The mirrored strands can work in a dedicated 5×5 area; do not reduce this one to 3×3. |
| [Rung Shift](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-circular-14) | `dotm-circular-14` | Useful | Producing output | The row emphasis gives a readable ladder rhythm; simplify side sway if it muddies the main motion. |
| [Glyph Cluster](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-circular-15) | `dotm-circular-15` | Alternative | Custom status glyphs | Grouped dots are technically straightforward; select a meaningful motif instead of a perpetual symbol carousel. |
| [Rail Scan](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-circular-16) | `dotm-circular-16` | Useful | Scanning / response activity | The left/right rail scan has a clear direction and a short wake; it can be redrawn for a narrower region. |
| [Checker Shift](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-circular-17) | `dotm-circular-17` | Defer | Decorative alternate theme | Checker phases are easy to generate but look restless and overlap visually with pixel noise. |
| [Pulse Pair](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-circular-18) | `dotm-circular-18` | First | Needs user input | The paired inward pulse gives an attention rhythm distinct from a chase; keep a steady attention marker visible. |
| [Orbit Cell](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-circular-19) | `dotm-circular-19` | Alternative | Tool execution | An inner orbit is workable but offers less distinction than an ordinary perimeter chase. |
| [Glyph Cycle](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-circular-20) | `dotm-circular-20` | Alternative | Custom status glyphs | Ghosted symbol transitions are useful; map each glyph to a real state instead of cycling them arbitrarily. |

### Triangle masks: 7×4 occupied area

| Reference | ID | Decision | Candidate role | Adaptation / reason |
|---|---|---|---|---|
| [Core Spokes](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-triangle-1) | `dotm-triangle-1` | Alternative | Tool execution | The current source follows the perimeter rather than radiating spokes; keep the path if choosing a triangle theme. |
| [Altitude Wave](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-triangle-2) | `dotm-triangle-2` | Useful | Waiting for model | A slow vertical brightness wave retains the triangle silhouette without a complex path. |
| [Corner Bounce](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-triangle-3) | `dotm-triangle-3` | Alternative | Search activity | Current source implements a rotating beam rather than a literal corner bounce; use its actual motion as the reference. |
| [Vertex Chase](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-triangle-4) | `dotm-triangle-4` | Alternative | Tool execution | Several heads share a short perimeter; reduce head count for an uncluttered status. |
| [Row Sweep](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-triangle-5) | `dotm-triangle-5` | Useful | Producing output | A back-and-forth row scan is clear and straightforward after cropping the empty outer rows. |
| [Braille Beat](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-triangle-6) | `dotm-triangle-6` | Defer | Alternate theme | The staged fills, blinks, and resets are busy and can resemble progress; shorten to one consistent beat if revisited. |
| [Oblique Weave](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-triangle-7) | `dotm-triangle-7` | Useful | Producing output | Diagonal brightness fronts transfer well; the secondary harmonic may be unnecessary with only ten active dots. |
| [Wing Metronome](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-triangle-8) | `dotm-triangle-8` | Useful | Needs user input | Alternating left/right emphasis is an effective attention cadence if the triangular space is available. |
| [Corona Tier](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-triangle-9) | `dotm-triangle-9` | Alternative | Waiting for model | Distance bands create a gentle pulse, but a square or circular ripple uses a dedicated 5×5 region more efficiently. |
| [Column Rake](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-triangle-10) | `dotm-triangle-10` | Alternative | Tool execution | The column-ordered traversal is feasible; a compact rectangular chase is easier to recognize in a small region. |
| [Shelf Descent](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-triangle-11) | `dotm-triangle-11` | Useful | Producing output | Descending brightness shelves provide a clear directional alternative to diagonal waves. |
| [Skew Drift](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-triangle-12) | `dotm-triangle-12` | Useful | Producing output | The opposite diagonal direction is useful as a theme option; avoid relying on direction alone for different meanings. |
| [Serpent Zip](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-triangle-13) | `dotm-triangle-13` | Alternative | Long-running work | A ten-dot traversal can be sampled compactly, but its zigzags need room to remain readable. |
| [Pillar Sweep](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-triangle-14) | `dotm-triangle-14` | Useful | Scanning / response activity | A moving vertical slice is simple and readable; the rectangular interpretation also works in a 5×5 region. |
| [Tripod Handoff](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-triangle-15) | `dotm-triangle-15` | Useful | Attention cadence | Three corner accents are spatially distinct; keep the timing slower than routine tool motion. |
| [Updraft](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-triangle-16) | `dotm-triangle-16` | Useful | Producing output | The V-shaped brightness front is distinctive and feasible; keep the shape broad enough for eight-level output. |
| [Infinity Trace](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-triangle-17) | `dotm-triangle-17` | Alternative | Long-running work | The crossing route is a viable style option, but has less immediate status meaning than a simple sweep. |
| [Hollow Shell](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-triangle-18) | `dotm-triangle-18` | First | Quiet waiting / heartbeat | Breathing around a dim center is calm and readable; the pulse can also be reinterpreted on a 5×5 square. |
| [Pivot Ray](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-triangle-19) | `dotm-triangle-19` | Useful | Search activity | A rotating angular highlight is feasible; use it as an alternative to Radar Arc rather than another simultaneous spinner. |
| [Twin Perimeter](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-triangle-20) | `dotm-triangle-20` | Alternative | Tool execution | Opposed heads give a balanced loop; consider one head if other regions are also animated. |

### Hexagonal patterns: redraw for square cells

| Reference | ID | Decision | Candidate role | Adaptation / reason |
|---|---|---|---|---|
| [Hex Orbit](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-hex-1) | `dotm-hex-1` | Redraw | Tool execution | Preserve the chase rhythm, then redraw the path on square cells; exact staggering needs a wider layout. |
| [Prism Bloom](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-hex-2) | `dotm-hex-2` | Redraw | General work | The spokes and center pulse can become a square-grid bloom; the honeycomb arrangement is not a direct 5×5 mapping. |
| [Honey Gate](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-hex-3) | `dotm-hex-3` | Redraw | Producing output | Opposed diagonal bands make a useful idea, but redraw their meeting line on the rectangular grid. |
| [Vertex Relay](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-hex-4) | `dotm-hex-4` | Redraw | Attention / handoff accent | Corner-to-corner emphasis can work with four square corners; retaining six vertices needs more space. |
| [Spiral Lattice](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-hex-5) | `dotm-hex-5` | Defer | Decorative alternate theme | Intersecting swirl fields lose identity after spatial and brightness quantization; keep for a larger display study. |
| [Chevron March](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-hex-6) | `dotm-hex-6` | Redraw | Producing output | The chevron rhythm is a strong reference; redraw it as a square-grid arrow or V-wave rather than packing hex dots. |
| [Hourglass Flip](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-hex-7) | `dotm-hex-7` | Redraw | Waiting for model | An upright hourglass sequence could give a useful waiting symbol; simplify the star/diamond changes. |
| [Glyph Flip](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-hex-8) | `dotm-hex-8` | Redraw | Custom status glyphs | The discrete-mask approach is useful; build our own square-grid symbols with deliberate meanings. |
| [Petal Shimmer](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-hex-9) | `dotm-hex-9` | Defer | Decorative alternate theme | Petal highlights and shell sheen are visually subtle; better studied on the future TFT. |
| [Liquid Vortex](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-hex-10) | `dotm-hex-10` | Defer | Decorative alternate theme | The soft moving field is attractive but weak as a compact, distinguishable session indicator. |

### Compact 3×3 patterns

| Reference | ID | Decision | Candidate role | Adaptation / reason |
|---|---|---|---|---|
| [Square Spiral](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-3x3-1) | `dotm-3x3-1` | Useful | Compact tool execution | An inward nine-cell route fits easily; a short tail leaves more visual separation than the original long tail. |
| [Drift TR](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-3x3-2) | `dotm-3x3-2` | Useful | Compact response activity | The directional diagonal band fits a small region directly; treat all four directions as one configurable family. |
| [Drift TL](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-3x3-3) | `dotm-3x3-3` | Useful | Compact response activity | A direct square-grid fit; choose this or its reverse as a style preference, not a hidden semantic distinction. |
| [Drift BR](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-3x3-4) | `dotm-3x3-4` | Useful | Compact response activity | A direct square-grid fit; keep the same direction convention across related status patterns. |
| [Drift BL](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-3x3-5) | `dotm-3x3-5` | Useful | Compact response activity | A direct square-grid fit; collapse the four variants into one preset with a direction option. |
| [Core Echo](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-3x3-6) | `dotm-3x3-6` | Useful | Small acknowledgment | Three distance tiers make a compact pulse; use a single pass for a new event. |
| [Column Flux](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-3x3-7) | `dotm-3x3-7` | First | Compact producing output | Three column bands are legible; the same idea scales naturally to a horizontal strip or a 5×5 region. |
| [Row Sweep](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-3x3-8) | `dotm-3x3-8` | First | Compact producing output | Three row bands are simple and distinct from a perimeter chase; useful beside a tool animation. |
| [Serpent](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-3x3-9) | `dotm-3x3-9` | Useful | Compact tool execution | A nine-position serpentine path fits well; distinguish it from the primary tool chase before keeping both. |
| [Frame Chase](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-3x3-10) | `dotm-3x3-10` | First | Compact tool execution | The eight-cell border gives a clear busy loop; keep the center dim to avoid a second competing rhythm. |
| [Glyph Pulse](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-3x3-11) | `dotm-3x3-11` | Alternative | Custom status glyphs | The morphing mechanism works at fixed LED positions; replace the arbitrary glyph sequence with chosen status symbols. |
| [Drop Ripple](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-3x3-12) | `dotm-3x3-12` | Useful | Small acknowledgment | A direct compact ripple; compare with Core Echo and keep one if they look too similar in hardware. |
| [Right Surge](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-3x3-13) | `dotm-3x3-13` | Useful | Compact producing output | The reversed column sweep is a useful direction option, not a separate required animation. |
| [Comet Trail](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-3x3-14) | `dotm-3x3-14` | First | Compact tool execution | A bright head with two dimmer trailing pixels is an excellent eight-position loop. |
| [Echo Rings](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-3x3-15) | `dotm-3x3-15` | Useful | Quiet heartbeat | A softer ripple option; inspect against Core Echo and Drop Ripple to avoid three nearly identical presets. |
| [Smiley Spin](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-3x3-16) | `dotm-3x3-16` | Defer | Character theme | The rotating face fits technically, but loses facial readability; a stationary face with a blink is a better session symbol. |
| [Check Spin](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-3x3-18) | `dotm-3x3-18` | Adapt | Completed outcome | Keep the check upright. Borrow the brightness transition, play once, and hold instead of rotating continuously. |
| [Arrow Spin](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-3x3-19) | `dotm-3x3-19` | Adapt | Transition / direction cue | The glyph stays on fixed cells; use an upright reveal or directional sweep rather than a perpetual spin. |
| [Corner Spin](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-3x3-20) | `dotm-3x3-20` | Useful | Compact tool execution | Quarter-turn corner masks give a small spinner alternative; test legibility against Frame Chase. |
| [Play Spin](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-3x3-21) | `dotm-3x3-21` | Adapt | Turn started / resumed | Use the stationary play shape as a short acknowledgment; continuous rotation makes the symbol less meaningful. |

## What the next studio iteration should expose

1. Give 5×5 and 3×3 equal access in the preset picker, with a region-size hint
   and explicit cropping/redraw choices for other shapes.
2. Paint intensity 0–7, not just on/off; preview every generated frame at the
   actual quantized levels. Keep browser bloom optional so it cannot hide poor
   pixel contrast.
3. Offer a small set of parameterized families: pulse, row/column/diagonal sweep,
   fading path chase, rotating blade, traveling strand, and symbol transition.
   Four diagonal directions should be one configurable family rather than four
   different status meanings.
4. Separate loops from event accents. Stop/supersede an old clip when the region
   changes state; a completion accent must not delay a new turn.
5. Compare several live regions together and retain a small unguided output
   preview. Judge the difference between waiting, output, tools, and attention
   without relying on color or editor labels.

For a first hardware experiment, author a shared 16- or 24-frame cycle with
three or four visibly separated intensity values, then expand if more levels
help. These are proposed starting budgets, not measured timing guarantees.
The MCU still has one animation buffer: combining region loops may exceed 32
frames even when each individual clip fits. Baking, common timing, storage,
wire encoding, and telemetry need an explicit grayscale controller design.

Use these animations as visual references and write a small renderer appropriate
to the board. If reusing upstream source directly, review its
[actual license](https://github.com/zzzzshawn/matrix/blob/e30b80a9c5e6fe388ecbbbac15abfd14f24d0dd3/LICENSE),
which differs from what the gallery's open-source label might suggest.

Related: [session studio design](2026-10-24-session-display-studio.md),
[fx feedback design](2026-10-24-fx-hardware-feedback.md).
