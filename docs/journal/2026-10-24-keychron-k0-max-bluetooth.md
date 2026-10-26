# Keychron K0 Max Bluetooth setup on Arduino UNO Q

**Date:** 2026-10-24, America/Los_Angeles

**Publication note (2026-10-26):** Hardware addresses in this public record are
replaced with `<KEYPAD_BT_ADDRESS>` and `<CONTROLLER_BT_ADDRESS>`. They are
documentation placeholders, not configured defaults. Obtain your own address
from local Bluetooth/device discovery. Raw captures remain outside Git.

**Status:** Paired, connected, and live input verified. The same-day follow-up
confirmed the saved Bluetooth state, matching input devices, and fresh press
and release events for all six tested numpad keys. A later full-key survey and
post-reset survey are recorded below. Wake-assisted reconnection was observed
without an assistant-issued manual connect; immediate connection at boot was
not measured.

Bluetooth and keyboard input belong to the UNO Q's Linux processor. This setup
does not require starting an Arduino app or replacing the MCU sketch.

## Device identity

| Item | Value |
|---|---|
| UNO Q hostname | `tommy-uno-q` |
| Bluetooth controller | `<CONTROLLER_BT_ADDRESS>` |
| Keyboard address | `<KEYPAD_BT_ADDRESS>` |
| Keyboard address type | Random |
| Device identity / BlueZ modalias | `usb:v3434p0A06d0204` |

## Pairing procedure

The reported successful procedure was to put the Keychron into Bluetooth pairing
mode, then run on the UNO Q:

```bash
bluetoothctl
```

Inside `bluetoothctl`:

```text
agent off
agent KeyboardDisplay
default-agent
scan on
```

Wait for:

```text
Device <KEYPAD_BT_ADDRESS> Keychron K0 Max
```

Then run:

```text
pair <KEYPAD_BT_ADDRESS>
trust <KEYPAD_BT_ADDRESS>
connect <KEYPAD_BT_ADDRESS>
info <KEYPAD_BT_ADDRESS>
scan off
quit
```

The reported final state was:

```text
Paired: yes
Bonded: yes
Trusted: yes
Connected: yes
```

An earlier `scan off` returned `org.bluez.Error.Failed`, but subsequent discovery
and pairing succeeded. The live follow-up did not repeat pairing or discovery.

## Original keyboard input verification

The user reported installing and running `evtest`:

```bash
sudo apt install evtest
sudo evtest
```

The detected devices included:

```text
/dev/input/event3: Keychron K0 Max Keyboard
/dev/input/event4: Keychron K0 Max Mouse
```

Selecting `3` and pressing numpad keys produced events for keys **1–6**, including:

```text
EV_KEY KEY_KP4 value 1
EV_KEY KEY_KP4 value 0
EV_KEY KEY_KP5 value 1
EV_KEY KEY_KP5 value 0
```

`value 1` indicates a press; `value 0` indicates a release. Exit with **Ctrl+C**.

The keyboard sends input directly to the UNO Q; its keys do not automatically
type into an SSH session opened from another computer.

**Device event numbers may change.** Application code should discover the
keyboard by identity rather than hardcode `/dev/input/event3`. Match the
keyboard interface, not the companion mouse interface.

## Same-day live verification

A read-only SSH check at **2026-10-24 17:47 PDT** (**2026-10-25 00:47 UTC**)
confirmed the following on `tommy-uno-q`:

- Installed `bluetoothctl` version: **5.82**.
- Controller `<CONTROLLER_BT_ADDRESS>`: `Powered: yes`, `Discovering: no`.
- Keyboard `<KEYPAD_BT_ADDRESS>`: `Paired: yes`, `Bonded: yes`, `Trusted: yes`,
  `Connected: yes`, `Blocked: no`; modalias `usb:v3434p0A06d0204`.
- `systemctl is-active bluetooth` returned `active`.
- `systemctl is-enabled bluetooth` returned `enabled`.
- `/usr/bin/evtest` was already installed. The SSH user could read both matching
  input devices without sudo; device permissions were `0660`.

The input devices were discovered through `/sys/class/input/event*/device/`,
then matched by name and Bluetooth identity:

