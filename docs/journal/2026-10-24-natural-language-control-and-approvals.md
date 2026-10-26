# Plain-language control: API discovery, approvals and output lifetime

**Date:** 2026-10-24, America/Los_Angeles

**Status:** Installed acceptance complete. Ordinary-language hardware,
automatic/explicit permission policies, program execution, and retained-state
adoption across a daemon restart passed on the board. The actuator counter stayed
at 45 across the dedicated restart test, confirming no actuator replay. The
readiness-polling defect in the earlier rollout helper is fixed. The session
is a user-supplied console transcript, not an independently replayed event log.
No exact session ID or request timestamp was supplied.

## Product expectation

A user describes the outcome in ordinary language. Torque chooses the tools,
implementation language and files when needed, executes routine work within the
requested scope, and reports the result briefly. Users should not need to name a
Python file, explain the SDK, or repeatedly approve routine steps.

Authorization checks remain in the harness. Automatic execution means a defined
policy authorizes routine operations; it does not mean malformed calls,
consequential system changes or actions outside the requested scope are ignored.

## Four priorities and tracking

- [x] **1. Immediately usable capabilities.** Give the agent accurate board
  capabilities, direct hardware actions and concise SDK context. Ordinary
  fill/clear/RGB requests should not require package introspection or generating
  a program. Generate code when the task actually needs a program.
- [x] **2. Automatic, scoped execution by default.** Routine reads, project edits
  and execution within the requested task proceed without repeated y/n prompts.
  Define the allowed scope in the harness; ask for consequential boundaries such
  as firmware replacement, system-service changes or unrelated deletion. Bind
  permission choices to the request/turn/session rather than a global bypass.
- [x] **3. State follows the sentence.** Direct on/off commands retain that state
  until another command changes or releases it. Timed demos/animations finish
  when requested. Device ownership and status rendering must preserve explicit
  user output, including an explicitly blank matrix, after the tool/turn ends.
- [x] **4. Ordinary-language tests and concise outcomes.** Exercise realistic
  prompts without supplying source code or API hints. Assert tool choices,
  approval behavior, retained state, truthful final output and recovery behavior.
  Keep technical detail available for inspection rather than mandatory prose.

First milestone: implement usable hardware capabilities and automatic policy
together, including the state lifetime needed to pass the following gate.

## Acceptance gate

In a fresh session:

```text
light up all led matrix now
```

Expected: a bounded state/capability read if needed, one matrix action, all 104
pixels retained on after the tool and turn complete, no shell-based API
exploration, no unnecessary project generation and no routine approval prompt.
A short confirmation should describe the committed state accurately.

Follow with:

```text
turn it off
```

Expected: a blank framebuffer retained after the turn. A status cue must not
silently repaint over an explicitly requested off state. Timed requests such as
“blink for ten seconds” should instead obey the requested duration.

Test at least automatic and explicit-approval policies. Approval denial must
prevent an effect; session/turn permission choices must not leak to other work.
Retain argument validation, device ownership and firmware capability checks.
Never switch to unchecked execution just to make a test pass.

## Observed session and diagnosis

The user launched the CLI from `~/ArduinoApps`. `torque status` selected workspace
`/home/arduino/torque`, model `MiniMaxAI/MiniMax-M3.1-Flash`, device ready and
session `end_turn`. The earlier incomplete quoted command was cancelled in the
shell before the substantive request.

The real request was **“light up all led matrix now.”** It led to:

1. Six approved shell requests exploring the workspace and installed packages.
2. One approved file write creating `projects/matrix-all-on/main.py`.
3. One approved shell request running it with a ten-second hold.
4. A long response describing a completed finite demo and restored status cue.

There were **eight approval prompts**. The task did reach the MCU: the reported
framebuffer contained eight rows of thirteen on pixels and packed hex
`ffffffffffffffffffffffffff`. That is software readback, not optical evidence.

The system chose a ten-second duration which the user had not requested, then
cleared/released the output. Current instructions bias generated demos toward
finite cleanup. The board-action tool catalog only exposed a snapshot reader,
so execution went through generic shell/file tools and SDK exploration.

The final response also called the circle an idle cue and said the matrix was
off while reporting the circle framebuffer. In the checked-in assets, the
circle is the **working** cue and standby is a single pixel. A readback during
an active turn can show working feedback; it is not proof of the state after
that turn ends. Future results need explicit display ownership/state metadata.

