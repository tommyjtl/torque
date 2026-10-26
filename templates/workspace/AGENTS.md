# My Torque workspace

Put generated programs and repositories in `projects/`. Add personal reusable
instructions in `skills/<name>/SKILL.md`. This file and your projects are preserved
when Torque is updated. Packaged board skills are supplied by the managed release.

Linux runtime maintenance belongs to the external SSH updater. After administrator
bootstrap, the normal account uses `torque update prepare/apply/status/recover`;
the running Torque agent does not self-update or run sudo. Keep user programs
and these personal instructions outside the release being replaced.

For a first program, ask Torque to create and run a finite 8x13 matrix demo using
the resident controller, inspect its framebuffer, and clear it when finished.
