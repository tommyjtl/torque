# Keychron K0 Max input survey

Capture the paired keypad on the UNO Q's Linux side so its controls can later
be mapped to Torque session commands and MCU/display feedback. The
[pairing journal](../../docs/journal/2026-10-24-keychron-k0-max-bluetooth.md)
records the verified model/interfaces using anonymized address placeholders.

This utility uses Python's standard library. If the already-installed libevdev
library is available, it supplies symbolic event names; otherwise numeric type
and code values are retained. It needs read access to the input nodes and does
not change permissions, pairing, services, key mappings, or MCU firmware.

## Free capture

Run on the board:

```bash
bluetoothctl devices
python3 tools/keychron-capture/capture.py --address "<KEYPAD_BT_ADDRESS>" --list
python3 tools/keychron-capture/capture.py --address "<KEYPAD_BT_ADDRESS>" --duration 180 --profile 'BT current mapping'
```

Replace `<KEYPAD_BT_ADDRESS>` with your paired keypad's locally reported address.
There is no device-address default. This developer logger requires an explicit
target because it records raw input. Ordinary projects should use the shared
`Keypad()` discovery API instead of embedding an address or running this tool.

Press and release each physical key, turn the knob in both directions, press
it, and hold a key briefly to check repeats. You can test chosen chords and
Num Lock states while staying on the same paired Bluetooth slot. Ctrl-C in
the SSH/local terminal finishes early and writes the report.

The tool is passive: the board's normal input consumers also receive these
keypresses. Keypad input does not automatically type into a laptop's SSH terminal.
It opens all matching interfaces for this one keypad, including the companion
Mouse interface, and verifies the opened device identity. Event numbers can
change across boots and reconnects. Reconnected interfaces are discovered again.

## Labelled capture

For physical labels such as M1/M2, Fn shortcuts, or comparing keypad modes:

```bash
python3 tools/keychron-capture/capture.py --address "<KEYPAD_BT_ADDRESS>" --guided --duration 900 --profile 'BT labelled controls'
```

1. Type a label such as `M1` on the laptop/local terminal and press Enter.
2. Press and release that control on the Keychron.
3. Type the next label, then test that control. Examples: `7`, `knob clockwise`,
   `knob counterclockwise`, `knob press`, `Fn`, `Fn + 1`, `Num Lock off: 7`.
4. Enter a blank label to finish. The duration also bounds the session.

A labelled window with no event is explicitly recorded. That does not prove
that a key is unusable: the operation may be internal to the keypad, or no input
may have happened during the window. Ordered key-down/up sequences are retained
for macro buttons; simultaneous held keys are also reported. Controls which emit
the same codes need contextual bindings or a later deliberate keymap change.

## Output

A new owner-only directory is created under
`~/torque/projects/keychron-keymap/<UTC timestamp>/`, or use `--output PATH`.
Existing output directories are not overwritten. Files use mode 600:

- `events.jsonl`: exact event type/code/value, kernel timestamp, device identity,
  scan codes, labels, press/release/repeat, held-key sets, connect/disconnect and
  resync markers. Raw events are retained in original order per interface.
- `summary.json`: observed keys, full press/release cycles, observed hold duration,
  relative/absolute controls, chords, and labelled sequences.
- `report.md`: a readable mapping table for reviewing the next integration step.

These local reports can contain real device addresses and keystrokes. Keep them
in the ignored user workspace, and anonymize shared excerpts. Do not put a
personal device address into a preset, packaged skill or repository fixture.

Initial held-key/LED state and advertised capabilities are recorded as metadata.
Advertised keys are not a checklist of actual physical keys—the keyboard
interface may advertise many more codes than its physical layout provides.
High-resolution wheel and legacy wheel codes remain separate; do not sum them
as independent physical motion. Buffer overruns (`SYN_DROPPED`) and disconnects
are explicit gaps; lost events are not fabricated. Key state is queried again
after the next synchronization packet, and incomplete labels are marked.

## Later Torque integration

Use the observed device identity plus numeric Linux event type/code and the
required action (press, release, hold, chord or axis direction). Input handling
belongs in the Linux session controller; it can then send commands to the
existing MCU controller. Capturing these inputs does not require a new sketch.
Approval controls must address a specific pending request in a specific session,
rather than grant blanket permission for future tools.

Sources: [Linux input event protocol](https://docs.kernel.org/input/event-codes.html),
[Keychron K0 Max manual](https://www.keychron.com/pages/keychron-k0-max-user-manual).