| Field | Keyboard interface | Mouse interface |
|---|---|---|
| Event node at test time | `/dev/input/event3` | `/dev/input/event4` |
| Name | `Keychron K0 Max Keyboard` | `Keychron K0 Max Mouse` |
| `uniq` | `<KEYPAD_BT_ADDRESS>` | `<KEYPAD_BT_ADDRESS>` |
| `phys` | `<CONTROLLER_BT_ADDRESS>` | `<CONTROLLER_BT_ADDRESS>` |
| `id/bustype` | `0005` (Bluetooth) | `0005` (Bluetooth) |
| `id/vendor` | `3434` | `3434` |
| `id/product` | `0a06` | `0a06` |
| `id/version` | `0204` | `0204` |

The `usb:` prefix in the BlueZ modalias is part of the reported device identity;
the Linux input bus and controller association confirm this connection uses
Bluetooth.

A bounded, passive `evtest` check ran from **17:47:58 to 17:48:58 PDT** while the
user pressed numpad keys **1–6**. It selected the keyboard by this identity and
reported only `KEY_KP1` through `KEY_KP6` events, without an exclusive device
grab. Linux received **108 matching events**, including both press (`1`) and
release (`0`) events for **every tested key**:

```text
PRESS_RELEASE_PAIRS KP1=yes KP2=yes KP3=yes KP4=yes KP5=yes KP6=yes
```

Representative fresh events:

```text
Event: time 1792889278.509252, type 1 (EV_KEY), code 79 (KEY_KP1), value 1
Event: time 1792889278.640891, type 1 (EV_KEY), code 79 (KEY_KP1), value 0
Event: time 1792889279.719067, type 1 (EV_KEY), code 77 (KEY_KP6), value 1
Event: time 1792889279.833351, type 1 (EV_KEY), code 77 (KEY_KP6), value 0
```

The monitor stopped at its intended 60-second limit (`timeout` exit status
`124`). This verifies current physical keyboard input reaching Linux; it does
not verify reconnection after a reboot.

No packages were installed, services enabled or restarted, boot settings changed,
or Arduino apps started or stopped during this verification. The MCU was not
flashed and the board was not rebooted.

## Reconnection after boot

Pairing and trust are saved. **Automatic reconnection after reboot has not yet
been verified.** A current connection and an enabled Bluetooth service do not
establish that a reboot reconnects the keyboard automatically.

The original report suggested:

```bash
sudo systemctl enable bluetooth
```

It did not confirm that command was executed. The live follow-up independently
confirmed that the service is **already enabled**, so no service change was
needed or performed.

To verify reconnection in a separate reboot test:

1. Reboot the UNO Q when interruption of its current workload is intended.
2. Keep the Keychron in Bluetooth mode on the same paired channel.
3. Press a key to wake it.
4. Run:

   ```bash
   bluetoothctl info "<KEYPAD_BT_ADDRESS>"
   ```

   Look for `Connected: yes` before attempting a manual connection.

If necessary, reconnect manually:

```bash
bluetoothctl connect "<KEYPAD_BT_ADDRESS>"
```

Record whether reconnection was automatic or required that command. Enabling
the Bluetooth service does not by itself guarantee reconnection. Test the
existing behavior before considering a custom reconnect service.

## Full-key capture utility and later surveys

The [capture utility](../../tools/keychron-capture/README.md) is implemented in
`tools/keychron-capture/capture.py`. The user-workspace copy on this UNO Q is
`~/torque/projects/keychron-capture/capture.py`. It runs without sudo or Python
package installation and reads only this Bluetooth keypad's matching input
interfaces. It is a bounded, passive capture; there is no exclusive device grab,
background service, permission change, keymap write, or MCU firmware change.

The utility verifies the opened file descriptor's Bluetooth identity rather than
trusting an event number, then captures the Keyboard and companion Mouse
interfaces. It records capabilities, initial held keys/LED state, scan codes,
key press/release/repeat, held-key chords, and relative/absolute controls. It
records hotplug and overrun gaps and resynchronizes key state rather than
inventing lost presses. The board's installed libevdev supplies symbolic names;
numeric type/code/value fields are retained regardless.

During these tests the interfaces were `/dev/input/event2` and `event3`,
showing why the old `event3` keyboard assignment must not be hardcoded. The
Keyboard interface advertised 283 key codes and the Mouse interface five;
those are HID capabilities, not a count of physical keys.

