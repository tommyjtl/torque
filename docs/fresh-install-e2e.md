# Fresh installation E2E

This records the default full installation/reboot path before optional
unattended-update bootstrap. Its root-owned runtime checks describe that initial
layout. After bootstrap, application releases are user-owned while the system
unit/launcher stay root-owned. For routine Linux changes use
[the updater](cli.md#unattended-linux-runtime-updates); this E2E is an explicitly
requested installation test, not an activation prerequisite.

This is an explicit test of the real UNO Q installation, including sudo and a
Linux reboot. It replaces only Torque-managed runtime/state and keeps a backup.
It preserves the user workspace, Modular credential, global FX settings,
prototype checkout, other Arduino apps, Debian and SSH configuration.

Preparation runs as the board user:

```bash
python3 install/e2e.py prepare
```

It creates a unique source snapshot, builds a new private runtime, and forces a
new controller compilation by saving the previous Torque preflight cache.
Verified dependency archives and the vendor toolchain cache may still be reused;
no installed runtime environment or compiled controller is reused. The existing
owner-only Modular credential is a prerequisite; its value is never logged.

Preparation writes a concrete root test command to `~/.cache/torque/run-e2e.sh`.
Run it from a terminal; from a laptop with working SSH key authentication:

```bash
ssh -t arduino@tommy-uno-q.local 'bash ~/.cache/torque/run-e2e.sh'
```

The test then:

1. Records existing apps/startup selection and refuses an unrelated active app.
2. Stops Torque and its controller, and archives only `/opt/torque`,
   `/var/lib/torque`, the managed launcher and service. User programs and the key
   remain in place. Recovery files stay under the private E2E run directory.
3. Runs the production installer against the newly built bundle. The controller
   is deliberately deployed and its fresh boot checked.
4. Tests the installed CLI without environment activation, model response,
   exact-command tool approval, denied file writes, client detach, a generated
   finite heart program, independent state readback, shared telemetry and
   competing-writer exclusion. All agent tools run as the normal user.
5. Repeats the same-bundle installation and confirms it did not reset the MCU.
6. Registers one temporary boot-verification unit and reboots Linux.
7. Automatically repeats the normal-user tests after local readiness. It checks
   a new Linux boot ID, credential availability without disclosure, no spontaneous
   agent work before the test prompt, private IPC, root-owned runtime files and
   preservation of the existing workspace/global FX settings.
8. Disables and removes the temporary test unit after it finishes, including on
   failure. The regular `torque.service` remains installed.

The temporary boot unit uses root only to switch to the normal user and remove
its own registration. Model calls and hardware programs execute as the board
user through Torque's normal permission checks. The test does not grant blanket
approvals or modify SSH/sudo policy.

Reports are under `~/.cache/torque/e2e/<run-id>/` with mode 600. The path of the
latest run is saved in `~/.cache/torque/latest-e2e`. `result.json` is written after
boot; it is not a success receipt until `passed` is true. `install.json`,
`pre-boot.json`, and the agent reports provide the earlier evidence.

Preparation and unit tests alone do not prove privileged installation or reboot
success. Until the root command has finished and `result.json` passes, this test
is pending. Framebuffer/GPIO evidence remains separate from somebody seeing the
physical LEDs.

## Recorded hardware run

**Passed:** `20261025T015831-b096a238`, on the actual UNO Q 4GB. The tested release
is `0.1.0-f39b997888b0`; the controller is firmware 0.2.0, protocol 1.1.

The user entered the sudo password once through SSH. The runner archived the
previous managed runtime/state, installed the fresh bundle, ran the normal-user
checks, verified a same-bundle reinstall without reflashing, rebooted Linux,
and completed the automatic post-boot checks. No fabricated sudo context or
mock system service was used for those installation checks.

| Evidence | Result |
|---|---|
| Fresh private runtime and controller compilation | Passed; flash 133,772 bytes, global RAM 57,048 bytes |
| Production system installation | Passed |
| Pre-boot agent/hardware checks | Passed |
| Same-bundle reinstall | Passed; MCU boot ID stayed 1894979779 |
| Real Linux reboot | Boot ID changed from `77d22032-2bbb-40e8-bd8f-56dd925fea3f` to `f2484647-0836-40a7-b394-2606eb04c32e` |
| Post-boot agent/hardware checks | Passed; MCU boot ID 973450602 |
| Installed CLI without activation | Passed; actual model reply and `uname -m` tool result |
| Actual host-tool denial | Passed; denied file was not created |
| Agent-created finite heart program | Passed before and after reboot, with firmware framebuffer readback |
| Shared telemetry and competing writer rejection | Passed |
| User workspace and global FX settings | Baseline hashes unchanged |
| Credential persistence | Available after reboot, owner-only mode 600; value never printed |
| Normal-user service and private IPC | `arduino`, UID 1000; socket mode 600 |
| Idle display | Exact standby framebuffer restored; no playback or dropped MCU events |
| Temporary verification unit cleanup | Unit and enablement link removed |

A separate fresh SSH connection confirmed `torque.service` enabled and active,
the authoritative startup controller path correct, the deployed source/firmware
identity matching, and `torque doctor` reporting ready. Stock FX remains 0.0.14.
Host and board unit suites each passed 99 tests with two platform-specific skips;
the skipped native/C++ cases were covered on the other platform.

The private receipts are `install.json`, `pre-boot.json`, `post-boot.json`, and
`result.json` under `~/.cache/torque/e2e/20261025T015831-b096a238/` on the board.
The final receipt has `passed: true`. A local ignored copy of the summary receipts
is under `.cache/e2e-20261025T015831-b096a238/`. The prior managed files remain in
the private `system-backup/` directory for recovery.

No optical sensor was used. These results confirm commands, MCU framebuffer and
GPIO state; they do not replace a person checking the physical LED appearance.
