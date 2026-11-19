# Episode 1 verification on the UNO Q

Two recordings begin at the original single-player start on Hurt Me Plenty. The ordinary route plays eight maps. The secret route visits Military Base from Toxin Refinery, returns to Command Control, and finishes at the same Phobos Anomaly ending. The verification driver feeds movement, turn and button commands to the normal Mojo simulation. It rejects an unexpected map order, a missed exit or a player death during either recording. Both recordings can be played at normal speed.

The installed Linux ARM64 binary has SHA-256 `7151a5f7add3fcff6c87049553e098007c871e80ecc8e931c39157776220f2ed`. The DOOM Hangar desktop entry opens CPU mode and its Adreno action opens GPU mode. Both launch the verified binary and share the per-user `campaign.sav` slot.

## Map exits

Each value is the simulation-state hash at the exit. The board produced the same hash in headless mode and with both renderers. Accelerated renderer checks ran every gameplay tick and presented a sample at map changes, level completion and every 140 ticks. [Raw board output](episode1-release.log)

| Map | Indexed sprites across skills | Blur spheres | Exit trigger | Ordinary route | Secret route |
|---|---:|---:|---|---|---|
| E1M1 · Hangar | 115 | 0 | line 330 (normal) | `ebff8812` | `ebff8812` |
| E1M2 · Nuclear Plant | 241 | 0 | line 873 (normal) | `b35a7973` | `b35a7973` |
| E1M3 · Toxin Refinery | 367 | 1 | line 785 (secret), line 982 (normal) | `46f33a5c` | `ca86e8d9` |
| E1M4 · Command Control | 240 | 0 | line 554 (normal) | `1d66f126` | `21476057` |
| E1M5 · Phobos Lab | 258 | 1 | line 409 (normal) | `743e4435` | `1ccb98a4` |
| E1M6 · Central Processing | 448 | 2 | line 627 (normal) | `d8c1e7c5` | `233414d0` |
| E1M7 · Computer Station | 336 | 1 | line 810 (normal) | `4150fc02` | `2c701066` |
| E1M8 · Phobos Anomaly | 112 | 1 | last Baron lowers tag 666, sector 66 ends the episode | `6457c2a7` | `3f9bc465` |
| E1M9 · Military Base | 221 | 0 | line 551 (normal) | Secret map | `2f075d82` |

The ordinary recording contains **80,431 ticks** and the secret recording **114,692 ticks**. In a separate two-Baron test, the arena floor stayed in place after the first kill and descended after the second. Entering the last damaging sector at low health triggered the finale between damage pulses. Combat checkpoints also exercised pickups, incoming damage and CPU-to-Adreno and Adreno-to-CPU save restoration.

Every single-player actor, pickup and decoration in the shareware map records is accounted for in the index. Player starts and teleport destinations are read directly from the IWAD. The importer identifies unsupported records by map and record number. Pass `--inventory inventory.json` to the importer to see the per-map thing counts, materials, sounds, music, linedef specials, sector specials and exit indices.

The November 18, 2026 board run used the following map data. Linedef numbers in this table identify types of triggers and effects present in each map. The exit table above uses individual record numbers.

| Map | Monsters on Hurt Me Plenty | Linedef special types | Music lump |
|---|---|---|---|
| E1M1 | 4 zombiemen, 2 imps | 1, 11, 36, 48, 88 | `D_E1M1` |
| E1M2 | 33 zombiemen, 8 imps | 1, 9, 11, 28, 31, 46, 62, 88, 103 | `D_E1M2` |
| E1M3 | 24 zombiemen, 19 shotgun guys, 29 imps, 2 demons | 1, 2, 8, 11, 20, 26, 27, 31, 35, 51, 62, 63, 88, 90, 103 | `D_E1M3` |
| E1M4 | 22 zombiemen, 9 shotgun guys, 20 imps, 3 demons | 1, 2, 5, 11, 18, 26, 27, 31, 36, 62, 86, 88, 90 | `D_E1M4` |
| E1M5 | 28 zombiemen, 24 shotgun guys, 26 imps, 4 demons, 9 spectres | 1, 2, 11, 22, 26, 27, 31, 62, 70, 88, 90, 91, 97, 98, 103 | `D_E1M5` |
| E1M6 | 22 zombiemen, 35 shotgun guys, 43 imps, 9 demons, 9 spectres | 1, 2, 11, 16, 26, 27, 28, 36, 62, 76, 88, 103 | `D_E1M6` |
| E1M7 | 31 zombiemen, 19 shotgun guys, 30 imps, 3 demons, 1 spectres | 1, 2, 11, 22, 23, 26, 27, 28, 31, 34, 48, 62, 63, 70, 88, 90, 91, 98, 103 | `D_E1M7` |
| E1M8 | 6 shotgun guys, 5 imps, 14 demons, 2 Barons | 1, 2, 7, 23, 31, 62, 82, 91, 97 | `D_E1M8` |
| E1M9 | 5 zombiemen, 21 shotgun guys, 30 imps, 11 demons, 5 spectres | 1, 2, 11, 20, 31, 32, 33, 34, 36, 62, 88, 90, 97, 103 | `D_E1M9` |

