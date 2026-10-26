# Linux user RGB LED

Cycle the MPU-controlled user LED through red, green, and blue. This plain
Python program needs no App Lab daemon, Docker container, firmware upload,
Modular request, or external wiring.

From the workspace root, inspect access without changing the LED:

```bash
python3 examples/01-linux-rgb-led/main.py --status
```

Run a finite demo when you want the physical LED to change:

```bash
python3 examples/01-linux-rgb-led/main.py --cycles 3 --interval 0.3
```

Expected behavior: the user RGB LED cycles through the colors, then returns to
its previous brightness and kernel triggers. The script uses each channel's
`max_brightness`. It leaves panic, WLAN, and Bluetooth status LEDs alone.

Ctrl-C or SIGTERM enters the same restoration path. Restoration cannot be
guaranteed after SIGKILL, a power loss, changed permissions, or another program
writing the same LED concurrently. A permission error is reported without
changing access rules. Do not run concurrent demos against the same LED.

Create a variation with:

```bash
cp -R examples/01-linux-rgb-led projects/my-rgb-demo
```

The default loop lasts about 2.7 seconds. `--status` is read-only.