After the actual Torque E2E Linux reboot, the keypad initially reported
`Connected: no`. The user reported waking it in its paired Bluetooth slot.
It subsequently reported `Connected: yes`, and both interfaces became readable,
without an assistant-issued connect/pair/trust command. The user later reset
the keypad and the same wake-assisted connection sequence worked again.

### Before the user-reported reset

Session `20261025T023521` ran at **2026-10-24 19:35:21–19:37:33 PDT**
(**2026-10-25 02:35:21–02:37:33 UTC**). The user pressed the controls, including
knob rotation and click. It recorded 730 raw events, 41 distinct Linux key codes,
and 121 complete press/release cycles, with no input gaps or held keys at exit.
All observed input came through the Keyboard interface; no relative/absolute
motion or Mouse-button events were observed in this trial.

Physical button labels were not assigned by this unlabelled trial.

### After the user-reported reset

The user reset the keypad and requested a fresh test. Session `20261025T024552`
ran at **2026-10-24 19:45:52–19:48:30 PDT**
(**2026-10-25 02:45:52–02:48:30 UTC**). It recorded 432 raw events, 41 distinct
Linux key codes and 71 complete press/release cycles. No gaps or held keys
remained when the capture was deliberately stopped.

| Tested control or output | Linux input observed | Numeric EV_KEY code |
|---|---|---:|
| Knob rotation in one direction | `KEY_VOLUMEUP`, six press/release cycles | 115 |
| Knob rotation in the other direction | `KEY_VOLUMEDOWN`, eight cycles | 114 |
| Knob press | `KEY_MUTE`, one cycle and two repeat events | 113 |
| Numpad 0–9 | `KEY_KP0` through `KEY_KP9` | 82, 79, 80, 81, 75, 76, 77, 71, 72, 73 |
| Numpad divide, multiply, subtract, add | `KEY_KPSLASH`, `KEY_KPASTERISK`, `KEY_KPMINUS`, `KEY_KPPLUS` | 98, 55, 74, 78 |
| Numpad decimal and Enter | `KEY_KPDOT`, `KEY_KPENTER` | 83, 96 |
| Num Lock | `KEY_NUMLOCK` | 69 |
| Escape, Delete, Tab, Backspace | Corresponding Linux key codes | 1, 111, 15, 14 |

`KEY_KPENTER` was observed in the post-reset trial. The utility did not read or
write the Keychron configuration.

The held knob press lasted about 337 ms and generated two `value=2` repeat
events. A future confirm/approve handler should act once on the intended edge
and filter repeats, while tying any approval to the exact pending request and
session. It must not convert each repeat into another confirmation.

No direct `KEY_FN` event, relative wheel event, or absolute-axis event was
observed. That is an observation for these trials, not proof that all possible
layers/chords have been tested. Firmware-local Fn behavior and physical macro
labels need deliberate labelled trials before choosing final bindings.

### Files and repeatable labelled trials

Both board-local sessions are under:

```text
~/torque/projects/keychron-keymap/20261025T023521/
~/torque/projects/keychron-keymap/20261025T024552/
```

Each owner-only directory contains `events.jsonl`, `summary.json`, and
`report.md`, with file mode 600. Local raw-capture copies are stored outside the
repository checkout. Personal mappings and decoded input text are not included
in the repository documentation.

For a labelled pass from the Mac:

```bash
ssh -t arduino@tommy-uno-q.local \
  'python3 ~/torque/projects/keychron-capture/capture.py --address "<KEYPAD_BT_ADDRESS>" --guided --duration 900 --profile "BT labelled controls"'
```

Type a physical label on the Mac terminal and press Enter, then operate that
control on the Keychron. Examples are `M1`, `knob clockwise`, or `Fn + 1`.
Enter the next label to advance; a blank label finishes. A quiet trial is marked
`no_linux_event_observed`, and ordered macro key-down/up sequences remain in the
JSON. This distinguishes physical labels from inferred key names.

The complete Python suite passed 113 tests on the Mac and board, each with two
platform-specific skips. Capture-specific tests cover identity matching,
fragmented native input records, signed axes, initial held state, repeat/hold
tracking, cross-interface chords, labelled macros, SYN_DROPPED, disconnects,
unknown numeric codes and owner-only reports. The actual capture was performed
as UID 1000 with no sudo, against both live matching interfaces.
