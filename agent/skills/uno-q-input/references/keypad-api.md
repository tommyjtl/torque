# Torque project input API

```python
from torque.input import (
    Keypad, KeypadUnavailable, KeypadBusy, KeypadDisconnected, input_capabilities,
)

print(input_capabilities())  # Identity/readability/advertised keys only.
with Keypad() as keypad:
    # Put this inside the project's finite game/render loop.
    for event in keypad.poll(timeout=0.02):
        if event.action == 'press' and event.key == 'KP8':
            rotate()
        elif event.action == 'press' and event.key == 'ESC':
            quit_game()
        elif event.action == 'resync':
            reset_transient_input()
    if keypad.is_down('KP4'):
        move_left_using_game_timer()
```

`Keypad()` opens immediately. Its context manager closes the device and project
lease. `poll` accepts 0..1 seconds and reads one bounded batch. `KeyEvent` has
`key`, `action` and numeric `code`; actions are `press`, `release`, `repeat` or
`resync`. A resync marker has no key/code. `held` is a frozen set of active
symbolic names; `is_down(name)` checks membership.

Keys held at startup or resync are suppressed until released. OS repeat events
remain explicit, so rotate/pause/confirm should normally respond only to presses.
Movement should use application timing rather than assume a particular OS
repeat delay. Lost event batches are discarded and held state queried again;
the helper does not reconstruct missing actions.

| Names | Meaning in this keypad profile |
|---|---|
| `KP0`..`KP9` | Numpad digits |
| `1`..`9` | Number-row digits if emitted by this keypad's active mapping |
| `KPENTER`, `KPDOT` | Numpad Enter and decimal |
| `KPPLUS`, `KPMINUS`, `KPASTERISK`, `KPSLASH` | Numpad operators |
| `KNOB_UP`, `KNOB_DOWN` | Surveyed volume-up / volume-down codes from rotation |
| `KNOB_PRESS` | Surveyed mute code from knob click |
| `ESC`, `NUMLOCK`, `TAB`, `BACKSPACE`, `DELETE` | Named auxiliary keys |
| `LEFT`, `RIGHT`, `UP`, `DOWN`, `HOME`, `END`, `PAGEUP`, `PAGEDOWN`, `INSERT` | Navigation events if emitted by the active mapping |

These names describe emitted events, not a guarantee that every physical layer
produces them. The device can advertise more keys than are physically present.
Do not bind unlabelled M/Fn controls by guessing. Ignore unsupported keys; ordinary
programs do not decode typed text or persist input streams.

`input_capabilities()` returns `available`, `selection_required`, `devices` and
a `reason`. Each device reports identity, node, readability and advertised keys.
It does not consume queued events, report held keys or claim a project lease.
The host tool of the same name exposes this metadata without shell inspection.

One readable matching keypad is selected automatically. With several, use
`Keypad(address='...')` with an address returned by discovery. Device addresses
are installation-specific; no address is embedded in the package.
The helper accepts an explicit address argument; it does not load a saved device
preference automatically. A project can read its own local configuration and pass
the selector, keeping that configuration outside Git. Animation/game presets bind
logical controls, not physical addresses.
Documentation placeholders are not runnable device defaults. The separate developer
capture logger requires `--address`; it is not the normal project input interface.

`KeypadUnavailable` means no unique usable device. `KeypadBusy` means another
cooperating project holds the advisory lease: report it rather than fallback.
`KeypadDisconnected` clears held state and closes the device/lease. Pause or exit
the project cleanly; a new `Keypad` can rediscover a reconnected device. Never
change permissions or pairing to conceal an unavailable device.

Project leases coordinate this helper's readers; they do not exclude Linux's
desktop/console or unrelated evdev readers. No OS grab or global agent binding
is installed. Physical keypad events reach the UNO Q, not the Mac SSH terminal.

The template defaults to an offline preview. `--play --input keypad --seconds 30`
requires manual controls; `--play --input none --seconds 10` requests finite
autoplay. `--input auto` uses a keypad if available, otherwise announces finite
autoplay. Disconnection stops play and cleanup requests clear. The normal Torque
status cue resumes after output ownership is released.
