# UNO Q hardware map

Identify the board with the NUL-separated values in
`/sys/firmware/devicetree/base/compatible`: `arduino,imola` identifies UNO Q;
`arduino,monza` identifies VENTUNO Q, which this starter does not target.

| Component | Owner | Interface |
|---|---|---|
| User RGB LED 1 | Linux MPU | `/sys/class/leds/{red,green,blue}:user/brightness` |
| RGB LED 2 | Linux MPU | System-status channels `red:panic`, `green:wlan`, `blue:bt`; leave their triggers alone for ordinary demos |
| RGB LEDs 3 and 4 | STM32 MCU | Base controller `board.rgb(3/4).set(...)`; active-low wiring hidden by the driver |
| Blue LED matrix | STM32 MCU | `Arduino_LED_Matrix`, 8 rows x 13 columns = 104 pixels |
| Linux-to-MCU calls | Both | Python `Bridge.call` and C++ `Bridge.provide`, through `arduino-router` |
| Reported MCU state | STM32 + Linux | Installed Torque uses `torque device snapshot/health` or public SDK observation; native `unoq-control` is reserved for developer diagnostics. GPIO readback is distinct from requested values. |

The Linux LED example snapshots brightness and triggers, runs a finite demo,
and restores that state. MCU Python demos reuse resident base-controller
firmware. Deploying that firmware replaces the running sketch; pattern edits
do not. No external wiring, sensor, camera, or local AI model is required.
The cloud model runs at Modular; fx runs on Linux.

For sketches, the verified FQBN is `arduino:zephyr:unoq`. The included profile
pins Arduino Zephyr core 1.0.0, which was installed on the validation board.
Check the local core version before choosing a newer profile deliberately.

Sources:
- [UNO Q user manual](https://docs.arduino.cc/tutorials/uno-q/user-manual/)
- [UNO Q hardware](https://docs.arduino.cc/hardware/uno-q/)
- [Bridge API](https://docs.arduino.cc/software/app-lab/bridge/bridge-api)
