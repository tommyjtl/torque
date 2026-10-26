# Compact Linux display for Arduino UNO Q

**Date:** 2026-10-24, America/Los_Angeles

**Status:** Try the Waveshare **2.8inch DSI LCD** first. Compatibility with our
UNO Q is unestablished; this is an experimental integration. Purchase has not
been confirmed, and no display has been connected or tested.

**Source:** User-provided investigation handoff. External product/documentation
claims below are retained from that handoff, not independently revalidated by
this journal entry. The board kernel was checked live through SSH as noted below.

## Goal and selection

Add a compact screen for the Linux shell and terminal applications, preferably
without a full desktop environment. Display output belongs to the UNO Q's
Qualcomm/Linux side; this investigation is separate from the STM32 matrix
controller and its firmware.

The handoff identifies Arduino's documented Media Carrier presets for Waveshare
5-inch, 8-inch and 10.1-inch DSI Touch A panels. Those are too large for the
intended device, so the selected smaller candidate is:

| Item | Selected candidate |
|---|---|
| Model | Waveshare `2.8inch DSI LCD` |
| Resolution | 480 × 640 |
| Panel | IPS, capacitive touch, optical bonding |
| Connection | MIPI-DSI through the UNO Media Carrier |
| Compatibility | Experimental; not established on our UNO Q |
| Purchase | Not confirmed |

The Amazon candidate in the handoff was the **$56.99 listing explicitly labelled
“DSI Interface.”** That is the quoted listing price at the time of the handoff,
not a newly checked price. Similar-looking **DPI/DPI666** products use a different
interface and are not the selected product. No exact Amazon URL was supplied.

## Compatibility investigation

Debian can host the terminal application, but a usable screen also needs kernel
support for the panel and its connection to the Qualcomm display controller.
The integration may require:

- A panel driver and panel-specific initialization commands.
- Correct display timings, DSI lane configuration and device-tree description.
- Backlight control, touch support and the appropriate device-tree overlay.
- A verified carrier pinout, power arrangement and display ribbon.

Raspberry Pi support is useful groundwork. Its configuration cannot be assumed
to transfer unchanged to UNO Q. The handoff found no demonstrated UNO Q
integration for this exact 2.8-inch panel; that does not establish incompatibility.

### Community reference

The [community UNO Q DSI display project](https://github.com/dcuartielles/uno_q_dsi_displays)
reports working Waveshare **4.3-inch/5-inch, 800 × 480 DSI panels**, including
multitouch, using the Media Carrier. The handoff describes driver patches,
overlays, installation/reversal scripts and boot-recovery workarounds.

That project reports Debian 13 and kernel 7.0.0. It is a reference for the
integration approach, not confirmation that its patches support the 2.8-inch
candidate.

### Kernel observation correction

The incoming handoff used **6.16.7** as its last-observed board kernel. A fresh,
read-only SSH check during this entry returned:

```text
$ uname -r
7.0.0-g122c2c22d838
```

Use **7.0.0-g122c2c22d838** as the current observation for `tommy-uno-q` when
comparing driver/BSP requirements. The version series aligns with the community
project's report, but that alone does not prove matching patches, kernel
configuration or panel compatibility. Recheck the running build before preparing
an actual driver change.

## Alternatives considered

| Option | Assessment from the handoff |
|---|---|
| USB-C to HDMI | Easier monitor integration, with additional hub/cable bulk |
| DSI-to-HDMI bridge | Possible, but adds a converter board and integration work |
| SPI TFT | Compact; additional integration is needed to show the Linux shell |
| Officially documented 5-inch DSI panel | Simplest documented path among these candidates, but too large |

## Next steps and tracking

- [ ] Identify the exact 2.8-inch panel controllers and inspect its published driver.
- [ ] Compare its requirements with our running kernel/BSP and the community implementation.
- [ ] Verify pinout, power requirements and the correct display ribbon.
- [ ] Prepare reversible driver/device-tree changes and a recovery procedure.
- [ ] Test image output, backlight, touch and repeated cold boots.
- [ ] Configure a full-screen terminal or text console.

The selected direction is an investigation candidate, not a validated bill of
materials or installation recipe. This entry made no driver, device-tree,
firmware, service or boot-configuration changes.

## References

- [UNO Media Carrier — Micro Center](https://www.microcenter.com/product/709918/arduino-uno-media-carrier#tab-reviews-bm)
- [UNO Media Carrier — Arduino Store](https://store-usa.arduino.cc/products/uno-media-carrier)
- [Official Arduino MIPI-DSI display configuration](https://docs.arduino.cc/software/app-lab/configure/display/)
- [Waveshare 2.8-inch DSI LCD — product page](https://www.waveshare.com/2.8inch-dsi-lcd.htm)
- [Waveshare 2.8-inch DSI LCD — technical wiki](https://www.waveshare.com/wiki/2.8inch_DSI_LCD)
- [Community UNO Q DSI display integration](https://github.com/dcuartielles/uno_q_dsi_displays)
- [ST B-LCDAD-HDMI1 DSI-to-HDMI adapter — alternative explored](https://www.st.com/en/evaluation-tools/b-lcdad-hdmi1.html)
