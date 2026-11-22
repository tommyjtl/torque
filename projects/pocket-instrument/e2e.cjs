// Run with Node and Playwright. Optional CHROMIUM_PATH and SHOT_DIR overrides.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const http = require("node:http");
const { chromium } = require("playwright");

function testTone(file) {
  const rate = 48000,
    samples = rate * 8,
    wave = Buffer.alloc(44 + samples * 2);
  wave.write("RIFF");
  wave.writeUInt32LE(wave.length - 8, 4);
  wave.write("WAVEfmt ", 8);
  wave.writeUInt32LE(16, 16);
  wave.writeUInt16LE(1, 20);
  wave.writeUInt16LE(1, 22);
  wave.writeUInt32LE(rate, 24);
  wave.writeUInt32LE(rate * 2, 28);
  wave.writeUInt16LE(2, 32);
  wave.writeUInt16LE(16, 34);
  wave.write("data", 36);
  wave.writeUInt32LE(samples * 2, 40);
  for (let i = 0; i < samples; i++)
    wave.writeInt16LE(
      Math.round(
        16000 *
          Math.sin((2 * Math.PI * (i < samples / 2 ? 440 : 740) * i) / rate),
      ),
      44 + i * 2,
    );
  fs.writeFileSync(file, wave);
}
async function run() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tq-sampler-"));
  let browser;
  // Serve only the public instrument files from a secure localhost origin.
  const files = {
    "/": "index.html",
    "/panel.css": "panel.css",
    "/instrument.js": "instrument.js",
    "/inspection.js": "inspection.js",
    "/inspect-model.mjs": "inspect-model.mjs",
    ...Object.fromEntries(
      [
        "layout.json",
        "silkscreen.png",
        "lcd.png",
        "vendor/three.core.min.js",
        "vendor/three.module.min.js",
      ].map((file) => ["/assets/inspect/" + file, "assets/inspect/" + file]),
    ),
    "/effects.js": "effects.js",
    "/audio.js": "audio.js",
    "/assets/SpaceGrotesk-Latin.woff2": "assets/SpaceGrotesk-Latin.woff2",
    "/assets/DSEG7Classic-Regular.woff2": "assets/DSEG7Classic-Regular.woff2",
    "/assets/bap-mark.svg": "assets/bap-mark.svg",
    "/assets/bap.svg": "assets/bap.svg",
    "/assets/ringside-poses.png": "assets/ringside-poses.png",
  };
  const server = http.createServer((req, res) => {
    const pathname = req.url.split("?")[0];
    const file = Object.hasOwn(files, pathname) && files[pathname];
    if (!file) {
      res.writeHead(404).end();
      return;
    }
    const types = {
      ".mjs": "text/javascript",
      ".json": "application/json",
      ".css": "text/css",
      ".js": "text/javascript",
      ".woff2": "font/woff2",
      ".svg": "image/svg+xml",
      ".png": "image/png",
      ".html": "text/html",
    };
    res.setHeader("Content-Type", types[path.extname(file)]);
    res.end(fs.readFileSync(path.join(__dirname, file)));
  });
  try {
    const wav = path.join(dir, "mic.wav");
    testTone(wav);
    browser = await chromium.launch({
      channel: process.env.CHROMIUM_PATH ? undefined : "chrome",
      executablePath: process.env.CHROMIUM_PATH || undefined,
      args: [
        "--use-angle=swiftshader",
        "--enable-unsafe-swiftshader",
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
        "--use-file-for-fake-audio-capture=" + wav,
      ],
    });
    const page = await browser.newPage({ permissions: ["microphone"] });
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    // Observe the final Web Audio signal without substituting an audio engine.
    await page.addInitScript(() => {
      const start = AudioBufferSourceNode.prototype.start;
      AudioBufferSourceNode.prototype.start = function (
        when,
        offset,
        duration,
      ) {
        window.lastSlice = {
          offset,
          duration,
          length: this.buffer.length,
          rate: this.buffer.sampleRate,
          basePitch: this.playbackRate.value,
        };
        return start.apply(this, arguments);
      };
      const connect = AudioNode.prototype.connect;
      AudioNode.prototype.connect = function (destination, ...args) {
        if (this instanceof BiquadFilterNode) window.loopFilter = this;
        if (destination instanceof AudioDestinationNode) {
          const probe = this.context.createAnalyser();
          probe.fftSize = 4096;
          connect.call(this, probe);
          window.outputProbe = probe;
        }
        return connect.call(this, destination, ...args);
      };
    });
    await new Promise((resolve, reject) =>
      server.once("error", reject).listen(0, "127.0.0.1", resolve),
    );
    const url = "http://127.0.0.1:" + server.address().port;
    await page.goto(url);
    const press = (k) => page.keyboard.press(k);
    const status = async (s) => {
      try {
        await page.waitForFunction(
          (text) => document.querySelector("#status").textContent === text,
          s,
          { timeout: 6000 },
        );
      } catch (e) {
        throw new Error(
          "Expected " +
            s +
            "; observed " +
            (await page.locator("#status").textContent()),
          { cause: e },
        );
      }
    };
    const select = async (mode, pad) => {
      await press(mode);
      await press(pad);
    };
    const button = (a) => page.locator('[data-action="' + a + '"]');
    const active = async (a) =>
      assert.equal(await button(a).getAttribute("aria-pressed"), "true");
    const pads = page.locator(".pad"),
      panel = page.locator(".board");
    for (const [width, height] of [
      [480, 640],
      [586, 897],
      [640, 480],
      [1280, 800],
      [375, 667],
    ]) {
      await page.setViewportSize({ width, height });
      await page.evaluate(() => document.fonts.ready);
      await page.evaluate(
        () =>
          new Promise((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(resolve)),
          ),
      );
      assert(
        await page.evaluate(
          () =>
            document.fonts.check('16px "Space Grotesk"') &&
            document.fonts.check("26px DSEG") &&
            document.documentElement.scrollWidth <= innerWidth &&
            document.documentElement.scrollHeight <= innerHeight,
        ),
        "Fonts and no-scroll fit at " + width + "x" + height,
      );
      const box = await panel.boundingBox();
      const scale = Math.min(1, width / 480, height / 640);
      assert(
        Math.abs(box.width - 480 * scale) < 1 &&
          Math.abs(box.height - 640 * scale) < 1,
        "Faceplate keeps its 480 × 640 portrait geometry",
      );
      const lcd = await page.locator(".display-panel").boundingBox();
      const rail = await page.locator(".hardware-strip").boundingBox();
      const glass = await page.locator(".lcd").boundingBox();
      const branding = await page
        .locator(".hardware-strip header")
        .boundingBox();
      const logo = await page
        .locator(".hardware-strip .bap-mark")
        .boundingBox();
      assert(
        logo.width <= 40 * scale + 1 &&
          Math.abs(logo.x + logo.width / 2 - rail.x - rail.width / 2) < 1,
        "Compact mark is centered inside the side strip",
      );
      assert(
        Math.abs(
          branding.y + branding.height / 2 - glass.y - glass.height / 2,
        ) < 1,
        "Torque branding follows the horizontal centerline of the LCD",
      );
      const guide = await page.locator("body > #guide").boundingBox();
      if (width === 480 && height === 640) {
        assert.equal(guide, null, "Device-sized view shows only the simulator");
      } else {
        assert(
          guide &&
            (guide.x >= box.x + box.width || guide.y >= box.y + box.height),
          "Web guide sits outside the simulator",
        );
      }
      const lastPad = await pads.last().boundingBox();
      assert(
        lastPad.y + lastPad.height <= box.y + box.height,
        "Last pad fits inside the faceplate",
      );
      const fullName = await page
        .locator(".hardware-strip .instrument-name")
        .boundingBox();
      const firstSwitch = await button("sound")
        .locator(".switch")
        .boundingBox();
      const resetControl = await page.locator("#reset-session").boundingBox();
      assert(
        Math.abs(fullName.y - firstSwitch.y) < 1 &&
          fullName.y >= branding.y + branding.height &&
          fullName.y + fullName.height < resetControl.y,
        "Vertical full name aligns with the first switch row and clears branding and reset",
      );
      const modes = await page.locator(".modes").boundingBox();
      const keys = await page.locator(".keys").boundingBox();
      assert(
        lcd.y + lcd.height <= modes.y + 1 &&
          modes.y + modes.height <= keys.y + 1,
        "LCD stays above dials and pads",
      );
      assert(
        box.x >= 0 &&
          box.y >= 0 &&
          box.x + box.width <= width + 1 &&
          box.y + box.height <= height + 1,
        JSON.stringify(box),
      );
      assert.equal(
        await page.locator("main button").evaluateAll(
          (els) =>
            els.filter((el) => {
              const { x, y, width, height } = el.getBoundingClientRect();
              return !el.contains(
                document.elementFromPoint(x + width / 2, y + height / 2),
              );
            }).length,
        ),
        0,
      );
      if (process.env.SHOT_DIR)
        await page.screenshot({
          path: path.join(process.env.SHOT_DIR, width + "x" + height + ".png"),
        });
    }
    console.log("PASS all controls fit and are hittable at five viewports");
    await page.setViewportSize({ width: 480, height: 640 });
    const signal = () =>
      page.waitForFunction(
        () => {
          if (!window.outputProbe) return false;
          const a = new Float32Array(outputProbe.fftSize);
          outputProbe.getFloatTimeDomainData(a);
          return a.some((n) => Math.abs(n) > 0.012);
        },
        null,
        { polling: 10, timeout: 4000 },
      );
    const silence = () =>
      page.waitForFunction(() => {
        const samples = new Float32Array(outputProbe.fftSize);
        outputProbe.getFloatTimeDomainData(samples);
        return samples.every((value) => Math.abs(value) < 0.0001);
      });
    const checkMeter = (audible) =>
      page.waitForFunction(
        (expected) => {
          const meter = document.querySelector("#strip");
          const aboveFloor =
            Number(meter.getAttribute("aria-valuenow")) >
            Number(meter.getAttribute("aria-valuemin"));
          const filled =
            parseFloat(getComputedStyle(meter, "::before").width) > 0;
          return aboveFloor === expected && filled === expected;
        },
        audible,
        { timeout: 4000 },
      );
    const checkAngle = async (dial, expected) => {
      const degrees = await button(dial)
        .locator("i")
        .evaluate((el) => {
          const m = new DOMMatrix(getComputedStyle(el, "::after").transform);
          return (Math.atan2(m.b, m.a) * 180) / Math.PI;
        });
      assert(
        Math.abs(degrees - expected) < 0.01,
        dial + " pointer angle " + degrees,
      );
    };
    const checkDialLights = async (selected) => {
      for (const dial of ["a", "b"]) {
        const lit = await button(dial).evaluate(
          (el) => getComputedStyle(el, "::before").boxShadow !== "none",
        );
        assert.equal(lit, dial === selected, "Selection LED on dial " + dial);
      }
    };
    await checkDialLights("a");
    await press("KeyO");
    await checkDialLights("b");
    await press("NumpadDecimal");
    await checkDialLights("b");
    await press("KeyO");
    await checkDialLights("a");
    await checkAngle("a", 0);
    await checkAngle("b", 0);
    for (const dial of ["a", "b"]) {
      await button(dial).click();
      for (let i = 0; i < 49; i++) await press("BracketRight");
      await checkAngle(dial, 15);
      await status(dial === "a" ? "PAD 01 · 12 ST" : "VOLUME 100%");
      await press("BracketLeft");
      await checkAngle(dial, 0);
      await status(dial === "a" ? "PAD 01 · 11 ST" : "VOLUME 95%");
      for (let i = 0; i < 49; i++) await press("BracketLeft");
      await checkAngle(dial, -15);
      await status(dial === "a" ? "PAD 01 · -12 ST" : "VOLUME 0%");
      await press("NumpadDecimal");
      await checkAngle(dial, 0);
    }
    const checkParameterMeter = async (label, value, min, max) => {
      const meter = page.locator("#strip");
      assert.equal(await meter.getAttribute("aria-label"), label);
      assert.equal(await meter.getAttribute("aria-valuenow"), String(value));
      assert(
        Math.abs(
          (await meter.evaluate((el) =>
            parseFloat(el.style.getPropertyValue("--fill")),
          )) -
            ((value - min) * 100) / (max - min),
        ) < 0.01,
      );
    };
    await button("a").click();
    await press("BracketRight");
    await checkParameterMeter("Pitch", 1, -12, 12);
    await press("NumpadDecimal");
    await button("b").click();
    await press("BracketRight");
    await checkParameterMeter("Volume", 55, 0, 100);
    await press("NumpadDecimal");
    await press("KeyU");
    await press("BracketRight");
    await checkParameterMeter("Tempo", 97, 60, 240);
    await press("NumpadDecimal");
    await page.waitForFunction(
      () =>
        document.querySelector("#strip").getAttribute("aria-label") ===
        "Output level",
    );
    await checkMeter(false);
    await press("KeyU");
    console.log("PASS parameter meter and automatic return to silent output");
    // Exercise exact encoder cadences without relying on host scheduling delays.
    await button("a").click();
    const encoderTick = (code, time, repeat = false) =>
      page.evaluate(
        ([code, time, repeat]) => {
          const event = new KeyboardEvent("keydown", {
            code,
            repeat,
            bubbles: true,
            cancelable: true,
          });
          Object.defineProperty(event, "timeStamp", { value: time });
          window.dispatchEvent(event);
        },
        [code, time, repeat],
      );
    await encoderTick("BracketRight", 1000);
    await status("PAD 01 · 1 ST");
    await encoderTick("BracketRight", 1080);
    await status("PAD 01 · 3 ST");
    await encoderTick("BracketRight", 1110);
    await status("PAD 01 · 7 ST");
    await encoderTick("BracketRight", 1120, true);
    await status("PAD 01 · 7 ST");
    await encoderTick("BracketLeft", 1130);
    await status("PAD 01 · 6 ST");
    await encoderTick("BracketLeft", 1430);
    await status("PAD 01 · 5 ST");
    await press("NumpadDecimal");
    await encoderTick("BracketLeft", 1440);
    await status("PAD 01 · -1 ST");
    await press("NumpadDecimal");
    await press("KeyO");
    await encoderTick("BracketRight", 1450);
    await status("VOLUME 55%");
    await encoderTick("BracketRight", 1480);
    await status("VOLUME 75%");
    await press("NumpadDecimal");
    await press("KeyU");
    await encoderTick("BracketRight", 1490);
    await status("97 BPM");
    await encoderTick("BracketRight", 1520);
    await status("101 BPM");
    await press("NumpadDecimal");
    await press("KeyU");
    console.log(
      "PASS encoder slow, medium, fast, reversal, repeat suppression and parameter changes",
    );
    console.log(
      "PASS centered startup and reset, endless bidirectional rotation",
    );
    const poseNames = () =>
      page
        .locator(".scene .lit")
        .evaluateAll((els) => els.map((el) => el.dataset.pose).join(" "));
    const idleScene = await poseNames();
    assert.equal(await page.locator(".scene [data-pose]").count(), 8);
    // Exercise the first audio gesture as a mouse click in a fresh document.
    await checkMeter(false);
    await pads.nth(1).click();
    assert.notEqual(
      await poseNames(),
      idleScene,
      "A pad hit changes the comic frame",
    );
    await signal();
    await checkMeter(true);
    await silence();
    await checkMeter(false);
    await button("sound").click();
    await pads.nth(0).click();
    await signal();
    await silence();
    const waitLights = (...expected) =>
      page.waitForFunction(
        (expected) => {
          const lit = [...document.querySelectorAll(".pad")].flatMap(
            (el, index) =>
              getComputedStyle(el, "::before").boxShadow !== "none"
                ? [index + 1]
                : [],
          );
          return lit.join(",") === expected.join(",");
        },
        expected,
        { polling: 10, timeout: 2500 },
      );
    await page.keyboard.down("Digit1");
    await page.keyboard.down("KeyZ");
    await waitLights(1, 13);
    await page.keyboard.up("KeyZ");
    await page.keyboard.up("Digit1");
    await waitLights(1); // The upper octave finishes before the root.
    await waitLights();

    await press("Digit1");
    await page.waitForTimeout(300);
    await press("Digit1");
    await page.waitForFunction(() => audio.voices.size === 2);
    await page.waitForFunction(() => audio.voices.size === 1);
    await waitLights(1); // Ending the earlier voice must not extinguish its retrigger.
    await waitLights();
    await press("Digit1");
    await press("KeyZ");
    await waitLights(1, 13);
    await press("Escape");
    await waitLights();
    console.log(
      "PASS overlapping keyboard notes, independent LED lifetimes, retrigger and stop",
    );
    await button("write").click();
    await pads.nth(1).click();
    await signal();
    assert.equal(await pads.nth(1).getAttribute("aria-pressed"), "true");
    console.log(
      "PASS first pad click, sound selection and stopped step entry each produce audio",
    );
    await page.reload();
    await press("NumpadAdd");
    await active("play");
    await signal();
    await page.waitForFunction(
      (idle) =>
        [...document.querySelectorAll(".scene .lit")]
          .map((el) => el.dataset.pose)
          .join(" ") !== idle,
      idleScene,
    );
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.waitForFunction(
      (idle) =>
        [...document.querySelectorAll(".scene .lit")]
          .map((el) => el.dataset.pose)
          .join(" ") === idle,
      idleScene,
    );
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await checkMeter(true);
    await press("NumpadEnter");
    for (const step of [6, 15, 0]) {
      await page.waitForFunction(
        (index) =>
          document.querySelectorAll(".pad")[index].classList.contains("hit"),
        step,
      );
    }
    await press("NumpadEnter");
    const filterAt = (hz) =>
      page.waitForFunction(
        (expected) =>
          Math.abs(window.loopFilter.frequency.value - expected) < 5,
        hz,
      );
    await press("NumpadSubtract");
    assert.equal(await button("fx").getAttribute("aria-pressed"), "false");
    await page.keyboard.down("NumpadSubtract");
    assert.equal(await page.evaluate(() => audio.effectPad), null);
    await page.keyboard.down("Digit1");
    await status("LOW PASS");
    await filterAt(640);
    await checkMeter(true);
    await pads.nth(1).hover();
    await page.mouse.down();
    await status("HIGH PASS");
    await filterAt(1400);
    await page.mouse.up();
    await status("LOW PASS");
    await filterAt(640);
    await pads.nth(5).hover();
    await page.mouse.down();
    await page.keyboard.up("Digit1");
    await status("FUZZ");
    assert.equal(await pads.nth(5).getAttribute("aria-pressed"), "true");
    await page.mouse.move(1, 1);
    await page.mouse.up();
    await status("FX · HOLD PAD");
    assert.equal(await page.evaluate(() => audio.effectPad), null);
    await active("fx");
    await active("play");
    const fxNames = await page.locator("#fx-map li").allTextContents();
    assert.equal(new Set(fxNames).size, 16);
    for (const [i, name] of fxNames.entries()) {
      await pads.nth(i).hover();
      await page.mouse.down();
      await status(name.toUpperCase());
      assert.equal(await page.evaluate(() => audio.effectPad), i);
      await page.mouse.up();
      await status("FX · HOLD PAD");
    }
    await page.keyboard.up("NumpadSubtract");
    // Pointer-held FX also ends immediately, even while a physical pad is down.
    await button("fx").hover();
    await page.mouse.down();
    await page.keyboard.down("Digit1");
    await status("LOW PASS");
    await page.mouse.move(1, 1);
    await page.mouse.up();
    assert.equal(await button("fx").getAttribute("aria-pressed"), "false");
    assert.equal(await page.evaluate(() => audio.effectPad), null);
    await page.keyboard.up("Digit1");
    // Stop the previous groove to clear queued hits before measuring an empty pattern.
    await press("NumpadAdd");
    await select("KeyY", "Digit2");
    await silence();
    await press("NumpadAdd");
    await active("play");
    await press("NumpadEnter");
    await page.keyboard.down("NumpadSubtract");
    await page.keyboard.down("Digit1");
    await status("LOW PASS");
    // A silent graph can suspend filter processing. Measure its output directly.
    await checkMeter(false);
    assert(
      await page.evaluate(async () => {
        const samples = new Float32Array(outputProbe.fftSize);
        for (let i = 0; i < 12; i++) {
          outputProbe.getFloatTimeDomainData(samples);
          if (samples.some((value) => Math.abs(value) > 0.0001)) return false;
          await new Promise((resolve) => setTimeout(resolve, 15));
        }
        return true;
      }),
      "FX pad does not audition a note",
    );
    await page.keyboard.up("NumpadSubtract");
    assert.equal(await page.evaluate(() => audio.effectPad), null);
    await page.keyboard.up("Digit1");
    assert.equal(await page.locator(".pad.on").count(), 0);
    await press("NumpadEnter");
    console.log(
      "PASS held keyboard and pointer FX, release outside the pad, dry return and loop-only routing",
    );
    await press("NumpadAdd");
    await checkMeter(false);
    await page.waitForFunction(() => {
      const a = new Float32Array(outputProbe.fftSize);
      outputProbe.getFloatTimeDomainData(a);
      return a.every((n) => Math.abs(n) < 0.0001);
    });
    console.log("PASS transport advances and the factory pattern produces PCM");
    await select("KeyY", "Digit2");
    assert.equal(await page.locator("#patternNo").innerText(), "02");
    await select("KeyT", "Digit1");
    await press("Digit3");
    await signal();
    await press("NumpadEnter");
    const codes = [
      "Digit1",
      "Digit2",
      "NumpadDivide",
      "NumpadMultiply",
      "KeyQ",
      "Numpad7",
      "Numpad8",
      "Numpad9",
      "KeyA",
      "Numpad4",
      "Numpad5",
      "Numpad6",
      "KeyZ",
      "Numpad1",
      "Numpad2",
      "Numpad3",
    ];
    for (const [i, key] of codes.entries()) {
      await press(key);
      assert.equal(await pads.nth(i).getAttribute("aria-pressed"), "true");
      assert.equal(await page.locator(".pad.on").count(), i + 1);
    }
    await press("Numpad3");
    assert.equal(await pads.nth(15).getAttribute("aria-pressed"), "false");
    await select("KeyY", "Digit1");
    assert.equal(await page.locator(".pad.on").count(), 0);
    await select("KeyY", "Digit2");
    assert.equal(await page.locator(".pad.on").count(), 15);
    await press("NumpadEnter");
    await press("BracketRight");
    await status("PAD 03 · 1 ST");
    await press("KeyO");
    await active("b");
    await press("BracketLeft");
    await status("VOLUME 45%");
    await press("NumpadDecimal");
    await status("VOLUME 50%");
    await active("b");
    await press("KeyO");
    await press("BracketRight");
    await status("PAD 03 · 2 ST");
    await press("NumpadDecimal");
    await status("PAD 03 · 0 ST");
    await active("a");
    await press("KeyO");
    await press("KeyU");
    await active("a");
    await press("BracketRight");
    assert.equal(await page.locator("#tempo").innerText(), "097");
    await checkAngle("a", 15);
    await checkAngle("b", 0);
    await press("KeyO");
    await press("BracketRight");
    await status("VOLUME 55%");
    await checkAngle("b", 15);
    await checkAngle("a", 15);
    assert.equal(await page.locator("#tempo").innerText(), "097");
    await press("NumpadDecimal");
    await checkAngle("b", 0);
    await checkAngle("a", 15);
    await press("KeyO");
    await press("NumpadDecimal");
    await status("96 BPM");
    await checkAngle("a", 0);
    await checkAngle("b", 0);
    await press("KeyU");
    await page.keyboard.down("NumpadSubtract");
    await active("fx");
    await page.keyboard.up("NumpadSubtract");
    console.log(
      "PASS 16 physical pad codes, pattern isolation, step removal, A/B, tempo and FX",
    );
    await press("KeyI");
    const checkRecordSlots = async (used) => {
      await status("REC → SLOT");
      assert.equal(
        await page.locator("#bank").innerText(),
        used.length + "/16 RECORDED",
      );
      const ledStyle = (el) => {
        const lamp = getComputedStyle(el, "::before");
        return [lamp.backgroundImage, lamp.boxShadow, lamp.borderColor];
      };
      const recordLed = await button("record").evaluate(ledStyle);
      assert.notEqual(recordLed[1], "none");
      for (const pad of await pads.all())
        assert.deepEqual(await pad.evaluate(ledStyle), recordLed);
      const marked = await pads.evaluateAll((els) =>
        els.flatMap((el, i) =>
          getComputedStyle(el.querySelector("strong")).color ===
          "rgb(255, 145, 71)"
            ? [i + 1]
            : [],
        ),
      );
      assert.deepEqual(marked, used);
    };
    await checkRecordSlots([]);
    await press("Digit2");
    await status("RECORDING");
    assert.equal(await page.locator(".pad.capturing").count(), 1);
    assert.equal(
      await pads.nth(1).getAttribute("aria-label"),
      "Pad 2, recording",
    );
    const blinkPhases = new Set();
    for (let seconds = 8; seconds >= 1; seconds--) {
      await page.waitForFunction(
        (text) => document.querySelector("#soundName").textContent === text,
        seconds + "s left",
        { timeout: 1800 },
      );
      if (seconds >= 2) {
        await page.waitForTimeout(180);
        blinkPhases.add(
          await pads
            .nth(1)
            .evaluate((el) => getComputedStyle(el, "::before").opacity),
        );
      }
    }
    await status("SAMPLE SAVED");
    assert.deepEqual(blinkPhases, new Set(["1", "0.12"]));
    assert.equal(await page.locator(".pad.capturing").count(), 0);

    assert.equal(await page.locator("#soundName").innerText(), "Sample 02");
    const checkSlices = async (minSeconds, maxSeconds) => {
      let end = 0;
      for (const key of codes) {
        await press(key);
        const slice = await page.evaluate(() => window.lastSlice);
        assert(
          slice.length / slice.rate >= minSeconds &&
            slice.length / slice.rate <= maxSeconds,
        );
        assert.equal(slice.basePitch, 1);
        assert(
          Math.abs(slice.offset - end) < 0.5 / slice.rate,
          "consecutive slices",
        );
        assert(
          Math.abs(slice.duration * slice.rate - slice.length / 16) < 1,
          "equal to within one sample",
        );
        end = slice.offset + slice.duration;
        await press("Escape");
      }
      await silence();
    };
    await checkSlices(7.5, 8);
    await press("Digit1");
    await signal();
    const hearPitch = (hz) =>
      page.waitForFunction(
        (expected) => {
          const a = new Float32Array(outputProbe.frequencyBinCount);
          outputProbe.getFloatFrequencyData(a);
          const peak =
            (a.indexOf(Math.max(...a)) * outputProbe.context.sampleRate) /
            outputProbe.fftSize;
          return Math.abs(peak - expected) < 15 && Math.max(...a) > -50;
        },
        hz,
        { polling: 15, timeout: 3000 },
      );
    await hearPitch(440);
    // Tune just pad 1 of the recorded slot up a fifth.
    for (let i = 0; i < 7; i++) {
      if (i) await page.waitForTimeout(130);
      await press("BracketRight");
    }
    await status("PAD 01 · 7 ST");
    await press("Escape");
    await press("Digit1");
    await hearPitch(659.26);
    // Silence the root note so it cannot mask the octave in the peak detector.
    await press("Escape");
    // Audition slice 13, write it on step one of an empty pattern,
    // and wait for the live voice to finish before listening to the sequencer.
    await select("KeyY", "Digit3");
    await press("KeyZ");
    await hearPitch(740);
    await press("NumpadEnter");
    await press("Digit1");
    await page.waitForTimeout(1050);
    await press("NumpadAdd");
    await hearPitch(740);
    await press("NumpadAdd");
    await press("NumpadEnter");
    console.log(
      "PASS synthetic microphone → slot 02 → 440 Hz first slice → 740 Hz late slice from a written step",
    );
    // Sequence tuned pad 1 and verify resetting pad 13 leaves pad 1 alone.
    await press("NumpadDecimal");
    await status("PAD 13 · 0 ST");
    await select("KeyY", "Digit4");
    await press("Digit1");
    await hearPitch(659.26);
    await press("Escape");
    await press("NumpadEnter");
    await press("Digit1");
    await press("NumpadAdd");
    await hearPitch(659.26);
    await press("NumpadAdd");
    await press("NumpadEnter");
    await press("NumpadDecimal");
    await press("Digit1");
    await hearPitch(440);
    console.log(
      "PASS per-pad pitch, independent reset and tuned sequencer playback",
    );
    await button("record").click();
    await checkRecordSlots([2]);
    await pads.nth(15).click();
    await status("RECORDING");
    await page.waitForTimeout(500);
    await press("KeyI");
    await status("SAMPLE SAVED");
    await checkSlices(0.2, 1);
    await press("KeyI");
    await checkRecordSlots([2, 16]);
    if (process.env.SHOT_DIR)
      await page.screenshot({
        path: path.join(process.env.SHOT_DIR, "record-slot-picker.png"),
      });
    await press("KeyI");
    await select("KeyT", "Digit2");
    // A rejected replacement must release the armed state and preserve the previous take.
    await page.evaluate(() => {
      navigator.mediaDevices.getUserMedia = async () => {
        throw new DOMException("denied", "NotAllowedError");
      };
    });
    await select("KeyI", "Digit2");
    await status("MIC UNAVAILABLE");
    assert.equal(await page.locator("#soundName").innerText(), "Sample 02");
    await press("KeyI");
    await checkRecordSlots([2, 16]);
    await press("KeyI");
    console.log(
      "PASS recorded-slot LEDs and counts for empty, melodic and drum slots, including failed replacement",
    );
    await page.setViewportSize({ width: 800, height: 800 });
    await page.locator("#guide").click();
    assert(await page.locator("#help").isVisible());
    await page.getByRole("button", { name: "Close guide" }).click();
    await button("sound").click();
    await pads.nth(8).click();
    assert.equal(await page.locator("#soundName").innerText(), "Break kit");
    await button("play").click();
    await active("play");
    await press("Escape");
    assert.equal(await button("play").getAttribute("aria-pressed"), "false");
    for (const trigger of ["button", "keypad"]) {
      await press("KeyU");
      await press("BracketRight");
      assert.equal(await page.locator("#tempo").innerText(), "097");
      await Promise.all([
        page.waitForEvent("load"),
        trigger === "button"
          ? page
              .getByRole("button", { name: "Reset sampler", exact: true })
              .click()
          : press("Numpad0"),
      ]);
      await status("READY");
      assert.equal(await page.locator("#tempo").innerText(), "096");
      assert.equal(await page.locator("#patternNo").innerText(), "01");
      assert.equal(await page.locator("#soundName").innerText(), "Break kit");
      await press("KeyI");
      await checkRecordSlots([]);
      await press("KeyI");
    }
    console.log("PASS one-click and keypad 0 immediate reset");
    // Render the same pulsed two-tone input through every effect. Compare
    // the actual PCM with dry playback and with each earlier pad's output.
    const distinctEffects = await page.evaluate(async () => {
      const rate = 22050,
        length = rate;
      const renders = [];
      for (const effect of [null, ...LOOP_EFFECTS]) {
        const ctx = new OfflineAudioContext(2, length, rate);
        const buffer = ctx.createBuffer(1, length, rate);
        const data = buffer.getChannelData(0);
        for (let i = 0; i < length; i++) {
          const t = i / rate,
            beat = t % 0.22;
          data[i] =
            Math.exp(-beat * 18) *
            (0.25 * Math.sin(2 * Math.PI * 220 * t) +
              0.15 * Math.sin(2 * Math.PI * 2200 * t));
        }
        const input = ctx.createBufferSource();
        input.buffer = buffer;
        if (effect) {
          const branch = makeLoopEffect(ctx, effect, 120);
          input.connect(branch.input);
          branch.output.connect(ctx.destination);
        } else input.connect(ctx.destination);
        input.start();
        const output = (await ctx.startRendering()).getChannelData(0);
        if (
          !output.every(Number.isFinite) ||
          !output.some((x) => Math.abs(x) > 0.015)
        )
          return false;
        for (const previous of renders) {
          let sum = 0;
          for (let i = 0; i < length; i++)
            sum += (output[i] - previous[i]) ** 2;
          if (Math.sqrt(sum / length) < 0.002) return false;
        }
        renders.push(output);
      }
      return true;
    });
    assert(distinctEffects, "Each pad produces distinct, finite audio");
    console.log("PASS all 16 FX pad gestures and distinct audio renders");
    // 3D is the physical P binding (M5); the inspector shares the current session.
    await press("KeyI");
    await status("REC → SLOT");
    const inspection = page.locator("#inspection");
    const orbitCanvas = inspection.locator("canvas");
    const modelBytesRequested = () =>
      page.evaluate(() =>
        performance
          .getEntriesByType("resource")
          .some((r) => r.name.includes("three.core.min.js")),
      );
    assert.equal(await modelBytesRequested(), false);
    await page.setViewportSize({ width: 900, height: 760 });
    await page.keyboard.down("KeyP");
    await inspection.locator('canvas[data-pose="orbit"]').waitFor();
    await page.keyboard.up("KeyP");
    assert(await modelBytesRequested());
    assert.equal(await inspection.locator("#inspect-close").isVisible(), false);
    const frameBox = await page.locator(".frame").boundingBox();
    const viewport = await orbitCanvas.boundingBox();
    for (const dim of ["x", "y", "width", "height"])
      assert(Math.abs(frameBox[dim] - viewport[dim]) < 1);
    await page.evaluate(() => {
      window.boardClicks = 0;
      document
        .querySelector(".board")
        .addEventListener("click", () => window.boardClicks++);
    });
    await orbitCanvas.click({ position: { x: 100, y: 150 } });
    const firstView = await orbitCanvas.screenshot();
    await page.mouse.move(viewport.x + 180, viewport.y + 240);
    await page.mouse.down();
    await page.mouse.move(viewport.x + 30, viewport.y + 260, { steps: 8 });
    await page.mouse.up();
    const rotatedView = await orbitCanvas.screenshot();
    assert(
      !firstView.equals(rotatedView),
      "Orbit drag changes the rendered device",
    );
    assert.equal(await page.evaluate(() => window.boardClicks), 0);
    await press("KeyP");
    await inspection.waitFor({ state: "hidden" });
    assert.equal(
      await page.locator(".frame").evaluate((el) => el.inert),
      false,
    );
    await page.setViewportSize({ width: 375, height: 667 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await press("KeyP");
    await inspection.locator('canvas[data-pose="orbit"]').waitFor();
    const small = await orbitCanvas.boundingBox();
    assert.equal(small.width, 375);
    assert.equal(small.height, 500);
    await press("Escape");
    await inspection.waitFor({ state: "hidden" });
    assert(
      (await button("record").getAttribute("aria-pressed")) === "true",
      "Sampler state survives inspection",
    );
    console.log(
      "PASS lazy WebGL preview, 3:4 viewport, orbit drag, click isolation, M5 and Escape return, reduced motion",
    );
    assert.deepEqual(errors, []);
    console.log(
      "PASS microphone refusal, pointer controls, stop, guide and zero uncaught page errors",
    );
    console.log("Chromium " + browser.version());
  } finally {
    try {
      await browser?.close();
    } finally {
      server.close();
      fs.rmSync(dir, { recursive: true, force: true });
    }
  }
}
run().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
