# UNO Q verification

The test board is an ARM64 Arduino UNO Q running Linux. Both binaries executed the original Quake 1.06 shareware program. The OpenGL driver identified the device as `FD702` and compiled the project's lightmapped brush shader.

| Check | Software | Adreno |
|---|---|---|
| Load the original start map, E1M1–E1M7, and E1M8 separately | 9 of 9, 360 ticks each | 9 of 9, 360 ticks each |
| Walk the Normal difficulty hall into E1M1 | Entered on input 400 | Entered on input 400 |
| Replay the recorded Slipgate Complex encounter | 2 of 23 enemies defeated, 1 secret, 200 health | 2 of 23 enemies defeated, 1 secret, 200 health |
| Simulation hash after input 1,538 | `a5ef55d7` | `a5ef55d7` |

The encounter uses the original shotgun, collects shells and the 100-health pickup. These runs used SDL dummy audio and accelerated simulation. They establish gameplay under the two renderers. The remaining campaign checks include a continuous run to Chthon and a second run through the secret exit. The physical K0, mouse and mounted speaker require a hands-on playtest.

## First level and desktop

The [hub to E1M2 recording](../replays/normal-hub-to-e1m2.trace) runs from the original start on Normal. Both installed binaries exited E1M1 after command 3,629 with 21 of 23 enemies defeated and 88 health. Both arrived at the Castle of the Damned with 88 health and matched hash `22ecf19a` after command 3,884. The CPU recorded 4,279,578 textured wall pixels. Adreno recorded 1,098 shader batches. Both executed 929,310 QuakeC instructions and 67,294 swept hull traces.

The desktop entry's CPU action launched fullscreen, accepted a synthetic keypad save and quit, and created a 34,502-byte save in an isolated profile. The default GPU action loaded that save and quit with keypad 0. A private PipeWire sink measured a peak of 12,324 on a signed 16-bit scale. This checks that samples reach the audio server. A person still needs to confirm the physical speaker and input devices.

The initial hub frame-time samples ran while three abandoned PipeWire test clients were active. Each consumed nearly one core. The release timing below uses fresh measurements after closing those three clients and verifying their private sinks had disappeared.

## Moving-lift recovery

The player returns to the E1M1 lift with the nailgun. At command 2,153 the board counted one moving lift and four live projectiles. A fresh Adreno process loaded the CPU save, and a fresh CPU process loaded the Adreno save. In each direction all six full-state digests matched uninterrupted play. The restore digest was `743d2165`. After the remaining 278 commands it was `2a3bcc62`. The digest covers every VM global and entity word, dynamic strings, spatial link order, RNG, time, view and inventory. The game continued along the same six checkpoints after loading a truncated file or a file containing a different map fingerprint. A version 5 quicksave from the previous desktop release also loaded into the new CPU build.

Run `python3 verify_snapshot.py /path/to/binaries /path/to/media` with the UNO Q's X11 display. It creates an isolated temporary profile, runs both backend directions and cleans up the test saves. The two builds draw to hidden windows during this check. [Input recording](../replays/moving-lift.trace)

## Original movement room

The UNO Q ran the same recording in the SDL dummy CPU backend, the X11 CPU backend and the FD702 OpenGL backend. The nine checkpoint rows matched byte for byte across all three. They include velocity, position, grounded flags and water level. The game finished command 394 on dry ground at x=559.97, z=24.03 with hash `b209c196`.

| Command | Observed game state |
|---|---|
| 30 | At rest on the entrance floor, z=24.03 |
| 122 | Climbed 32 units to the raised deck, z=56.03 |
| 157 | Jump stopped against the beam, z=63.97, vertical velocity zero |
| 159 | Falling from the beam at 22.22 units per second |
| 229 | Falling past the ledge at 144.44 units per second |
| 279 | Submerged at water level 3, z=−47.97 |
| 394 | Climbed out onto the far floor, grounded at water level 0 |

The board used the project's own compiled BSP and the separate LibreQuake verification directory. [Fixture and reproduction](../fixture/README.md)


## Continuous campaign coverage