Current E2E tests provide exact source and an exact run command to the model.
They validate transport and execution but do not cover this uncoached interaction.
A realistic prompt test is required alongside those integration checks.

## Console reference

The following preserves the supplied interaction for review. It contains no
credential, environment dump or unrelated personal keypad mapping.

````text
arduino@tommy-uno-q:~/ArduinoApps$ torque ask "^C
arduino@tommy-uno-q:~/ArduinoApps$ torque status
Torque · MiniMaxAI/MiniMax-M3.1-Flash
Workspace: /home/arduino/torque
Device: ready
Session: end_turn
Tools require approval; model requests start only when prompted.
arduino@tommy-uno-q:~/ArduinoApps$ torque ask "light up all led matrix now"
I'll start by checking the board state and reading the API reference.
Approve shell: {"command": "ls -la /home/arduino/torque && ls /home/arduino/torque/projects 2>/dev/null && /opt/torque/current/runtime/python/bin/python -c \"import torque, inspect; print(torque.__file__); print([n for n in dir(torque) if not n.startswith('_')])\""}
Run this exact action once? [y/N] y

Approve shell: {"command": "ls /opt/torque/current/runtime/python/lib/python3.13/site-packages/torque/ && grep -n \"def \" /opt/torque/current/runtime/python/lib/python3.13/site-packages/torque/sdk.py | head -60"}
Run this exact action once? [y/N] y

Approve shell: {"command": "grep -n \"def \\|class \" /opt/torque/current/runtime/python/lib/python3.13/site-packages/torque/device.py | head -60"}
Run this exact action once? [y/N] y

Approve shell: {"command": "grep -rn \"class Matrix\\|class Board\\|def draw\\|def clear\\|def from_rows\\|def load\\|def play\" /opt/torque/current/runtime/python/lib/python3.13/site-packages/torque/*.py | head -30"}
Run this exact action once? [y/N] y

Approve shell: {"command": "sed -n 1,60p /opt/torque/current/runtime/python/lib/python3.13/site-packages/torque/sdk.py; echo ---; grep -rn \"matrix\" /opt/torque/current/runtime/python/lib/python3.13/site-packages/torque/protocol.py | head -20"}
Run this exact action once? [y/N] y

Approve shell: {"command": "python3 - <<'EOF'\nimport glob\nprint(glob.glob('/opt/torque/current/runtime/python/lib/python3.13/site-packages/unoq_control*'))\nEOF\nfind /opt/torque/current/runtime/python/lib/python3.13/site-packages -maxdepth 2 -name \"*.py\" | grep unoq"}
Run this exact action once? [y/N] y
Board is ready (8x13 matrix, idle status cue showing a circle). Now I'll create the program.
Approve write_file: {"path": "/home/arduino/torque/projects/matrix-all-on/main.py", "content": "\"\"\"Light every pixel of the 8x13 LED matrix, hold briefly, then blank it.\n\nFinite by default: the matrix is cleared in `finally`, and when the Board\nconnection closes, Torque restores its own status cue on the display.\n\nUsage:\n    python main.py [hold_seconds]\n\"\"\"\n\nimport sys\nimport time\n\nfrom torque import Board, Frame\n\nROWS = 8\nCOLUMNS = 13\nDEFAULT_HOLD_SECONDS = 10.0\n\n\ndef all_on_frame():\n    \"\"\"A frame with every one of the 104 pixels lit.\"\"\"\n    return Frame.from_rows(['#' * COLUMNS] * ROWS)\n\n\ndef main():\n    hold = DEFAULT_HOLD_SECONDS\n    if len(sys.argv) > 1:\n        hold = float(sys.argv[1])\n        if hold < 0:\n            raise SystemExit('hold_seconds must not be negative')\n\n    frame = all_on_frame()\n    lit = sum(frame.pixels)\n    print(f'frame pixels lit: {lit}/{ROWS * COLUMNS}')\n\n    with Board() as board:\n        try:\n            board.matrix.draw(frame)\n            state = board.snapshot()['matrix']\n            print('framebuffer rows after draw:')\n            for row in state['rows']:\n                print(f'  {row}')\n            print(f\"playing={state['playing']} frame_hex={state['frame_hex']}\")\n            print(f'holding all pixels on for {hold:g}s')\n            time.sleep(hold)\n        finally:\n            board.matrix.clear()\n            print('matrix cleared')\n\n\nif __name__ == '__main__':\n    main()\n"}
Run this exact action once? [y/N] y

