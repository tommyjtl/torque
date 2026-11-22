// Bake only printed surfaces. The switches, knobs, casework and rear hardware are meshes.
const path = require("node:path");
const fs = require("node:fs");
const { pathToFileURL } = require("node:url");
const { chromium } = require("playwright");
(async () => {
  const browser = await chromium.launch({ channel: "chrome" });
  try {
    const page = await browser.newPage({
      viewport: { width: 480, height: 640 },
      deviceScaleFactor: 2,
    });
    await page.goto(pathToFileURL(path.join(__dirname, "index.html")).href);
    await page.evaluate(() => document.fonts.ready);
    const layout = await page.evaluate(() => {
      const bounds = (el) => {
        const { x, y, width, height } = el.getBoundingClientRect();
        return [x, y, width, height].map((v) => Math.round(v * 10) / 10);
      };
      const buttons = [...document.querySelectorAll(".controls button")];
      return {
        lcd: bounds(document.querySelector(".lcd")),
        screen: bounds(document.querySelector(".display-panel")),
        texts: ["#bank", "#soundName", "#status", "#tempo", "#patternNo"].map(
          (selector) => {
            const el = document.querySelector(selector),
              cs = getComputedStyle(el);
            return {
              selector,
              rect: bounds(el),
              font: cs.fontWeight + " " + cs.fontSize + " " + cs.fontFamily,
            };
          },
        ),
        poses: [...document.querySelectorAll(".scene i")].map(bounds),
        meter: bounds(document.querySelector("#strip")),
        controls: buttons.map((el) => ({
          key: el.dataset.action || el.getAttribute("aria-label"),
          rect: bounds(el.querySelector("i")),
        })),
      };
    });
    const out = path.join(__dirname, "assets/inspect");
    fs.writeFileSync(
      path.join(out, "layout.json"),
      JSON.stringify(layout, null, 2) + "\n",
    );
    await page.addStyleTag({
      content:
        "#bank,#soundName,#status,#tempo,#patternNo,.scene i{visibility:hidden}",
    });
    await page.locator(".lcd").screenshot({ path: path.join(out, "lcd.png") });
    await page.addStyleTag({
      content:
        ".controls button>i,.controls button::before,.lcd,.pins{visibility:hidden!important} .display-panel {background:transparent} .board{border-radius:14px;overflow:hidden}body{background:transparent}",
    });
    await page
      .locator(".board")
      .screenshot({
        path: path.join(out, "silkscreen.png"),
        omitBackground: true,
      });
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
