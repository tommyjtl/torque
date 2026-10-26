# Grayscale controller deployment and Half Helix playback

**Historical rollout:** This includes an explicitly authorized firmware upgrade.
Subsequent Linux-only updates use the
[verified unattended updater](2026-10-25-unattended-runtime-updates.md).
Firmware replacement remains a separate administrator operation.

The user explicitly requested flashing/restarting the controller as needed and
running Half Helix on the UNO Q. Before deployment, read-only checks found the
healthy 0.2.0 controller at the existing stable app path, an active Torque
service, no active turn/program, and retained blank display state.

The matrix belongs to the STM32 MCU. The Linux Torque daemon and Python SDK
were updated together with the resident controller, using a private copy of the
active release. The separate session's installed runtime work was retained.
Credentials were neither copied into the repository nor printed. Administrator
authentication happened in the user's own terminal because unattended sudo
required a password.

| Evidence | Result |
|---|---|
| Previous release | `0.1.0-9271b389ad23` |
| Applied matched release | `0.1.0-e5e9bab7e388` |
| Controller and SDK | 0.3.0; protocol [1,2]; grayscale capability advertises 0..7 |
| MCU boot ID | Changed from 973450602 to 1876154746 |
| Stable app / boot default | `/var/lib/torque/device/uno-q/controller`, unchanged |
| Torque service | Active and device ready after restart |
| Service unit | Unchanged SHA-256 `78c105ee13da53cc868841406fd1fa0cca816c28db8376a71162910ca97e6fc4` |
| Half Helix playback | 24 frames uploaded once; 15 finite loops completed |
| Passive framebuffer samples | 122 grayscale samples; all 24 frames observed and matched generated data |
| Brightness readback | All integer levels 0..7 observed |
| Finish | MCU playback stopped; example requested clear; Torque resumed its normal standby dot |
| Person's observation of LEDs | Not yet confirmed |

The activation helper successfully uploaded and verified firmware, then hit an
`AttributeError` while calling `wait_for_ready` from the older copied installer
helper. That function did not exist in the active release. Independent checks
confirmed firmware 0.3.0 and a healthy service. Recovery completed user-owned
installation bookkeeping and project staging without another flash or restart.
The temporary helper was corrected to provide its own readiness polling; a
subsequent invocation returned `already_applied` without repeating activation.

The deployment preserved the previous immutable runtime release and controller
source backups. It did not change the startup selection, service unit, user
groups, router permissions, or model configuration. The changed MCU boot
invalidated the old retained display intent; no old output was replayed.

The installed program uses `from torque import Board, Frame`, runs through
`torque run`, and is located at
`/home/arduino/torque/projects/half-helix/main.py`. Its passive verifier is
`verify_live.py` in the same folder. Live JSON evidence is saved there as
`live-result.json`, with deployment evidence under
`/home/arduino/.cache/torque/grayscale-rollout-8ygl_j6o/stage/applied.json`.
The combined local record is `projects/half-helix/validation.json`.

The staged release's installer pins match 0.3.0. A subsequent source-only cleanup
reconciled the generic installer's pins through `install/torque_bundle.py`, saved
the stage/apply helpers in `install/`, and added regression tests for older
installers without `wait_for_ready` and completed reruns without reflashing.
The reference example was renamed to `examples/06-dot-matrix-animations/` and
extended with Neon Drift, Core Spiral, and optional Keychron/terminal selection.
Those follow-ups did not restart services, reflash, or run the new animations.
Physical LED appearance, optical brightness, and power-cycle behavior remain
separate checks.

The source follow-up passed `python3 -m unittest discover -s tests -v` with 164
tests and two local native-Bridge skips. It generated the three SVG previews
under `projects/dot-matrix-animations/`. The gallery and input tests use simulated
devices/players, so they do not establish physical playback of the two new
animations or a live keyboard selection. The running board was unchanged.
