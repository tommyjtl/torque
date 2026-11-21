# Episode 1 desktop release · November 19, 2026

Desktop release `eb61e0f50aa4973e810e` is installed on the UNO Q. Installation verified the packaged files and preserved all existing player profile files. The packaged source archive contains the per-map inventory from the campaign runs. [Machine-readable checkpoints](episode1-checkpoints.json)

## Continuous campaign coverage

On November 19, 2026 the UNO Q finished both Normal routes in fresh CPU and Adreno processes. Each began at the difficulty hall, defeated Chthon and walked in the hub with the first rune. The ordinary route used 46,767 input ticks and matched at all 18 checkpoints. The secret route used 58,685 ticks and matched at all 20. Each pair also matched on the exact ticks of all nine boss-switch presses and all three lightning hits. The tested ARM64 binary SHA-256 digests begin with `8a0717810f37df0e` (CPU) and `210aa51f7b9f090b` (Adreno). [Ordinary recording](../replays/ordinary-route.trace) · [Secret recording](../replays/secret-route.trace) · [Verifier](../verify_campaign.py)

| Map and outcome | Ordinary exit tick · hash | Secret-route exit tick · hash |
|---|---|---|
| E1M1 · Slipgate Complex | 3,629 · `cb975cdd` | 3,629 · `cb975cdd` |
| E1M2 · silver key, door and floor switch | 8,453 · `6fdf4149` | 8,453 · `6fdf4149` |
| E1M3 · lifts and gold door | 17,294 · `6db42f0f` | 17,294 · `6db42f0f` |
| E1M4 · ordinary exit or two hidden controls and secret exit | 22,826 · `79423fc2` | 26,059 · `aa7379bb` |
| E1M8 · silver key, low gravity, exit to E1M5 | — | 34,729 · `c1af8ab4` |
| E1M5 · both keys and slipgate to E1M6 | 31,976 · `e755ec78` | 43,894 · `9ef6c94f` |
| E1M6 · keys, moving platforms and final gate | 40,996 · `5586b262` | 52,914 · `636a4098` |
| E1M7 · rune, three lightning strikes, exit shaft | 45,715 · `7d78100d` | 57,633 · `c5ab20e9` |
| E1M7 · original finale text | 46,040 · `5d34341a` | 57,958 · `cfe2aaa6` |
| start · returned hub with rune | 46,694 · `842c541b` | 58,612 · `842c541b` |

Gravity was 100 throughout the E1M8 checkpoints and 800 upon re-entry to E1M5. On both routes Chthon woke with three health, lost one per strike and died before the player entered the exit shaft. The player advanced the tally, finale and shareware end card using jump. The original QuakeC selected the hub. After walking there, both routes ended at hash `c9a2b52f`.

## Input, assets and sound

A bounded X11 input test on the board recorded three forward holds of 17, 18 and 21 ticks in the installed release. The first two used the K0 keypad scancode with the Num Lock modifier cleared and set. Changing focus during the third released the pointer and cleared held movement. Refocusing restored the pointer grab. Relative mouse input moved yaw by 3.77° and pitch by 12°, left click fired for 11 ticks and keypad 0 quit. Hands-on observations of the physical K0, mouse and mounted speaker are still pending.

The native Mojo loaders matched an independent decode of the local PAK for 61 alias models, 190 PCM sounds and 7,960 BSP visibility rows. Each map's inventory includes resolved precached model and sound filenames plus the QuakeC builtins observed during play. A separate board audio test played a generated stereo WAV as E1M1's optional track. The 431 Hz left and 739 Hz right components measured about 8,989 and 8,974, with less than 2 on the opposite channels. With the track absent the sampled tones measured zero. [Resource verifier](../verify_resources.py) · [Music verifier](../verify_music.py) · [Per-map inventory](episode1-inventory.json)

## Real-time board measurements

The default Adreno renderer presents a 640 × 480 image. CPU mode draws 320 × 240 and scales it to the same display. Both ran with their default vsync enabled, fixed 72 Hz simulation and 60 Hz display scheduling. The game submitted sound to an isolated PipeWire sink. The measurement window starts after the accelerated replay prefix. RSS is the process peak in MiB and CPU seconds cover the measurement window. [Reproduction script](../verify_timing.py)

| Scene | Renderer | Frames / seconds | Median ms | p95 ms | Worst ms | CPU seconds | Peak MiB | Audio underruns |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| E1M1 fight | CPU | 433 / 7.22 | 16.68 | 17.29 | 18.81 | 4.16 | 122.3 | 0 |
| E1M4 water surface | CPU | 312 / 5.20 | 16.67 | 17.29 | 24.76 | 2.54 | 122.2 | 0 |
| E1M1 → E1M2 | CPU | 185 / 4.59 | 16.66 | 17.92 | 912.56 | 2.14 | 126.4 | 2 |
| E1M1 fight | Adreno | 433 / 7.22 | 16.66 | 17.13 | 21.61 | 2.67 | 130.1 | 0 |
| E1M4 water surface | Adreno | 312 / 5.20 | 16.66 | 17.13 | 22.69 | 1.70 | 129.9 | 0 |
| E1M1 → E1M2 | Adreno | 201 / 3.74 | 16.68 | 17.85 | 256.81 | 1.46 | 134.5 | 2 |

Adreno averaged 60 frames per second in the fight and water samples. Its p95 stayed below 20 ms in all three samples. The level change still loads synchronously and causes a visible pause and two audio underruns. Both renderers retained every scheduled simulation tick through these samples.

## 72 Hz simulation comparison

The installed CPU build was compared with the pinned TyrQuake 0.71 C engine at the same 72 Hz step. The reference harness supplied one ordinary movement command per step and sampled server state before sending it. It used the same shareware PAK. Reference movement, collision, QuakeC execution and door logic came directly from the upstream source.

| Measurement | C reference | Installed UNO Q release |
|---|---|---|
| Forward speed after 1 and 6 ticks from rest | 44.444 and 229.026 units/s | 44.444 and 229.026 units/s |
| Jump from the start hall | Apex at tick 54, 43.704 units above takeoff. Landed on the lower step at tick 83, 191.939 units forward. | Same apex, landing tick and distance |
| E1M1 entrance door panels | Reached 96 and 94 units of travel. Returned to rest 252 and 250 ticks after first movement. | Same displacements and durations. Both panels started 12 command ticks earlier relative to map startup. |
| Six shotgun shots while holding fire | Input ticks 147, 183, 219, 255, 291, 327 | Input ticks 147, 183, 220, 256, 292, 328 |

From settled rest at tick 24 through the last movement sample at tick 346, each reported player position and velocity component matched to six decimal places. The door trajectories matched at all 300 aligned samples. The shotgun's largest difference was one tick (13.9 ms). The reference used a Mac host and its native C RNG. Campaign determinism is checked separately between the two UNO Q renderers.

## Save and recovery checks

The release restored a save containing a moving lift and four live projectiles in both renderer directions. Six resumed checkpoints matched uninterrupted play in each direction. The restore digest was `743d2165` and the final digest was `2a3bcc62`. The live game remained playable after both a truncated save and a mismatched map fingerprint. [Snapshot verifier](../verify_snapshot.py)
