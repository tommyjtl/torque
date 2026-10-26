# Troubleshooting

For installed Torque, start with `torque doctor` or `torque status --json`.
Local device readiness and cloud authentication are separate checks.

## Linux runtime maintenance

The configured validation board uses the external SSH updater:
`torque update prepare/apply/status/recover`. Routine activation needs no user
sudo script after bootstrap. The running Torque agent must not self-update or
invoke sudo; its service retains `NoNewPrivileges`. Report a missing grant,
unexpected ownership, inactive service or busy transaction for the external
operator. Do not broaden permissions or change vendor services to pass a check.

An interrupted activation is handled with `torque update recover UPDATE_ID` by
that external operator. Firmware/app startup and boot defaults remain separate
explicit workflows. Arduino vendor sudoers files may be root-owned 0644; preserve
them. The dedicated Torque restart fragment is root-owned 0440.

## Stock fx and prototype diagnostics

In a source checkout, `scripts/doctor.sh` reads versions, service state,
LED access, and credential availability without printing credentials or sending
API requests. These stock-fx checks are separate from installed Torque startup.

- **fx not found:** use `~/.local/bin/fx`, or open a fresh SSH login after setup.
- **Credential missing:** confirm the private file exists, is owned by the user,
  and has mode 600. Edit it privately with `nano ~/.config/fx/modular-api-key`.
  Do not display it with `cat`, `env`, `printenv`, or shell tracing.
- **Provider mismatch:** inspect `fx status --json`; `FX_PROVIDER`, `FX_MODEL`,
  and private workspace overrides can take precedence over global settings.
- **HTTP 400 / grammar error:** read `docs/model-compatibility.md`. Use a model
  that passed stock-fx tool tests; do not patch fx or bypass permissions.
- **`invalid_shell_request` / `request.action is required`:** the shell
  arguments received by fx are malformed. For fx 0.0.14, a run request includes
  `{"request":{"action":"run","command":"python3 led_demo.py","timeout_ms":10000}}`.
  Correct the call and retry in a new turn. Full access does not repair argument
  validation; keep `/permissions auto` (or the user's normal checked mode).
  See the [incident journal](../../../../docs/journal/2026-10-23-fx-empty-shell-arguments.md)
  for the observed empty arguments and the unresolved source of the failure.
- **LED permission denied:** report the exact inaccessible LED channel. Do not
  chmod sysfs, install broad sudo rules, or use a different status LED silently.
- **App startup fails:** check `arduino-app-cli app ps`, app logs, and the state
  of `arduino-app-cli`, `arduino-router`, and Docker. An inactive daemon is not a
  reason to change boot settings or restart the stack automatically.
- **Sketch does not compile:** check `arduino-cli core list`, `arduino-cli lib list`,
  the app's `sketch.yaml`, and installed headers. Keep dependencies explicit.

Do not include private diagnostic dumps in an issue. Record tool versions,
selected non-secret model ID, the failing command, and a redacted error instead.
