# Dot Matrix Animations

Ten original, eight-level animations in a centered 5×5 region at (4,1) on the
UNO Q's 13×8 blue matrix. They adapt the motion ideas in the
[animation review](../../docs/design-spec/2026-10-24-animation-reference-review.md);
no upstream component source is included.

| Key | Animation | Motion | Frames | Nominal loop at 25 ms |
|---|---|---|---:|---:|
| 1 | Half Helix | One traveling sine strand | 24 | 0.600 s |
| 2 | Neon Drift | Diagonal brightness front from top-right toward bottom-left | 24 | 0.600 s |
| 3 | CRT Glide | Downward scanline with a fading wake and dark rows ahead | 30 | 0.750 s |
| 4 | Echo Ring | Centered outward pulse with a weaker echo | 32 | 0.800 s |
| 5 | Origin Wave | Outward wave from local (1,1) | 32 | 0.800 s |
| 6 | Prism Bloom | Crossfading star, diamond, petals and cross | 32 | 0.800 s |
| 7 | Sound Bars | Five changing synthetic bars | 24 | 0.600 s |
| 8 | Mobius Run | Outer-edge chase with corner-fold accents | 32 | 0.800 s |
| 9 | Plasma Veil | Two circular perimeter chases around a dim center | 24 | 0.600 s |
| — | Heart Pulse | Circular glow with a strong beat, weaker beat and quiet tail | 28 | 0.700 s |

The default frame step is 25 ms. Use
`--frame-ms 80` to restore the original timing.

Key 3 uses the [CRT Glide reference](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-square-10):
a stepped top-to-bottom scanline with a fading wake. The
[reviewed motion source](https://github.com/zzzzshawn/matrix/blob/e30b80a9c5e6fe388ecbbbac15abfd14f24d0dd3/loaders/loaders/dotm-square-10.tsx)
informs this original hardware adaptation. Each row is held for six frames;
the small web column warp is omitted for consistent quantized contrast.

Heart Pulse references [circular preset 8](https://dotmatrix.zzzzshawn.cloud/playground?loader=dotm-circular-8)
and its [reviewed motion](https://github.com/zzzzshawn/matrix/blob/e30b80a9c5e6fe388ecbbbac15abfd14f24d0dd3/loaders/loaders/dotm-circular-8.tsx).
It uses an original double-beat envelope on 21 circularly masked dots, with a
dim shell. It is available by name and in offline previews, without a number
key or a tenth resident slot in the live gallery. To match Torque's idle cue:

```bash
torque example dot-matrix-animations --animation heart-pulse --peak 5 --frame-ms 50 --repeat 3
```

Run the packaged reference directly:

```bash
torque example dot-matrix-animations
torque example --mode preview dot-matrix-animations
```

The manifest supplies launch defaults and a workspace output directory. Script
options still work after the slug, for example `--frame-ms 40` or `--input terminal`.
See the [command reference](../../docs/cli.md#run-a-bundled-example).

Generate all ten SVG previews offline from the repository root:

```bash
PYTHONPATH=packages/session/src:packages/device/src python3 examples/06-dot-matrix-animations/main.py
```

Open the SVGs under `projects/dot-matrix-animations/`. Preview mode never opens
input devices, changes terminal settings, or connects to a board. It shows
quantized native levels 0..7 with discrete frames. Faint unlit dots reveal the
grid; browser brightness is not an optical measurement of physical LEDs.

Select one animation or tune the peak/timing:

```bash
PYTHONPATH=packages/session/src:packages/device/src python3 examples/06-dot-matrix-animations/main.py \
  --animation neon-drift --peak 4 --frame-ms 100
```

Use `--output-dir PATH` for the gallery, or `--preview FILE.svg` with one
`--animation`. New generated variations belong in `projects/`.

## Playback and keyboard selection

Playback uses the matched 0.4.0 controller/SDK and a ready Torque daemon. It uploads
the nine clips once at startup, then switches with one playback command per
keypress. Selecting a single animation by name uploads only that clip.
Sound Bars are synthetic activity, not measured audio. See the
[grayscale spec](../../docs/design-spec/2026-10-24-matrix-grayscale.md).

Copy this folder into `~/torque/projects/dot-matrix-animations/` on the UNO Q.
When execution is requested, from the Torque workspace:

```bash
torque run projects/dot-matrix-animations/main.py --play
```

Default `--input auto` discovers a **readable Bluetooth Keychron K0 Max Keyboard**
through the shared `torque.input.Keypad` API on Linux. It discovers event numbers
dynamically and verifies the opened descriptor's identity and numpad capabilities.
It excludes the companion Mouse interface and claims the shared project input
lease. It needs the existing
input-node read permission and never changes pairing, groups, modes, services,
key mappings, or MCU firmware. Identity and key codes come from the
[Keychron journal](../../docs/journal/2026-10-24-keychron-k0-max-bluetooth.md).

No address is embedded in the example or its presets. One verified readable
keypad is selected automatically. Several matching devices require explicit
selection; the gallery never takes the first match. Use an address returned by
local `input_capabilities()` discovery:

```bash
torque example dot-matrix-animations --keyboard-address "<KEYPAD_BT_ADDRESS>"
```

The placeholder is documentation only. Real selectors belong in runtime arguments
or user-local configuration outside Git. A busy input lease, ambiguous discovery
or missing explicitly selected device reports an error before the matrix is
acquired; these cases do not silently turn into autoplay. `--keyboard-address`
is only for `--input auto` or `keyboard`, without a single `--animation`.

With the Keychron available, press **1–9** to play the selected
animation **continuously** until another preset is selected. A new selection
supersedes the current clip; selecting the active preset keeps its loop running.
Numpad keys and number-row events map to the same nine presets. Repeats and keys
already held at startup/resync are ignored. Escape or Ctrl-C clears
the matrix and exits.

If no readable Keychron is found in automatic mode without an explicit address,
the script runs **three rounds** of the complete
nine-preset gallery, one loop of each per round, then exits. A keyboard
disconnect also falls back to that finite gallery. The shared helper clears held
state and releases its input lease on disconnect. `--repeat N` changes gallery
rounds; keyboard selections always loop until switched or stopped.

The physical Keychron sends events to the UNO Q; those events do not type into
your laptop's SSH terminal. To use the laptop/SSH keyboard explicitly instead:

```bash
ssh -t arduino@tommy-uno-q.local \
  'torque run ~/torque/projects/dot-matrix-animations/main.py --play --input terminal'
```

Terminal mode accepts 1–9 and q/Escape, restoring terminal settings on exit.
`--input keyboard` requires a readable Keychron and reports an error if missing.
`--input none` always runs the finite gallery. With a single `--animation`,
keyboard selection is disabled and `--repeat` repeats only that clip:

```bash
torque example dot-matrix-animations --animation crt-glide --repeat 1
```

Input polling uses 10 ms waits; playback health is sampled separately at
250 ms. In cache mode no frame upload occurs during a switch. These are
software scheduling choices, not a measured optical latency guarantee. Cache
slots disappear on MCU reset and are preloaded again on program restart.

All MCU access uses `from torque import Board, Frame`. Playback is buffered on
the MCU, with status queries observing completion. Normal completion, Ctrl-C,
SIGTERM, or an observation timeout requests clear when communication remains
available. Hard kills and lost connections cannot guarantee cleanup. Torque
resumes its normal status display when the program releases ownership.
