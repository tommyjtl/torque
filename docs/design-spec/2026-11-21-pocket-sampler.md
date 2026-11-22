# Torque pocket sampler for the UNO Q

**First playable version · November 21, 2026.** Make a beat with the K0 Max while the Waveshare shows the selected sound, pattern, tempo, steps and two parameter dials. Both the local browser preview and the native Mojo/SDL2 desktop instrument are playable. On the UNO Q, open the **B.A.P.** desktop shortcut. [Native build, controls and board evidence](../../projects/pocket-instrument/native/README.md). [Open the instrument](../../projects/pocket-instrument/index.html)

## The first minute

Press keypad **+** to hear the starter beat at 96 BPM. Tap **△**, then **Num** (pad 02) to switch to an empty pattern. Tap **○**, then **M3** (pad 09) for the Break kit. Play **M1** to pick the kick. Tap **Enter** for Write, then tap the first key of each row to put kicks on steps 1, 5, 9 and 13. Tap Enter to return to playing pads. Pattern 01 still contains the starter beat. The on-screen controls do the same thing, including on a laptop without a numpad.

For a first recording, stop the loop with **+** if it is running. Tap **top-row ×**, then **Num** to choose slot 02. Allow the microphone prompt and speak when the LCD says **RECORDING**. The LCD counts down during capture and the take saves at eight seconds (sooner if the shared budget is nearly full). Tap × to finish early. Pad 01 plays the first sixteenth of the saved audio, pad 02 the next, and pad 16 the last. The browser keeps recordings and patterns in memory for this session. Reloading starts a fresh instrument.

## Instrument and references

