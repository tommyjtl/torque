# MCU RGB color cycle

The native Python client cycles MCU RGB LED 3 through red, green, and blue three
times, with 0.3 seconds per color, then requests all channels off. No wiring is
needed. Colors are binary; PWM dimming is not implemented.

First prepare and deliberately deploy the
[base controller](../../firmware/uno-q/controller/README.md). The running user
needs local router socket access. From the workspace root, when execution is
requested:

```bash
packages/device/.venv/bin/python examples/02-mcu-rgb-led/main.py
```

The program sends commands only; it never compiles, uploads, restarts apps, or
changes access permissions. Ctrl-C and SIGTERM enter the off-cleanup path.
Cleanup requires a working connection; a killed process or disconnected board
cannot guarantee the LED turns off. Request off later with:

```bash
packages/device/.venv/bin/unoq-control rgb 3 0 0 0
```

Copy the folder into `projects/<name>/` for a variation. Use the same prepared
Python environment. Acknowledged RPCs and observed physical colors are separate
validation results.