Both ARM64 builds played the original Normal difficulty hall, the Slipgate Complex and the Castle of the Damned with the same ordinary movement inputs. In E1M2 the player collected the silver key, opened its door, activated the floor switch and crossed the exit with 50 health and 16 of 24 enemies defeated. The board reached E1M3 at command 8,690. The player obtained the gold key, operated the lifts, opened the gold door and completed the Necropolis with 12 of 47 enemies defeated. Both renderers entered E1M4. The player obtained its silver key, operated all five floor switches and took the regular exit with 55 health and 20 of 42 enemies defeated. Both builds entered Gloom Keep, with hash `f44e96f3` after command 23,074. [Continuous recording](../replays/ordinary-route.trace)

| Map | Entry/exit state from continuous board replay | Further coverage |
|---|---|---|
| start | Normal hall and Episode 1 slipgate | Check return with first rune |
| E1M1 | Exit tick 3,629 · `cb975cdd` | Verified |
| E1M2 | Exit tick 8,453 · `6fdf4149` | Verified |
| E1M3 | Exit tick 17,294 · `6db42f0f` | Verified |
| E1M4 | Ordinary exit tick 22,826 · `79423fc2` | Verify secret exit |
| E1M5 | Ordinary entry · `7833e4e2` | Verify secret-route entry and exit |
| E1M6 | Map start | Verify exit |
| E1M7 | Map start | Verify Chthon, rune, ending and return |
| E1M8 | Map start | Verify secret traversal and gravity reset |

## Real-time board measurements

The default Adreno renderer presents a 640 × 480 image. CPU mode draws 320 × 240 and scales it to the same display. Both ran with their default vsync enabled, fixed 72 Hz simulation and 60 Hz display scheduling. The game submitted sound to an isolated PipeWire sink. The measurement window starts after the accelerated replay prefix. RSS is the process peak in MiB and CPU seconds cover the measurement window. [Reproduction script](../verify_timing.py)

| Scene | Renderer | Frames / seconds | Median ms | p95 ms | Worst ms | CPU seconds | Peak MiB | Audio underruns |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| E1M1 fight | CPU | 433 / 7.22 | 16.66 | 17.29 | 21.12 | 4.16 | 122.2 | 0 |
| E1M4 water surface | CPU | 312 / 5.20 | 16.67 | 17.16 | 21.18 | 2.54 | 122.2 | 0 |
| E1M1 → E1M2 | CPU | 186 / 4.58 | 16.65 | 20.48 | 919.47 | 2.12 | 126.2 | 2 |
| E1M1 fight | Adreno | 433 / 7.22 | 16.66 | 17.11 | 18.57 | 2.67 | 132.1 | 0 |
| E1M4 water surface | Adreno | 312 / 5.20 | 16.67 | 17.15 | 21.29 | 1.74 | 128.1 | 0 |
| E1M1 → E1M2 | Adreno | 201 / 3.74 | 16.67 | 17.19 | 248.72 | 1.42 | 134.7 | 2 |

Adreno averaged 60 frames per second in the fight and water samples. Its p95 stayed below 20 ms in all three samples. The level change still loads synchronously and causes a visible pause and two audio underruns. Both renderers retained every scheduled simulation tick through these samples.

## Renderer comparison and restart

The board captured matching 320 × 240 views of the moving E1M1 entrance door at command 703, a grunt partly behind cover at command 3,084 and the E1M4 water surface at command 544. Door edges, the intervening wall and the water boundary align. Palette shading, particle shapes and texture filtering differ between backends. Software PCX captures now use the same active palette as the live display, including underwater color shifts. The stationary start-hall views from both backends matched the corridor layout, camera height and torch placements in a separate capture from the pinned upstream C renderer. Only the profile-directory hook was changed for the upstream capture. The private images are in `build/verification/matched`.

An alternate E1M3 recording stayed on the lift long enough for the player to die. At command 17,535 the CPU reported −1 health and 12 kills. Pressing fire restarted the Necropolis through its normal gameplay logic. At command 17,795 the player was back at the original spawn with 50 health, 25 shells and zero kills. The [complete alternate recording](../replays/death-restart.trace.gz) begins at the original difficulty hall. Decompress it before passing it to `-mqreplay`.
