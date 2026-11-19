# Finishing the single-player DOOM campaign on the UNO Q

**Implementation spec · November 18, 2026**

**The approved release is Episode 1, Knee-Deep in the Dead**, including Military Base and the Phobos Anomaly finale. The four phases below define this release. [Implementation and per-map verification](../../projects/mojo-doom-switchyard/evidence/episode1-verification.md)

The first playable milestone is a fight in Hangar. Start from the original player position, walk into the first occupied room, alert a zombieman, take a hit, shoot back, and pick up the dropped clip. A player who stands still in the starting room should experience the encounter that the original map and selected difficulty prescribe. The final milestone is a desktop game a player can start, save, resume and finish using the K0 Max and mouse.

## What counts as finished

| Release | Playable content | Acceptance |
|---|---|---|
| Shareware DOOM 1.9 | Knee-Deep in the Dead, 9 maps | Finish E1M1–E1M8 from New Game. Also take the secret exit from E1M3, finish E1M9, rejoin at E1M4 and reach the Episode 1 finale. The board already has the required IWAD. |

The release uses the original episode’s maps, monsters, weapons, sounds, music, intermissions and ending. Local game data stays outside Git. [Original engine and game-data distinction](https://github.com/id-Software/DOOM)

## Starting point

Before this implementation, the UNO Q shortcut opened the real shareware Hangar. That baseline supported walking, basic doors, pistol animation and sound, an exit marker and a Hangar save. The baseline importer selected medium-difficulty sprite pictures and dropped their actor identities from the sprite table. The runtime had fixed Hangar-sized storage, including 85 sectors and a 96-word saved state. Opening more map files alone would leave players exploring rooms full of stationary artwork. On this board’s E1M1, the medium single-player records specify four zombiemen and two imps. These six placements give us the first regression test. [Importer](../../projects/mojo-doom-switchyard/import_iwad.py) · [Mojo simulation](../../projects/mojo-doom-switchyard/src/classic.mojo) · [Native resource allocation](../../projects/mojo-doom-switchyard/src/classic_platform.inc)

Mojo owns one deterministic 35-tick simulation, player commands, campaign state, audio sequencing and mixing. CPU mode draws pixels in Mojo. GPU mode presents the same world through OpenGL and GLSL on the Adreno. C connects the executable to SDL2, storage and graphics. Python may build the asset index and run tests offline. Both installed renderers must play the campaign without a Python process. [Renderer and platform design](2026-11-18-mojo-doom-dual-renderers.md)

## Implementation phases

### 1. Make Hangar’s first encounter playable

Preserve each map thing’s type, position, facing and skill flags. Give live actors stable IDs, health, collision bounds, targets, timers and animation states. Implement sight and sound alerts, chase, zombieman attacks, imp melee and fireballs, pistol hits, pain, death, applicable drops, player damage and death/restart. Both renderers draw the same live actors, facing and animation frames. Wall openings, closed doors and solid walls must affect visibility, movement and attacks.

**Playtest.** Start E1M1 on Hurt Me Plenty on the UNO Q. Approach the original encounter, see an enemy turn and approach, hear its attack, take damage, kill it and collect its drop. Take cover behind a solid wall and verify a shot is blocked. Save mid-fight, resume on the other renderer and replay the same inputs to the same outcome. Run a separate spawn check for all six monsters, even those outside the starting view. [Original actor behavior](https://github.com/id-Software/DOOM/blob/master/linuxdoom-1.10/p_enemy.c)

### 2. Load levels and carry a game between them

Replace the E1M1-specific index with a versioned map directory keyed by edition, IWAD digest and map name. Size level and renderer buffers from validated per-map records. Inventory each map’s things, textures, sound and music references, line and sector specials, and exits. Record unsupported entries with their map and record number so they become specific implementation tasks.

Introduce New Game, difficulty selection, level completion, intermission and next-level loading. Carry health, armor, weapons and ammo across normal exits. Clear level-local keys and temporary powers according to the original rules. Save the edition, map, skill, player, live actors and projectiles, RNG, triggers and moving sectors. Use an atomic save replacement. Give legacy Hangar slots an explicit import or restart choice and preserve the original file. A mismatched IWAD or unreadable slot must leave the current game playable.

**Playtest.** Exit E1M1 into E1M2 and regain control with the correct inventory. Save, quit to the desktop, reopen and resume on the other renderer. Load each of the nine maps separately in verification to catch resource limits before testing their routes. [Original level progression](https://github.com/id-Software/DOOM/blob/master/linuxdoom-1.10/g_game.c)

### 3. Finish Episode 1’s combat and map mechanics

Use the map inventory to implement the episode’s remaining enemies, weapons and pickups, including shotgun guys, demons, spectres, and Barons of Hell. Cover weapon switching, usable ammo, health and armor limits, keys, powerups, exploding barrels, projectile impact and splash damage. Implement the actual tagged doors, switches, lifts, stairs, moving floors, teleports, hazards, secrets and lighting encountered along the routes. Honor skill flags and the selected skill’s combat rules, including Nightmare behavior.

**Playtest.** Complete E1M1 through E1M7 from normal starts with collision and progression rules enabled. Exercise a locked door before and after finding its key. Take the E1M3 secret exit to Military Base and return to E1M4. In Phobos Anomaly, killing the first Baron must leave the arena barrier up. Killing the second must lower it. Enter the final damaging sector and reach the episode ending. Map warps and seeded saves are useful for diagnosis. Campaign acceptance uses a continuous run. [Original boss triggers](https://github.com/id-Software/DOOM/blob/master/linuxdoom-1.10/p_enemy.c) · [Sector effects](https://github.com/id-Software/DOOM/blob/master/linuxdoom-1.10/p_spec.c)

### 4. Ship Episode 1 as a desktop game

Finish the title and episode menus, HUD, automap, pause, death/restart, save/load menus, intermission statistics and finale. Play original positional effects and the correct map, intermission and finale music. Decode and sequence the WAD’s MUS tracks in Mojo, mix them with effects, and provide an offline instrument bank with distribution rights. Exercise simultaneous weapon, enemy and door sounds. Complete sprite masking and angles, animated textures and flats, sky, lighting and moving-sector rendering used by the episode.

Keep the existing K0 movement, fire, use, save/restore and **KP0 to quit**. Proposed free keys are **KP3 to cycle weapons** and **keypad decimal for automap**. Menus must be navigable with KP8, KP2 and keypad Enter. Verify the actual key events with Num Lock on and off. Show the bindings in the controls legend.

**Release playtest.** From the desktop shortcut, finish the episode on the UNO Q with the physical K0 and mouse, including a save, quit and relaunch. Check the secret-route return, intermission counts, readable HUD on the 640 × 480 display, audible music and effects through the board speaker, and return to desktop. Run the campaign replay on CPU and Adreno. This is the first release described as a complete playable episode.

## Evidence required for a campaign release

- **Map coverage.** Keep one row per map recording normal exit, secret destination and return where applicable, required triggers, supported actors and assets, CPU/GPU replay results and date of the last board playtest. An unimplemented progression trigger keeps that map open.
- **Gameplay and saves.** Use small redistributable fixtures for individual rules. Record a medium-skill campaign command trace for the episode and a branch trace for its secret route. Replay both graphics modes against the same seed. Compare state hashes at map entry, combat checkpoints, save/load, exit and finale. Include easy and hard spawn counts, skill-specific behavior and a corrupt-save recovery test.
- **Board performance.** On each renderer, measure a crowded fight with music, a moving-sector scene and a map transition. Require sustained 35 simulation ticks/s on a timed route with no lost commands. Record median and p95 presented-frame time, peak memory and audio underruns. Use 320 × 200 with 4:3 presentation for CPU and the native 640 × 480 viewport for Adreno. Treat 60 rendered frames/s as a target to measure.
- **Player acceptance.** A person can start from the shortcut and finish through normal controls with sound. Record the edition, IWAD digest, build, renderer, difficulty and route. Keep automated simulation results, firmware-independent graphics measurements and the player’s observations distinguishable.
