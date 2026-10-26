# Validation record

## Controller telemetry on 2026-10-24

Version 0.2.0 is deployed and reports protocol 1.1 and ready state. The existing
command API remains available. The expanded design spec was written before the
telemetry implementation.

- The 72-test software suite passes across macOS and the UNO Q. Each environment
  skips two different dependency-dependent tests: the real C++ engine/codec tests
  run on the Mac; both real native Bridge wire tests run on the board. Together
  the environments cover every test.
- Maximum-value snapshots/events fit the pinned 256-byte MessagePack budget.
  Codec tests include active-low conversion and unavailable GPIO readback.
- Live RGB requested states matched independently read GPIO levels. Known matrix
  frames matched framebuffer snapshots and async events. Another client could
  query/control outputs while an observer was active.
- Live checks passed for observer exclusion, idempotent subscribe, stale-token
  rejection, sampled playback, command-error events, and observer cleanup without
  output changes. An abandoned observer expired in 10.12 seconds. Both normal
  close and expiry preserved a nonblank frame and an enabled RGB channel.
- During 83 repeated RGB-off commands over 1.33 seconds, six matrix progress
  events were emitted. RGB traffic did not bypass the 200 ms matrix sampler.
  The JSONL watch CLI received real MCU state events.
- A live observer survived an approved MCU firmware replacement using an
  expanded retry budget. It reported disconnect/reconnect, detected the changed
  boot, rejected an old-boot actuator command, refreshed state, and received a
  new GPIO event. Recovery did not replay output commands.
- Ten native `info` RPCs measured 15.98 ms median without observation and
  16.59 ms median with observation. The respective maxima were 16.68 and 30.43 ms.
  These are small RPC timing samples, not optical or model latency measurements.
- The final compiler report was **133,772 flash bytes** and **57,048 RAM bytes**,
  leaving 205,096 bytes of reported RAM. The core/library profile was unchanged.
- A checked stock fx request executed the snapshot CLI successfully in process
  permission mode `auto` and reported valid GPIO readback, all RGB channels off,
  and a blank firmware framebuffer. Its saved permission mode was not changed.
- The finite passive observer example completed successfully without changing
  outputs and released its subscription afterward.

Final readback showed both RGB LEDs off, a blank matrix, no playback, no active
observer, an empty event queue, and zero MCU queue drops. The deployment wrapper
remains running. Power-cycle persistence and optical brightness/timing were not
tested. Reports are in the board workspace's ignored `.cache/base-controller/`.

The installed App CLI 0.14 restart command was observed stopping the old app then
returning “app is running.” The deployment helper now uses explicit stop, waits
for terminal status, then starts. It verifies the expected version and a new boot
identifier when the previous controller is reachable. Regression tests cover
stop ordering and rejection of stale firmware identity. Services, boot defaults,
SSH settings, stock fx, and Modular credentials/configuration were preserved.

## Base controller on 2026-10-24

Version 0.1.0 implements MCU RGB LEDs 3 and 4, packed monochrome matrix frames,
transactional uploads of up to 32 frames, and finite or explicitly continuous
MCU playback. The standalone MCU apps were replaced by Python clients of this
shared firmware; no archive directory was created.

- The 53-test suite passes on macOS Python 3.14 and UNO Q Python 3.13, with one
  different dependency-related skip on each. The firmware state-machine test
  compiles and runs on macOS; the board lacks a native C++ compiler. The real
  Bridge wire test runs on the board; its runtime dependency is absent on the
  Mac. Together, both environments cover every test.
- Firmware state tests cover malformed frames, incomplete uploads, duplicate
  writes and commits, preserving old playback during an upload, full 32-frame
  capacity, abort/expiry, finite and looping playback, and 32-bit timer wrap.
- Client tests cover identity/version checks, boot changes, advisory writer
  exclusion, validation before upload, cleanup of failed uploads, no automatic
  mutation retries, and malformed status replies. Deployment tests reject
  changed source and denied access before issuing an app-start command, and
  discard old build manifests after failed compilation.
- Native `arduino-router-bridge` 0.5.1 plus `msgpack` 1.2.3 were installed in a
  project virtual environment on the board. Debian's missing `ensurepip` path
  was exercised using PyPA's bootstrap to install pip 26.2.2 inside that
  environment. No uv or global Python package installation was required.
- The native Bridge package successfully sent real MessagePack-RPC over a
  private simulated Unix router socket. Tests included maximum-size numeric
  arguments and 32-frame uploads, and checked requests/replies against a
  256-byte budget. This is protocol simulation, not communication with the MCU.
- The actual `prepare-controller.py --client --resolve` path compiled with core
  1.0.0 and the pinned library profile. A complete App CLI deployment wrapper
  also built successfully. Both reported **120,312 flash bytes** and
  **49,092 RAM bytes**; Arduino CLI reported 213,052 bytes of RAM remaining.
- All three skills passed the skill-creator validator. Bash syntax, Python
  parsing, local documentation links, and whitespace checks passed.

**Router access follow-up:** `/var/run/arduino-router.sock` is owned by root and
group `arduino-router`, mode 660. Initially, the SSH user was outside that group,
and a direct connection returned `PermissionError` (errno 13). The user then ran
`sudo usermod -aG arduino-router arduino`. A fresh key-authenticated SSH session
confirmed group membership and writable socket access. The native client reached
the router and received the expected missing-controller-RPC error. The prepared
firmware source fingerprint still matched, and `arduino-app-cli app ps` listed
no running app. The agent did not change socket modes, group membership, service
configuration, or SSH configuration.

### Deployment and live checks

