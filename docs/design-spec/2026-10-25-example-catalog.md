# Manifest-driven example catalog

Torque application 0.2.0 adds `torque example`; `unoq-control` and firmware
remain 0.4.0 / protocol 1.3. This is a Linux software change, with no MCU upload.

Each reference directory supplies `example.toml` schema 1: stable slug, title,
description, relative Python entrypoint, and named launch modes. Each mode owns
default `args` and `requires`. `run` is required and is the default mode. Python
scripts retain their own argparse options/defaults; user arguments are forwarded
after the mode defaults, without a second argument schema in Torque.

`torque example` lists the packaged catalog. `torque example SLUG [ARGS...]`
launches run mode. Launcher options precede the slug, for example
`torque example --mode preview dot-matrix-animations`. Everything after the slug
belongs to the child, including `--help`. All registered entrypoints must handle
`--help` and reject unknown arguments before any hardware access.

`torque.examples` provides shared discovery and launch functions. Discovery
reads data only, validates duplicate slugs, mode/argument shapes, and contained
entrypoint/resource paths. The wheel build automatically bundles every folder
with an `example.toml`, including its ordinary local resource files. No manual
Python registry or index is maintained. The installed wheel catalog takes
precedence over checkout discovery; arbitrary working directories are never
searched for executable examples. `idle-sketch` has no manifest and stays out
of this command because its purpose is deliberate firmware replacement.

Listing, help, preview, and Linux-only modes do not need the daemon. `daemon`
requirements check readiness; other requirement names query controller
capabilities through existing read-only daemon RPCs. The child retains normal
device ownership and permission checks. No model turn, service restart,
permission change, app start, or firmware upload is an example-launch action.

Children run with the managed Python interpreter, explicit argv (no shell),
and the same credential-environment filtering as workspace programs. Output
and cwd live in `WORKSPACE/projects/examples/SLUG`, never in read-only package
data. Mode args may use only `{workspace}` and `{output_dir}` substitutions.
`torque run` continues to require a script under workspace `projects/`.

Validate discovery and path containment, malformed manifests, new-folder
discovery, all six safe help entrypoints, no-daemon modes, capability errors,
argument precedence/forwarding, sanitized environments, workspace output,
wheel/sdist contents, and invocation from an installed wheel outside a checkout.
Run the full repository Python suite. Installing the new application release
is separate from these software checks; it does not require an MCU reflash.