Approve shell: {"command": "cd /home/arduino/torque && /opt/torque/current/runtime/python/bin/python projects/matrix-all-on/main.py 10"}
Run this exact action once? [y/N] y
Done — the full 8x13 matrix was lit and then released.

**What I did**

1. Checked board state first (`device_snapshot`): MCU responsive, matrix idle showing Torque's status circle, RGB LEDs 3 and 4 off.
2. Created `projects/matrix-all-on/main.py` — uses the resident controller via `from torque import Board, Frame`, draws a single frame with all 104 pixels on, holds, and clears in `finally`.
3. Ran it with the managed interpreter (`/opt/torque/current/runtime/python/bin/python`), 10-second hold.

**Software evidence (framebuffer readback, not a camera)**

```
frame pixels lit: 104/104
framebuffer rows after draw:
  #############   (x8 rows)
playing=False frame_hex=ffffffffffffffffffffffffff
matrix cleared
```

All 104 pixels were set in the firmware framebuffer for the hold period. After the program closed, the snapshot shows the framebuffer back to `00003802201100880380000000` — the Torque status circle, which is the expected idle display once a program releases the matrix (a blank buffer is not the normal end state here).

**What I did not do / note**

- No optical verification: I read the firmware framebuffer and GPIO state, so I can't confirm what a person actually sees on the panel. Please glance at the board to confirm the lit state looks right.
- The matrix is off now. The demo is finite by default; re-run it any time with:
  ```
  /opt/torque/current/runtime/python/bin/python projects/matrix-all-on/main.py 30
  ```
  (the argument is the hold time in seconds). If you'd rather it stay lit continuously, tell me and I'll change it to a retained/looping version instead.
- MCU RGB LEDs 3 and 4 were left untouched (all channels off), and no firmware, services, or boot defaults were changed.
arduino@tommy-uno-q:~/ArduinoApps$
````

## Relevant implementation locations

- [Worker tool catalog and loaded context](../../engines/fx/worker.mjs).
- [Tool authorization and execution](../../packages/session/src/torque/daemon.py).
- [CLI approvals and output](../../packages/session/src/torque/cli.py).
- [Device ownership and status rendering](../../packages/session/src/torque/device.py).
- [Finite-demo instructions](../../agent/AGENTS.md) and
  [board workflow reference](../../agent/skills/uno-q-apps/references/app-workflow.md).
- [Existing coached E2E verifier](../../install/verify.py).

## Implementation log

- Journal created before code changes, with the four agreed priorities,
  baseline transcript and ordinary-language acceptance gate.
- Implementation and verification results will be recorded here as work proceeds.

### Source milestone

Implemented direct `device_capabilities`, `matrix_fill`, `matrix_draw`,
`matrix_clear`, `matrix_release` and `rgb_set` tools, plus bounded directory/search
and `run_program` tools. Auto policy permits routine tool categories; advanced
shell execution asks. Ask/full are explicit turn/session choices, with default
modes and validation retained. Auto program execution is not an OS sandbox;
programs retain the normal account's OS access. Maintenance and unrelated changes
must not be smuggled into routine programs.

Matrix tools retain the explicit framebuffer through turn completion and session
feedback changes. A saved scene is adopted after a daemon restart only when MCU
boot ID and actual frame match; no write is replayed onto a new boot. A program
acquiring the device replaces the retained scene; explicit `matrix_release`
restores status feedback. Turning the matrix off retains a blank user scene.

The real MiniMax model passed the literal on/off prompts against a simulated
hardware backend through the real daemon, policy and Unix IPC: one `matrix_fill`
per turn, zero approvals, no shell/files/program generation, short replies and
retained on/off state. This was a model/host integration check, not physical MCU
evidence. The first simulation attempt used an incorrect fixture injection and
failed; correcting the fixture selected the intended simulated device.

The Python suite passed 123 tests on the Mac at this milestone. Dedicated tests
cover auto/ask behavior, denied effects, scoped program paths, mode isolation,
retained off state, writer conflict, explicit status release, matching-boot
restart adoption and invalidation without actuator replay. The uncoached runner
is `install/verify-natural.py --exercise-outputs`; the older coached verifier now
uses explicit ask policy and the structured program runner.

### Real-MCU acceptance through the existing private IPC

