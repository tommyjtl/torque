# Torque

Torque uses unmodified libfx, Modular Cloud, and the Arduino UNO Q. Stock fx
remains a separate prototype/diagnostic application.

- Keep credentials outside the repository. Never print keys, dump the environment,
  or put credentials in command arguments, examples, manifests, or Git.
- Preserve fx permission checks. Do not patch fx to work around provider errors.
- Installed MCU programs use `from torque import Board, Frame`; direct
  `unoq_control` access is reserved for developer diagnostics and bring-up.
- Put generated variations in `projects/`; keep `examples/` as reference projects.
- Identify the processor a component belongs to before choosing an API. UNO Q's
  matrix is 8 rows by 13 columns; it is not the UNO R4 matrix.
- Creating or compiling an example does not authorize running it or flashing the
  MCU. When the user requests execution, check the current app and explain that
  starting an Arduino app can stop it and replace the MCU sketch.
- Preserve service configuration and boot defaults. Report missing permissions or
  inactive services instead of changing them as a side effect of setup or tests.
- Prefer the installed CLI's `--help`, installed headers, and bundled examples
  over remembered APIs. The default MCU FQBN is `arduino:zephyr:unoq`.
- Distinguish software checks, successful upload, and a person's observation of
  the physical LED. A successful command does not prove the LED was seen.

## Linux runtime updates

The validation UNO Q has the unattended updater enabled and verified as of
2026-10-26. For a user-requested Linux application update, use the normal
`arduino` account over SSH, outside `torque.service`:

```bash
torque update prepare --source /path/to/reviewed-checkout
torque update apply UPDATE_ID
torque update status UPDATE_ID
```

- Freeze/review the selected source first. Use `--scope examples` for example
  data/manifests only; do not ship another agent's unrelated working changes.
- On a configured board, activate authorized updates autonomously. Do not ask
  the user to run a sudo activation script or repeat administrator bootstrap.
  Routine updater code runs without sudo; its sole privileged operation is the
  already delegated `sudo -n /usr/bin/systemctl restart torque.service`.
- Do not use `sudo python3 install/update-runtime.py`, edit an active release in
  place, broaden sudo policy, disable `NoNewPrivileges`, or update from inside
  the running Torque agent. The root-owned service and launcher stay protected.
- Busy turns, approvals, model/reset operations and managed programs are refused.
  Wait/report the conflict; do not cancel work to make an update fit unless asked.
- Use `torque update recover UPDATE_ID` after interrupted activation. Identical
  source and completed transactions must not cause another restart. `gc` is only
  for validated unused managed releases; preserve projects, credentials and leases.
- Verify the actual release/version and new daemon epoch, readiness, unchanged
  MCU boot, service configuration, boot default and user settings. Preserve user
  display intent through adoption, without replaying actuator commands.
- The grant covers Linux runtime updates, not firmware, Arduino app start/stop,
  boot selection, OS packages or other services. Those need their own explicit
  authorization. Other boards may still need administrator bootstrap; report a
  missing grant/ownership or inactive service instead of silently repairing it.
- Preserve Arduino's existing vendor sudoers files. Bootstrap validates global
  syntax and safe ownership while enforcing 0440 only for Torque's own rule.
- Check space on the destination filesystem: `/opt/torque` and `/home/arduino`
  are separate storage pools on the validation board. Current `gc` handles
  managed releases when invoked; automatic cache budgets/retention are still a
  [design draft](docs/design-spec/2026-10-26-managed-storage-retention.md), with
  measurements in the [cleanup journal](docs/journal/2026-10-26-storage-cleanup-and-retention.md). Before
  pruning deployment caches, check runtime/process/container references and
  preserve sources, receipts, live leases, projects, credentials and vendor tools.

See [CLI usage](docs/cli.md#unattended-linux-runtime-updates),
[setup/recovery](install/README.md), the
[design](docs/design-spec/2026-10-25-unattended-runtime-updates.md), and the
[verified rollout](docs/journal/2026-10-25-unattended-runtime-updates.md).

## Local speech direction

CPU streaming Zipformer is the selected baseline for the next local English
speech prototype. In the six-clip experiment it finalized the last segment a
median 0.387 s after file end (18/18 below one second), versus 6.457 s for the
working GPU hybrid path (0/18). The GPU experiment is closed for its latency
result; do not restage GPU speech work unless requested. Keep its archived
evidence and the CPU model/runtime. Live microphone buffering and whole-turn
detection are not validated; the fast endpoint splits some longer utterances.
Use push-to-talk or explicit turn handling for the first live prototype. See
the [benchmark and decision](docs/journal/2026-10-30-ncnn-streaming-speech-benchmark.md).
Initial live trials with greedy and four-path beam search were responsive but
had connected-speech errors. Live recognition quality is not accepted; do not
present the recorded-clip result as production voice accuracy.

Run `python3 -m unittest discover -s tests -v` after changing Python or setup code.
Run `bash -n setup.sh scripts/doctor.sh` after changing shell scripts.
