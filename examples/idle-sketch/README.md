# Idle MCU sketch

This optional replacement firmware turns the built-in MCU LED off and clears
its matrix. It is not an Arduino App and is never uploaded by setup or tests.
Upload it only when deliberately stopping/replacing the current MCU program,
using the installed board's normal upload workflow. Restoring a previous app is
also an option. A Linux app stop alone does not guarantee an autonomous MCU loop
has stopped.

Compile it with the pinned profile (may download build dependencies):

```bash
arduino-cli compile --profile default examples/idle-sketch
```

This command does not upload. Deliberate upload must use the actual board/port
identified by the installed tools.