The new coordinator/policy/worker also passed the uncoached prompts against the
actual MCU through a private IPC proxy to the existing installed daemon. The
existing service kept its native router subscription; the temporary coordinator
held an ordinary cooperating program connection. This avoided changing the
installed service or its permissions for a test.

- “light up all led matrix now” used one `matrix_fill({on: true})` call, zero
  approvals and no shell, file or program tools. All 104 framebuffer pixels
  remained on after the turn.
- “turn it off” used one `matrix_clear({})` call, zero approvals and no other
  implementation tools. The blank framebuffer remained after the turn.
- Replies were short and described the returned retained user display state.
- The result is hardware/API evidence, not an optical measurement and not yet
  verification of the new installed system service.

The temporary simulated and live-proxy daemons were stopped after these checks.
Their private receipts are `.cache/natural-control/model-simulated.json` and
`.cache/natural-control/live-proxy.json` locally, with board copies under
`~/.cache/torque/natural-sim/` and `natural-live/`. Source tests pass 123 cases.
Installed-policy acceptance and same-boot daemon-restart adoption are the
remaining rollout gates. No firmware source change is required.

### Installed acceptance and restart-probe correction

The user ran the reviewed update helper. Release `0.1.0-9271b389ad23` was
installed without changing the MCU boot or reflashing firmware. The installed
natural-language runner passed:

- The exact all-on sentence used `device_snapshot`, `device_capabilities` and
  `matrix_fill({on: true})`, with zero approvals, no shell/project generation,
  and the all-on framebuffer retained after turn completion.
- The follow-up “turn it off” used one `matrix_clear` call and retained a blank
  framebuffer, again without approval prompts.
- Ask-policy denial prevented an actual matrix effect. A subsequent automatic
  turn returned to default auto policy.
- “Make a small program that prints hello and run it” selected its own language
  and filename, wrote and executed the program, printed Hello, world!, and
  required zero approvals.

The helper then restarted `torque.service` but aborted on its first status
query: the CLI briefly returned exit 1 while the control socket/device was
starting, and the helper used `check=True` before its retry loop could run.
This is a verifier timing defect, not evidence that the retained state was lost.

A later independent SSH check confirmed the service active as `arduino`, default
permissions auto, no active turn or approvals, no output owner, MCU boot ID
973450602 unchanged, and a zero framebuffer in retained user mode. The blank
state therefore survived the original daemon restart. The original helper did
not reach its command-counter comparison; a hardware no-replay counter result
must not be claimed from that failed invocation.

`install/system.py` now has bounded readiness polling that tolerates a missing
socket, nonzero CLI exit, malformed/transient output and command timeouts, and
retains the last device diagnostic on failure. The board-local rollout helper
uses this polling. `install/verify-restart.py --exercise-restart` is a dedicated
administrator check for a new daemon epoch, unchanged MCU boot/frame, retained
user mode and unchanged actuator command counter. It performs no model calls,
reinstallation or firmware upload. Tests cover the transient sequence and reject
same-pixel actuator replay rather than inferring it from final pixels alone.

The source suite now passes 129 tests. Core installed behavior is operational;
the dedicated strict counter comparison is available separately because systemd
service restart still requires administrator authentication in this SSH context.

### Dedicated restart acceptance completed

The user ran the restart-only verifier with administrator authentication. Its
board-local receipt `~/.cache/torque/natural-rollout.json` reports `passed: true`
for release `0.1.0-9271b389ad23`:

- New daemon execution, retained blank framebuffer and retained user display mode.
- MCU boot unchanged; no firmware upload or Linux reboot in this check.
- Actuator command counter **45 before and 45 after**, demonstrating state
  adoption without replaying an actuator write.
- Default permission policy remains auto.

An independent fresh SSH check confirmed the receipt, service enabled/active,
device ready, no active turn, the same zero framebuffer and command counter 45.
The earlier strict-counter rollout gate is therefore complete. These remain
firmware/API observations rather than an optical measurement.

The user subsequently deleted the legacy `/home/arduino/projects` directory.
The agent did not perform that deletion. Prior inspection found no active
process, configuration or container-mount dependency on that directory. Afterward
checks confirmed `/home/arduino/torque/projects` still exists, the running
controller remains at `/var/lib/torque/device/uno-q/controller`, and the current
Torque service is healthy. The current user workspace is `~/torque`, not the
removed legacy path.
