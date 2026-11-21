# Faster Quake control on the Mac

**November 19, 2026 · Apple M3 Max, 36 GiB.** In six starts without a previous target, one Modular Gemma 4 31B call returning both vision and action cut median time to the first non-neutral input from **1.17 s to 0.84 s**. It passed all six short tests. A Mac feature tracker sometimes steered much sooner once it had a target, especially on a static landing. The serial baseline used cloud vision and local Gemma 4 E4B. The Observatory now defaults to the single-call controller; `--controller split` selects the earlier pipeline.

A [14-second side-by-side recording](../build/experiments/mac-fast-control-comparison.mp4) shows two additional real-time takes, one on the ledge and one in combat. Each pair shares its starting view and game clock.

## Results

The table compares each experimental controller with its own interleaved production baseline. Each condition used the same native save-free starting state and identical first JPEG for both controllers.

| Test | Experimental controller | Its serial baseline |
|---|---:|---:|
| One call, first actual input across six unprimed starts | 0.84 s median | 1.17 s median |
| One call, time from observed frame to applied action across applied decisions | 0.61 s median | 1.17 s median |
| One call, landed and survived | 3/3 | 3/3 |
| One call, defeated the first enemy and survived | 3/3 | 2/3 |
| Feature tracking, already identified ledge after camera turn | 3/4 compensating inputs, 5.2–5.9 ms; 4/4 landings | 0/4 qualifying corrections; 4/4 landings |
| Feature tracking, already identified enemy after camera turn | 2/4 compensating inputs, 0.97 s and 2.52 s; 3/4 wins | 0/4 qualifying corrections; 2/4 wins |
| Feature tracking, unprimed ledge / enemy | 3/3 landings, 1/3 wins | 3/3 landings, 1/3 wins |

The fast ledge corrections began as soon as the shifted frame reached the controller. The camera is sampled every 55.6 ms. This timing excludes the wait for an arbitrary game event to enter a sampled frame. The ledge was wide enough that the serial controller could still land without steering back. A six-second trial without a qualifying input counts as a miss, not a six-second reaction.

The simpler patch tracker frequently lost its target and withheld the intended input. It finished 0/6 unprimed tasks, against 3/6 for its paired baseline. A separate, unpaired feature-tracker run also failed all six unprimed tasks. In the subsequent interleaved comparison, the feature controller used its bounded semantic fallback 14 times across those six unprimed trials. The results reflect substantial run-to-run variation; the handful of enemy wins do not establish reliable visual enemy tracking. In the one-call block, neutral controls occupied 65.8% of ticks, down from 74.1% for its baseline.

## What ran

- **Serial.** The existing Observatory decision cycle handles every new observation. Modular Cloud describes the frame, the Mac chooses an input, and the game releases the controls between macros.
- **Patch tracker.** The same two models refresh plans asynchronously while a local controller matches the last model-marked image patch on each new Quake frame. It releases a lost lock and bounds the lifetime of targeted commands.
- **Feature tracker.** ORB correspondences and a RANSAC camera transform predict where a marked point moved. Nearby matching image patches refine that estimate. Static surfaces can use geometric support; an enemy needs a local appearance match. Fresh cloud vision can refresh an existing skill while local Gemma chooses the next intent. On loss of a newly acquired lock, an otherwise fresh semantic instruction may execute once under the normal expiry rules. The controller never restarts a committed jump from an overlapping plan.
- **One call.** Modular Gemma 4 31B returns the scene, points, action and cue together with thinking disabled. The host validates the proposed input against the existing legal options. It uses the production scheduler and ordinary input macros. Local Gemma is absent in this experimental arm.

## How to read the measurements

Each scored trial ran at 72 ticks/s for six seconds or until death, with a local control opportunity every four ticks. E1M1 gameplay, QuakeC and physics used the project's native CPU build. The two scenes came from real input replays. A ledge success required at least 12 grounded ticks on the upper platform and survival to the end. Combat success required an enemy kill and survival. Engine position, flags, health and kills were used only by the evaluator. The tracker and both models worked from game pixels, recent inputs and route memory.

Unprimed tests used initial yaw offsets of 0°, −8° and +8° and required fresh perception from the first frame. The warm test started both arms with the same previously recorded model-selected jump or aim instruction, ran its first eight game ticks, and introduced a −10°, +10°, −14° or +14° camera turn during the second four-tick chunk. The controller received the resulting pixels. The evaluator timed the first subsequent task-directed input that compensated at least 2° of the imposed horizontal turn and reduced the residual angle. This measures a steering command; kill and landing counts measure gameplay outcomes separately. Trials alternated order within each paired series. Models were shared endpoints under normal machine and network load, so API timings vary.

An independent four-turn camera probe reacquired the ledge in 4/4 views for both trackers, within 0.5 pixels of the static projection. Both rejected the enemy patch in 4/4 views. The projection assumes stationary geometry and is an approximation for a moving character. The probe resets the game between turns and includes decoding the new game JPEG and updating the local track in its compute time.

## Reproduce

From the Mojo Quake project directory, build the host game and supply its private shareware media. The experiments use the configured Modular API key and a running local Ollama with `gemma4:e4b-mlx`. An existing Pooki env file can be supplied with `--key-file`. Output paths must be new. Each measured process uses a temporary game profile.

```sh
uv run --script experiments/fast_control.py --output /tmp/quake-patch-trials.jsonl
uv run --script experiments/fast_control.py --paired-features --output /tmp/quake-feature-trials.jsonl
uv run --script experiments/fast_control.py --one-call --output /tmp/quake-one-call-trials.jsonl
uv run --script experiments/probe_camera.py
```

The results include **68 matched trial executions** (34 pairs) plus the 14 exploratory, unpaired feature-tracker executions. Setup/smoke calls, an interrupted instrumentation run and the separate illustrative video takes are excluded. The original patch pilot omitted the action label during the serial jump subphases, so its serial ledge correction metric is unavailable. The paired feature confirmation and its fresh serial baseline used the corrected instrumentation. [Summary](../evidence/mac-fast-control-summary.json) · [All scored trials](../evidence/mac-fast-control-trials.jsonl.gz) · [Camera probes](../evidence/mac-fast-control-camera.json)

**Decision.** The single-call controller is the first candidate for a larger live A/B. For a confirmed ledge, local tracking can correct a camera change quickly, but these trials show no additional landings. Enemy tracking still needs better identity checks before it can carry combat by itself.
