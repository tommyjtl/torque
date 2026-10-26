# Matrix patterns from Python

Show a heart and an asymmetric border on the MCU's 8×13 blue LED matrix, holding
each for 0.8 seconds, then clear it. The border's corner marks help verify row
and column orientation on the real board.

Prepare and deliberately deploy the
[base controller](../../firmware/uno-q/controller/README.md) first, with intended
router access for the current user. From the workspace root, when execution is
requested:

```bash
packages/device/.venv/bin/python examples/03-matrix-patterns/main.py
```

Edit `Frame.from_rows(...)` strings to change a pattern: exactly eight strings
of thirteen `.`, `#`, `0`, or `1` characters. This needs no firmware rebuild or
app restart. Copy this folder into `projects/<name>/` to make a new demo.

The script requests clear on completion, Ctrl-C, or SIGTERM. After a connection
loss or hard kill, clear explicitly when access returns:

```bash
packages/device/.venv/bin/unoq-control clear
```

The command does not prove that a person saw the displayed pattern. Physical
orientation and appearance need observation after the first authorized upload.