A direct Hangar test fires at the same zombieman from 64 units away across solid linedef 406 and then in the open. A Nuclear Plant test uses the red door before and after collecting the red key. Both blur spheres on Central Processing grant the timed partial-invisibility power and stay collected across save/load. A framebuffer comparison at the original E1M6 sphere position also confirmed that its artwork is visible. Saves from versions 2 and 3 restore their actor IDs, moving sectors and triggered lines into the current map layout. Difficulty checkpoints verify doubled ammo on easy and Nightmare, and a Nightmare-only monster respawn.

## Reproduction

Run these from the project directory with a local shareware 1.9 IWAD, its nine generated indexes and a built native executable. The renderer and performance checks require a desktop session. The verifier uses temporary save slots.

```bash
python3 verify_campaign.py ./build/switchyard-unoq "$media/doom1.wad" \
    --index "$media/doom1.syi" --episode --renderers
```

Each input row contains a run length followed by forward, strafe, turn and action bits. A map-entry assertion marks the start of each level. It advances zero ticks. To watch a recording through the ordinary real-time loop, decompress it into standard input.

```bash
gzip -dc evidence/episode1-secret.trace.gz | ./build/switchyard-unoq \
    --iwad "$media/doom1.wad" --index "$media/doom1.syi" --renderer=gpu --replay -
```

The compressed recordings contain player inputs and map-entry assertions. Both start a fresh game and reach the finale without loading a save. Asset preparation on the UNO Q reproduced all nine map indexes byte for byte. The installed game reads the original art, sound and music from the local IWAD.

## Real-time measurements

Each scene ran 245 gameplay ticks using the normal 35 Hz clock. CPU rendered its 320 × 200 world buffer and Adreno rendered the 640 × 480 viewport. SDL queued stereo float32 music and effects to an isolated PipeWire output on the board. Frame-interval buckets exclude the first second. Peak resident memory covers the entire process. The queue counter records when SDL reports an empty application queue after previously queued audio. [Raw timing and audio results](episode1-performance.log)

| Scene | Renderer | Median frame interval (ms) | p95 (ms) | Peak memory (MiB) | Empty audio queue events |
|---|---|---:|---:|---:|---:|
| Military Base firefight | CPU | 17 | 17 | 105.8 | 0 |
| Military Base firefight | GPU | 17 | 18 | 106.7 | 0 |
| Phobos Lab platforms | CPU | 17 | 17 | 110.7 | 0 |
| Phobos Lab platforms | GPU | 17 | 18 | 111.5 | 0 |
| Central Processing exit into Computer Station | CPU | 17 | 18 | 111.5 | 0 |
| Central Processing exit into Computer Station | GPU | 17 | 17 | 112.8 | 0 |

Run `verify_campaign.py` with `--performance` to repeat the measurements. The level loader feeds the mixer during decode and GPU texture upload so music can continue across level changes.

## Player observations

Targeted desktop events exercised New Game, difficulty selection, weapon cycling, map, pause, save/load and quit. A PipeWire playback monitor observed nonzero game audio on an isolated output. Targeted keypad events in both Num Lock modifier states also selected difficulty, moved, turned, fired, saved and quit. Physical operation of the K0 Max and mouse, listening on the mounted speaker and a personal playthrough remain unobserved.
