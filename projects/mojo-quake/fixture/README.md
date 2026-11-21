# Movement room

The flat entrance leads up four steps to a raised deck. A low beam limits a jump on the deck. The ledge drops into a deep pool whose far wall has submerged stairs. The level geometry, palette-index textures and lights are original to this project. The compiled BSP29 contains its own textures, collision hulls, visibility and lighting.

The test uses **LibreQuake lite v0.09-beta** as a separate base game. Extract its release privately. Create `torque/maps` alongside its `id1` directory and copy `room.bsp` there. The commercial/shareware PAKs stay in their own installation. [LibreQuake release](https://github.com/lavenderdotpet/LibreQuake/releases/tag/v0.09-beta)

Run with the usual K0 and mouse controls, or replay the recorded walkthrough. Here `LIBREQUAKE` is the directory containing both `id1` and `torque`. Each replay checkpoint prints origin, velocity, grounded flags, water level and simulation hash.

```sh
build/host/tyr-quake -basedir "$LIBREQUAKE" -game torque \
  -window -width 640 -height 480 -mqcpu2x -noudp -noconinput +mlook +map room

SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy build/host/tyr-quake \
  -basedir "$LIBREQUAKE" -game torque -window -width 640 -height 480 -mqcpu2x \
  -mqfast -mqreplay fixture/movement.trace -noudp -noconinput +map room
```

To rebuild the BSP, run `python3 fixture/make_room.py /path/to/ericw-tools/bin fixture/room.bsp`. The generator creates the brush map and WAD2 materials in a temporary directory, then runs QBSP, VIS and LIGHT. The verified BSP uses ericw-tools v0.18.1 and has SHA-256 `dd17ce28bc1dab62c06b08f0f11a5419a223b4b4876e68000508cd0322acab64`. [Map compiler release](https://github.com/ericwa/ericw-tools/releases/tag/v0.18.1)