After explicit user authorization, `flash-controller.py --replace-firmware`
started the base-controller app, uploaded the MCU firmware, and verified version
0.1.0, protocol 1.0, and `ready: true`. The same MCU boot identifier remained
throughout the subsequent native Python tests, with no per-pattern compilation,
upload, or app restart.

- Both MCU RGB LEDs accepted red, green, blue, and off commands.
- Static heart/border frames and the finite buffered sweep completed.
- Detached playback remained active after its Python process exited, advanced
  through all thirteen frame indices, and finished autonomously.
- The MCU rejected malformed frames, an invalid LED identifier, an incomplete
  upload commit, and a stale boot identifier. The incomplete upload preserved
  the prior committed animation; duplicate commit was acknowledged.
- Final clear and RGB-off commands were acknowledged. Status reported playback
  stopped and no pending upload. The user confirmed: “Both RGB and matrix work.”
- Twenty sequential native `info` RPCs measured 15.73 ms median, 16.13 ms p95,
  and 16.46 ms maximum. These measure RPC round trips, not visible LED timing
  or model response latency.
- A stock fx request executed `python/.venv/bin/unoq-control info` successfully
  with permission mode `auto`, reported version 0.1.0 and ready state, and saved
  no fx session. The existing saved permission mode was not changed.

The base-controller deployment wrapper remains running. Boot defaults, stock fx,
and Modular settings/credentials were unchanged. The controller guide describes
[normal use and deliberate replacement](../firmware/uno-q/controller/README.md).
MCU reset recovery, power-cycle persistence, and exact pixel orientation/timing
have not been separately verified. Detailed deployment and hardware reports are
stored in the board workspace's ignored `.cache/base-controller/` directory.

## Original workspace validation on 2026-10-23

The following records the earlier implementation, including the now-retired
standalone MCU apps. Dates use America/Los_Angeles.

### Host checks

- 33 dependency-free Python unit/integration tests passed on macOS ARM64 and
  on the UNO Q running Debian aarch64.
- Bash syntax and ShellCheck 0.11.0 passed for setup and doctor.
- All three skills passed the skill-creator frontmatter validator.
- Relative documentation links and whitespace checks passed.
- An independent skill exercise created a finite 104-pixel matrix animation in
  an isolated workspace. It respected compile-only scope and reported missing
  host-side Arduino tools instead of uploading or installing software.

Tests cover model discovery and authentication failures, visible-model
filtering and default fallback, preserving unrelated settings and custom model
metadata, backups, credential redaction and permissions, startup hook reruns,
piped workspace delivery, archive traversal rejection, LED state restoration
including interruption, and requiring a real successful shell result rather
than accepting a model's assertion.

### UNO Q checks

Board: UNO Q 4 GB, Debian aarch64. Tools: stock fx 0.0.14, Arduino App CLI
0.14.0, Arduino CLI 1.5.1, Arduino Zephyr core 1.0.0.

The actual piped bootstrap was exercised using a locally packaged archive in
place of the unpublished GitHub URL. It fetched the complete workspace into a
temporary directory and ran its real configuration entry point against an
isolated profile. Live checks passed:

- Authenticated `/v1/models` discovery filtered the known catalog. Additional
  unknown IDs were skipped instead of assigned guessed capabilities.
- MiniMax M3.1 Flash returned `MODULAR_OK`.
- fx executed `uname -m` and reported `aarch64` with permission mode `auto`.
- A fresh login shell loaded the credential without printing it.
- A rerun was idempotent after another Models API lookup.
- fx listed all three `uno-q-*` skills from the downloaded workspace.
- The live user's fx settings, startup files, and credential file were unchanged
  by these isolated-profile tests. Temporary credential copies were removed.

The missing-fx branch also downloaded and ran official fx 0.0.14 in an isolated
profile. The vendor receives the release tag `v0.0.14`. Its install directory is
already on the child PATH so it leaves startup files for our backed-up managed
hook. The private test installation was then removed.

The Linux RGB example's `--status` path was run read-only on the actual sysfs
channels. Simulated-file tests exercised color changes and restoration; the
validation process did not actuate the physical LED.

All three MCU sketches compiled using the installed core plus temporary,
checksum-verified copies of their library dependencies. All three also built as
complete App CLI release archives, including Python runtime preparation:

| App | Flash bytes | RAM bytes | Full app release |
|---|---:|---:|---|
| MCU blink | 72,288 | 29,072 | Passed |
| Matrix sweep | 80,928 | 33,104 | Passed |
| Bridge LED | 83,872 | 33,492 | Passed |

The compile helper's `--resolve` mode was exercised using the pinned profile.
The optional idle sketch also compiled (82,088 flash bytes, 33,600 RAM bytes).
These sizes describe the full/profile builds; a bare-core compile can differ.

### Boundaries

No firmware was uploaded and no app was started during validation. There is no
claim that a physical MCU LED or matrix animation was observed. Build dependency
archives and a Python App Lab runtime were fetched into build caches; no local
AI model, fx source patch, SSH change, service change, or boot-default change was
made. The user independently restarted their App CLI service during the work.

Hosted one-command download remains untested until the GitHub repository is
renamed/published. The local archive bootstrap path was tested. The CI workflow
is included but has not run on GitHub; no commit or push was performed.

The model tests establish a smoke-test result, not universal tool-call quality.
A live interactive M3.1 Flash session later supplied empty `{}` shell arguments
and hit `request.action is required`. fx rejected those calls without executing
them. This is distinct from Linux file permissions; full access cannot repair
invalid arguments. The troubleshooting guide records the checked retry shape.
The [incident journal](journal/2026-10-23-fx-empty-shell-arguments.md) preserves
the exact observations and separates them from the unconfirmed component cause.
