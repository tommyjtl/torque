---
name: uno-q-input
description: Use Keychron controls or explicitly requested microphone input in UNO Q projects through Torque's shared Python input and audio APIs.
---

# Project input on UNO Q

For microphone/sound-reactive requests, check the read-only `audio_capabilities`
tool and read [audio-api.md](references/audio-api.md). Capture runs on Linux;
MCU output still uses the public Board API. Endpoint discovery is not a signal
test or permission to begin recording. Preserve requested durations and storage
intent; use finite local capture without files or uploads when only levels are needed.

Consider input when building games, selectable animations or menus. Use the
read-only `input_capabilities` tool to check current availability; past pairing
does not prove a keypad is awake/readable now. When useful input exists, choose
sensible controls without asking users for Linux codes or event paths. Preserve
explicit autoplay, requested durations and existing project behavior.

Use `from torque.input import Keypad` for local event polling and held state.
Read [keypad-api.md](references/keypad-api.md) for exact API, names and lifecycle.
Keep the game loop local: keypresses do not invoke the model. MCU output still
uses `from torque import Board, Frame`; no firmware update is needed.

Choose bindings suited to the project and show a short legend when starting it.
For example, 4/6 move, 8 rotates, 2 drops, Enter confirms and Escape exits.
Knob down/up can adjust a value; knob press can pause. These are application
bindings, not a keypad remap or universal game layout. Physical Fn/macro labels
are not established by the available evidence.

Use press edges for one-shot actions; held state plus game timing for continuous
movement. Pause/exit on disconnect, and treat resync as lost transient state.
If input is unavailable, report it and choose an appropriate finite fallback only
when compatible with the user's request. An explicitly manual game should not
silently become autoplay. Stop on a busy lease rather than competing for input.

The [paddle template](assets/paddle.py) demonstrates a finite game, offline preview,
auto/manual input and cleanup. Read/copy it into `projects/<name>/` when relevant;
do not edit packaged resources. An explicit autoplay request can use `--input none`.
Create/run programs through the normal Torque tools and existing authorization.
For a new game, check that an input changes game state and that the changed state
reaches a rendered frame; syntax checks alone do not verify playable controls.

The helper discovers the Bluetooth keyboard by identity and verifies the opened
descriptor. Do not hardcode Bluetooth addresses or event numbers, run the capture
utility, save raw keystrokes, change access/group/pairing settings or add global keyboard bindings.
Project input does not answer agent approvals or control unrelated sessions.