The linked simulator demonstrates how keyboard playing, sample slots and a sequencer translate to a browser. It models the PO-20 Arcade in p5.js. The target here is the PO-33 K.O! workflow. Its eight melodic and eight drum slots give the same sixteen keys three jobs — pitches, slices and sequencer steps. The preview uses original generated sounds and original monochrome boxing artwork. [Reference simulator](https://github.com/franeklubi/pocket-operator-simulator) · [PO-33 product](https://teenage.engineering/store/po-33) · [PO-33 operator guide](https://teenage.engineering/guides/po-33/en)

| Operation | Local v1 | Toward the PO-33 |
|---|---|---|
| Play and sample | Eight pitched slots and eight kits with factory sounds. Record into any slot, with a shared 40-second budget for user takes. A new take replaces its slot only after decoding succeeds. Factory melodic sounds span 16 chromatic notes. Every recorded take is capped at eight seconds and divided into 16 consecutive equal slices, in either bank. | Add transient-aware slicing, trim start/length per slice, and a choice of mic or line input where available. Compare note layout, envelope and voice-stealing against the guide and by ear. |
| Sequence | Sixteen patterns of sixteen sixteenth-note steps. Each slot has one lane and one note per step. Write adds the last auditioned note or removes an occupied step. Start/stop, 60–240 BPM, per-pad pitch within each slot and per-slot volume, and 16 hold-to-apply performance effects. | Add swing, quantized live entry, pattern chaining, parameter locks and timed punch-in effects. Prioritize retrigger and reverse after the basic timing trial. |
| Recall | The browser session owns the current kit and patterns. | Add versioned local save/restore with PCM and patterns in one project. Verify round-trip playback and recovery after an interrupted save before using it for kept takes. |

## K0 Max input contract

Interpret “M1 → 3” spatially, reading across each row. The numbered keycap 3 is **step 16**. The faceplate shows pad numbers 1–16. The controls guide lists their physical K0 keys. The square and cross refer to the top-row symbols. The multiplication key in the pad grid is a separate switch.

| Steps | K0 keys, left to right | Browser event codes after proposed mapping | Laptop alternative |
|---|---|---|---|
| 01–04 | M1, Num/Clear, ÷, * | Digit1, Digit2, NumpadDivide, NumpadMultiply | 1 2 3 4 |
| 05–08 | M2, 7, 8, 9 | KeyQ, Numpad7, Numpad8, Numpad9 | Q W E R |
| 09–12 | M3, 4, 5, 6 | KeyA, Numpad4, Numpad5, Numpad6 | A S D F |
| 13–16 | M4, 1, 2, 3 | KeyZ, Numpad1, Numpad2, Numpad3 | Z X C V |

| Physical control | Launcher assignment or existing event | Action |
|---|---|---|
| ○, △, □ | T, Y, U | Sound and Pattern arm the next pad. BPM enters or leaves tempo adjustment. |
| Encoder press | O | Select dial A or B. The LED above the selected dial lights up. |
| Decimal | NumpadDecimal | On the UNO Q desktop this quits B.A.P. In the web preview this restores the active parameter. Pitch resets to 0 semitones for the last played pad in the selected slot. Volume resets to 50% for the selected slot. In BPM mode resetting A restores 96 BPM, and resetting B restores the slot volume. |
| Encoder counterclockwise / clockwise | Left bracket / right bracket | A tunes the last played sound pad by a semitone, within ±12. Its tuning applies to auditions and every step playing that same pad in that slot. B adjusts slot volume by 5 percentage points. Entering BPM selects A for tempo in 1 BPM steps. B continues to adjust the selected slot’s volume. Same-direction detents up to 100 ms apart use 2× steps, increasing to 4× at 45 ms or less. The first detent after a pause, reversal or control change uses 1×. |
| Top-row × | I | Arm Record to see the recorded-slot count and identify every slot. All 16 pad LEDs use the same red glow as Record. Orange numbers identify saved user recordings. During capture the destination pad LED alternates one second on and one second dim; reduced-motion mode uses a steady light. Plain numbers identify factory sounds. Choose a destination pad, then tap Record to finish. The remaining user sample budget caps the take. |
| Minus | NumpadSubtract | Hold FX during playback and press a numbered pad for its loop effect. Releasing FX immediately restores the dry loop, even with pads held. Overlapping presses use the newest held pad, and releasing it resumes the previous one. The controls guide lists the bank in pad order. The last pad release restores the dry loop. FX pads do not trigger notes or write steps. |
| Plus | NumpadAdd | Play / stop. |
| Enter | NumpadEnter | Toggle Write. |
| 0 | Numpad0 | Start a fresh factory session immediately, clearing recordings, pattern edits and settings. |
| Escape | Escape | In web 2D, stop playback. In native 2D, exit the app. In either 3D view, return to the faceplate. |

**Launcher profile.** Use Layer 0 for this K0 Max. In Keymap, select the knob center and assign the Basic letter O to its press. Set the two rotation directions to the bracket keys. Keep the top-row × on I for recording. In the web preview, P toggles a WebGL 2 inspection of a concept enclosure inside the same portrait viewport. M5 can send P on tap and retain Fn on hold using QMK's layer-tap assignment `LT(1, KC_P)` if supported by the installed Launcher/firmware. Alternatively use ordinary P on a dedicated performance layer. A layer-only Fn press does not emit P. The native desktop build uses the same P binding and enclosure geometry through OpenGL ES. The hardware sends ordinary key events to the focused sampler. [K0 Max manual](https://www.keychron.com/pages/keychron-k0-max-user-manual) · [Launcher remapping](https://www.keychron.com/blogs/news/keychron-launcher-guide)

## Screen, sound and runtime decision

The shipped UNO Q implementation is the [native Mojo sampler](../../projects/pocket-instrument/native/README.md). The browser remains the local design reference. The prototype comparison below records the earlier framework evaluation.

The Linux MPU owns the DSI display, keypad, audio capture and output. The MCU has no role in this release. The instrument uses a single vertical 480×640 faceplate. The LCD sits above the selector keys and dials, followed by the pad grid and transport. The main control area is 392 pixels wide, beside a 54-pixel graphite strip with the mallet and vertical TORQUE wordmark centered beside the LCD. Orange brackets on the left mark melodic slots 1–8 and drum slots 9–16. The Reset control sits at the foot of the strip, aligned with Write, with a thin border around its icon. The web preview places its controls guide in the page margin when space permits. The native portrait Waveshare fills the frame. A wider or shorter browser centers the same 3:4 panel and scales it to fit. Space Grotesk carries the printed legends and DSEG7 Classic renders tempo and pattern behind the gray glass. The boxers move with the beat, 48 narrow ticks between IN and OUT normally show the mixed output level. Turning a dial displays the adjusted parameter across its range for 1.2 seconds after the last turn, and the LCD prompts for the next action. Touch and mouse use the same actions as the keypad. The pitch and volume dials start at twelve o’clock (0 semitones and 50% volume) and rotate freely in either direction. Each detent moves the selected shaft 15° even at a parameter limit; acceleration affects the value only. They support vertical dragging and wheel adjustment. [Native display capture](../../projects/pocket-instrument/native/evidence/uno-q.png)

| Candidate | Evidence and tradeoff | Decision |
|---|---|---|
| HTML + Web Audio in Chromium | The same files run the local preview and can run on the UNO Q desktop. AudioContext provides a scheduling clock, buffer playback with pitch control, filtering and a microphone capture path. Chromium process overhead, audio buffering and Bluetooth latency on this board need measurement. | Try this build first on the Linux desktop. It gives us the fastest test of the actual playing experience. |
| pygame-ce + SDL audio or a callback-driven native audio engine | Torque measured 61.9 loop updates/s and 102.5 MiB peak process RSS in its 1,000-object pygame-ce trial, and separately verified live K0 input. This establishes rendering headroom for a small LCD. It gives no measurement of pad-to-speaker delay. Sampling, pitch shifts, slice boundaries and the audio clock still need implementation. | Keep pygame-ce as the native fallback if the browser misses the timing or resource budget. Port the action map, pattern representation and test groove first. Measure native audio with the same test. |

[Native runtime and board checks](../../projects/pocket-instrument/native/README.md#runtime)

**Timing.** The browser wakes the scheduler every 20 ms and submits notes up to 85 ms ahead on the audio clock. A live pad starts immediately on that clock. The LCD follows elapsed audio time. A stalled scheduler skips missed steps. Stop silences queued voices. A backgrounded page cancels capture and stops playback. Sample data stays local.

## Enclosure inspection

Open the local preview with `?view=3d`, use the page-margin 3D view control, or tap P. The sampler stays in its portrait 480×640 frame. The camera eases from the face to a side view on a 13-degree wire stand. Dragging or arrow keys orbit a fixed point on the instrument; the wheel zooms and Home returns to a face-on view. P or Escape returns to the playable panel. Reduced-motion users get an immediate change of view. The inspection surface reads the live panel and accepts orbit gestures. Physical keypad musical controls stay available.

The [native UNO Q port](../../projects/pocket-instrument/native/README.md#3d-inspection) uses SDL2 and the FD702 GPU. The web model uses locally vendored Three.js r180 (MIT), WebGL 2 meshes, environment lighting and an approximate contact shadow. The rear cells, wire stand and housing are a visual concept. Run `node bake-inspection.cjs` with the preview test dependencies after changing the faceplate layout or art to regenerate its print texture and layout measurements. [Open the model](http://127.0.0.1:8733/?view=3d)

## Test the preview

Open the [HTML file](../../projects/pocket-instrument/index.html) in Chrome for pad play. For a stable microphone permission origin, serve the project on localhost from the repository root.

```sh
python3 -m http.server 8733 --bind 127.0.0.1 --directory projects/pocket-instrument
```

Open [the local sampler](http://127.0.0.1:8733/). The instrument requires no build or network assets. To repeat the automated E2E test, use Node.js, local Google Chrome and the project's Playwright dev dependency.

```sh
cd projects/pocket-instrument
npm install
npm test
```

The test starts its own ephemeral loopback server and isolated browser. It generates a two-tone WAV (440 Hz followed by 740 Hz), supplies it to Chrome's virtual microphone and examines the final Web Audio signal. Set `CHROMIUM_PATH` to select another Chrome executable. Set `SHOT_DIR` to an existing directory to retain layout screenshots. [Executable E2E test](../../projects/pocket-instrument/e2e.cjs)

| Desktop E2E check | Result |
|---|---|
| Full controls visible and hit-testable at 480×640, 640×480, 375×667 and 1280×800 | Passed. [Portrait capture](../../projects/pocket-instrument/evidence/480x640.png) · [Vertical panel in a wide window](../../projects/pocket-instrument/evidence/640x480.png) |
| Start factory groove, detect output PCM, advance through step 16, wrap to step 1 and stop to silence | Passed. |
| All sixteen K0 pad codes, add/remove steps, switch patterns and recover the edited lane | Passed. |
| Select A/B, adjust pitch and volume, change BPM and toggle FX | Passed for controls and readouts. |
| Count down and auto-save a take in slot 02, verify 16 equal slice boundaries, hear 440 Hz on pad 1 and 740 Hz on sequenced pad 13, and verify slicing on an early stop in slot 16 | Passed. |
| Deny a replacement recording, preserve the named slot, operate pointer controls, open and dismiss the guide, stop with Escape | Passed. Zero uncaught page errors. |

The passing run used **Google Chrome 158.0.8127.36 on macOS**. The standalone headless-shell binary stalled at virtual microphone acquisition on this machine. Full Chrome completed the capture path. The desktop suite verifies browser behavior. The UNO Q checks covered native audio computation, capture-device selection, slice playback, 3D rendering, and launch and exit through the desktop shortcut. [Board verification](../../projects/pocket-instrument/native/README.md#installation-and-evidence)

## Remaining hands-on checks

1. In the playing position, operate each physical key once, turn the encoder in both directions, toggle A/B and check the post-reconnect mapping. Check for desktop volume changes or connection switching. Enter four kicks using only the K0. Verify mute/stop, record permission, and cleanup when the owned window closes.
2. **Proposed feel targets.** Measure at least 50 presses over USB and Bluetooth separately. Use a synchronized external recording of the switch contact/click and speaker transient to estimate end-to-end onset. Report median and p95 plus the measurement uncertainty. Aim for p95 at or below 40 ms. A browser event timestamp measures only the path after the OS delivered the press.
3. Run a two-minute four-on-the-floor loop at 120 BPM, including simultaneous lanes, knob turns and repeated screen updates. Capture the line output, count missing or duplicate hits and compare inter-onset intervals to the programmed grid. Aim for zero missing hits and p95 interval error below 5 ms. Record process RSS and CPU alongside the audio evidence. These are proposed thresholds to evaluate on the board.
4. Record a short spoken phrase into a melodic slot and a percussive phrase into a kit. Listen for pitch changes, cut boundaries, clicks and monitoring feedback. Confirm readability and dial selection with a person using the actual Waveshare. If timing misses, measure Bluetooth delivery, audio buffering and UI stalls separately. Advance to durable sample projects and richer PO-33 functions after this trial.
