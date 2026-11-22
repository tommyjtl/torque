# B.A.P. for the UNO Q desktop

Open **B.A.P.** on the Arduino desktop. The factory session starts idle on Break kit, pattern 1, at 96 BPM. Keypad **+** starts the loop. **Decimal (.) quits to the desktop**. In 2D, Escape or the small **exit** target at the top of the right strip also closes the native app. In 3D, Escape returns to the playable faceplate. Closing discards the current session. Keypad **0** restores factory state. The pointer is hidden inside the instrument.

The portrait controls follow the [sampler map](../../../docs/design-spec/2026-11-21-pocket-sampler.md#k0-max-input-contract). Press the encoder (O) to switch dials. Turn it in either direction (bracket events). Each detent rotates the selected shaft 15° through successive revolutions. Accelerated turns change pitch, volume or tempo more quickly. The values stay within their musical ranges, and reversing the physical turn immediately steps away from a limit. Both shafts begin upright. The browser preview uses decimal to reset a parameter; the installed UNO Q build uses it to quit.

## 3D inspection

Tap **P** (or M5 mapped to send P) to ease into the tabletop view. Drag with one finger or the mouse to orbit around the sampler; the wheel zooms, the arrow keys orbit, and Home brings the face into view. P or Escape returns to 2D. The 3D model does not accept panel clicks. Keypad musical controls and the Mojo audio callback continue in the same session.

The native GLES renderer uses the web enclosure's geometry and printed artwork baked on the Mac. It shares the live SDL panel texture for the LCD, updates the LED and dial meshes, and uses a narrow camera depth range to separate the printed surfaces. Angled textures use mipmaps. On the validation board the FD702 driver provided 4× multisampling and 8× anisotropic filtering. The capture of pattern 02 before inspection matched the capture after the orbit and return, pixel for pixel. Validation used synthetic keyboard and pointer events on the real desktop; physical finger-drag feel is unmeasured.

[Placed view](evidence/uno-q-3d.png) · [Side profile](evidence/uno-q-3d-side.png) · [Rear artwork and stand](evidence/uno-q-3d-back.png)

## Runtime

The native program links Mojo DSP and a C/SDL2 desktop adapter into one Linux AArch64 executable. The audio callback runs the Mojo polyphonic mixer, fractional sample playback, per-pad tuning, 16-lane pattern sequencer, and 16 performance effects. Tempo is clocked in PCM frames at 48 kHz. SDL handles window events, touch, graphics, microphone capture and audio-device access. The framebuffer uses rasterized artwork from the portrait web design, with runtime comic frames, meter, state labels, independent LEDs and encoder positions. The factory PCM bank is baked from the preview's original sound generator.

Capture explicitly opens the enumerated **Built-in Audio Headset microphone**. Playback explicitly opens **Built-in Audio Lineout playback**. A missing endpoint is reported. No system mixer or routing defaults are written. Press top-row × (I), choose a slot, record up to eight seconds and divide the take into sixteen slices. Early stop uses the captured length. A new factory session and its 40-second user recording budget live in process memory. The current visual and audio implementations are native approximations of the web reference, including a 24-voice pool.

## Build

The tested cross-build host is macOS on Apple silicon with Mojo 1.2.0, Zig 0.17.1, SDL2 development headers (`sdl2-config`), Node.js, Google Chrome and ImageMagick. Point `MOJO` and `ZIG` at the installed executables. Set `SDL2_INCLUDE` if the headers are outside the directory reported by `sdl2-config`.

Start at the repository root. Replace the example hostname with your UNO Q's SSH hostname. The linker uses copies of the board's SDL2 and GLES libraries; the app uses the installed libraries on the board.

```sh
export BOARD_HOST=your-board.local
export MOJO=/absolute/path/to/mojo
export ZIG=/absolute/path/to/zig
cd projects/pocket-instrument
npm install --no-package-lock
cd native
bap_libdir=$(mktemp -d)
scp "arduino@$BOARD_HOST:/usr/lib/aarch64-linux-gnu/libSDL2-2.0.so.0" "$bap_libdir/"
scp "arduino@$BOARD_HOST:/usr/lib/aarch64-linux-gnu/libGLESv2.so.2" "$bap_libdir/"
node prepare.cjs
node bake-model.cjs
SDL2_TARGET_LIB="$bap_libdir/libSDL2-2.0.so.0" GLES_TARGET_LIB="$bap_libdir/libGLESv2.so.2" ./build.sh
```

The resource bake reads the local reference files and writes to the ignored build directory. Repeat it after a change to the skin, font, default sounds or layout. The build emits `build/bap-linux-arm64.tgz` with runtime resources, desktop entry and SHA-256 manifest.

## Installation and evidence

To install your build, copy the archive from the Mac while still in the `native` directory:

```sh
scp build/bap-linux-arm64.tgz "arduino@$BOARD_HOST:bap-linux-arm64.tgz"
```

Run the following on the board as `arduino`. The supplied desktop entry uses paths under `/home/arduino`. The test runs without opening the microphone, speaker or screen.

```sh
(
  set -eu
  app_dir="$HOME/torque/projects/bap-native"
  mkdir -p "$app_dir/releases" "$HOME/Desktop" "$HOME/.local/share/applications"
  release=$(mktemp -d "$app_dir/releases/bap.XXXXXXXX")
  cd "$release"
  tar -xzf "$HOME/bap-linux-arm64.tgz"
  sha256sum -c SHA256SUMS
  ./bap --self-test
  desktop-file-validate BAP.desktop
  ln -s "$release" "$release.next"
  mv -Tf "$release.next" "$app_dir/current"
  install -m 755 BAP.desktop "$HOME/Desktop/BAP.desktop"
  install -m 644 BAP.desktop "$HOME/.local/share/applications/BAP.desktop"
)
```

Double-click **B.A.P.** on the desktop. If XFCE asks whether to trust the launcher, review its executable path and allow it to launch. An open B.A.P. session picks up the new release on its next launch.

The validation board has `~/Desktop/BAP.desktop` and a matching applications-menu entry. The desktop file is executable and the XFCE trust checksum was verified. The stable user-owned install path is `~/torque/projects/bap-native/current`. The November 21 validation used release **62cb50b23f37**. Turning an encoder shows its parameter range on the IN–OUT strip for 1.2 seconds, then the strip resumes showing mixed output level. Its skin uses 60-pixel push buttons on the 480×640 faceplate. Installation used the arduino account on the Linux side. Firmware, boot selection and service configuration were preserved.

The following finite checks can be run from a native release directory. The I/O probe requires the sampler to be closed. It opens Line Out silently and discards a short microphone buffer.

```sh
./bap --self-test
./bap --verify-io
```

- The board passed native polyphony, all sixteen synthetic capture slices and distinct output for sixteen effects. The final test also turned both encoders past their parameter limits over four revolutions of travel, reversed direction and reset their position.
- The final native mixer test averaged 0.068 ms and peaked at 0.196 ms of computation per 256 frames, against a 5.33 ms block period. This is an offline DSP workload. Physical pad-to-speaker latency and USB versus Bluetooth timing still need a synchronized external measurement.
- The I/O probe opened both named endpoints at 48 kHz and received 3,584 microphone frames in its 700 ms startup trial. The first desktop run exercised recording, saving, slot occupancy, transport, held FX, pattern writing, reset and exit with targeted X11 input. These checks establish a working capture path. Acoustic microphone placement, audible quality and physical touch/keypad feel still need a person's observation.
- The final installed desktop entry launched at 480×640. A targeted keypad decimal event closed the process. XFixes reported a transparent pointer over the sampler and a visible pointer after exit. The desktop entry was launched again into a fresh idle session.

[Final native window capture](evidence/uno-q.png)
