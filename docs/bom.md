# Bill of materials

Hardware inventory and planned additions as of October 25, 2026.
Prices are in USD, using the item prices shown in the supplied order/product
screenshots before cashback or other discounts, except for the M-1 retail
reference noted below. Tax, shipping and recycling fees are excluded; these are
recorded prices, not live quotes.

## Required hardware

The Arduino UNO Q is required to run Torque.

| Item | Purpose | Quantity | Unit price | Product link |
|---|---|---|---|---|
| Arduino UNO Q 4GB (`ABX00173`) | Runs Torque on Linux and controls board hardware through the MCU. | 1 | $79.00 | [Arduino](https://store-usa.arduino.cc/products/uno-q-4gb) |

## Additional hardware

Accessories and expansion hardware for the current and planned build.

| Item | Purpose | Status | Quantity | Unit price | Product link |
|---|---|---|---|---|---|
| Anker Nano Power Bank, 5,000mAh, 22.5W, built-in USB-C connector | Portable power for the board. | In use | 1 | $23.99 | [Anker](https://www.anker.com/products/a1653-usb-c-portable-charger-5000mah) |
| Arduino UNO Media Carrier (`ASX00083`) | Carrier for display, camera and audio connections. | In use | 1 | $19.99 | [Arduino](https://store-usa.arduino.cc/products/uno-media-carrier) |
| teenage engineering M-1 | Voice input using the microphone only. | In use | 1 | $79.00 | [teenage engineering](https://teenage.engineering/products/op-z/m-1) |
| Waveshare 2.8inch DSI LCD, 480 × 640, IPS capacitive touch | Compact display for the Linux side through the Media Carrier. | Planned | 1 | $56.99 | [Waveshare](https://www.waveshare.com/2.8inch-dsi-lcd.htm) |

The M-1 is already owned. Its price is the manufacturer's
[$79 retail reference for the complete headset](https://teenage.engineering/store/m-1/),
checked October 25, 2026; the amount originally paid was not supplied. Only its
microphone is used in this build.

The display price is from the supplied Amazon listing; the link is the original
Waveshare product page, whose price may differ. The display is not yet purchased
or tested with the UNO Q. See the [display investigation](journal/2026-10-24-compact-dsi-display.md)
for integration status.

## Microphone alternative under consideration

For a microphone mounted on Torque itself, this is a possible replacement for
the M-1 microphone. It is a candidate, not a selected purchase.
The price below was checked October 25, 2026.

The Media Carrier's microphone input is part of its CTIA-standard headset jack;
audio capture belongs to the UNO Q's Linux side. See the
[Arduino Media Carrier manual](https://github.com/arduino/docs-content/blob/main/content/hardware/uno/carriers/uno-media-carrier/tutorials/01.user-manual/content.md).
This candidate has not been tested with this build.

| Candidate | Listed price | Mounting and connection |
|---|---|---|
| [Saramonic SmartMic5S](https://saramonicusa.com/mini-shotgun-mic-w-3-5mm-trrs/) | $29.00 | Compact directional mic with a swivel, shock mount and 3.5mm TRRS plug. Leading candidate for a small device-mounted mic; choose the **5S/TRRS** version. |
