// Bake the approved skin, geometry and original factory waveforms into native resources.
// The board reads these assets directly; no browser, server or JS runtime is needed.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { execFileSync } = require("node:child_process");
const { chromium } = require("playwright");
const { pathToFileURL } = require("node:url");
const project = path.dirname(__dirname),
  out = path.join(__dirname, "build");
fs.mkdirSync(out, { recursive: true });
const write = (name, bytes) => fs.writeFileSync(path.join(out, name), bytes);
async function prepare() {
  const browser = await chromium.launch({ channel: "chrome" });
  try {
    const page = await browser.newPage({
      viewport: { width: 480, height: 640 },
      deviceScaleFactor: 1,
    });
    await page.goto(pathToFileURL(path.join(project, "index.html")).href);
    await page.evaluate(() => document.fonts.ready);
    const layout = await page.evaluate(() => {
      const rect = (el) => {
        const r = el.getBoundingClientRect();
        return [r.x, r.y, r.width, r.height].map(Math.round);
      };
      const buttons = [
        ...document.querySelectorAll(".pad"),
        ...[
          "sound",
          "pattern",
          "bpm",
          "a",
          "b",
          "record",
          "fx",
          "play",
          "write",
        ].map((a) => document.querySelector('[data-action="' + a + '"]')),
        document.querySelector("#reset-session"),
      ];
      return {
        controls: buttons.map(rect),
        switches: buttons.map((el) => rect(el.querySelector("i") || el)),
        labels: buttons.map((el) => rect(el.querySelector(".legend") || el)),
        fields: [
          ".scene",
          "#bank",
          "#soundName",
          "#status",
          "#tempo",
          "#patternNo",
          "#strip",
        ].map((k) => rect(document.querySelector(k))),
      };
    });
    const rows = (a) => a.map((r) => "{" + r.join(",") + "}").join(",\n");
    let header = Object.entries(layout)
      .map(
        ([name, v]) =>
          "static const SDL_Rect " + name + "[]={" + rows(v) + "};",
      )
      .join("\n");
    const bitmap = async (name, locator) => {
      const png = path.join(out, name + ".png");
      if (locator) await locator.screenshot({ path: png });
      else await page.screenshot({ path: png });
      execFileSync("magick", [
        png,
        "-alpha",
        "off",
        "-type",
        "TrueColor",
        "BMP3:" + path.join(out, name + ".bmp"),
      ]);
    };
    for (const [i, poses] of (
      await page.evaluate(() => comicFrames)
    ).entries()) {
      await page.evaluate(
        (poses) =>
          document
            .querySelectorAll("[data-pose]")
            .forEach((el) =>
              el.classList.toggle("lit", poses.includes(el.dataset.pose)),
            ),
        poses,
      );
      await bitmap("comic" + i, page.locator(".scene"));
    }
    await page.addStyleTag({
      content: `
      #bank,#soundName,#status,#tempo,#patternNo,.transport [data-action=play] em,.pad strong{visibility:hidden}
      .dial i:after{visibility:hidden} .controls button::before{visibility:hidden}
      .mode[data-action=sound] .legend{color:var(--silk)}`,
    });
    await bitmap("face");
    // Fixed cells retain fractional font metrics; widths drive proportional layout.
    const font = await page.evaluate(() => {
      const canvas = document.createElement("canvas");
      canvas.width = 32 * 96;
      canvas.height = 40 * 5;
      const g = canvas.getContext("2d");
      g.fillStyle = "#fff";
      g.textBaseline = "middle";
      const widths = [];
      for (const [row, font] of [
        '600 12px "Space Grotesk"',
        '600 16px "Space Grotesk"',
        '500 11px "Space Grotesk"',
        "24px DSEG",
        "19px DSEG",
      ].entries()) {
        g.font = font;
        const w = [];
        for (let i = 0; i < 96; i++) {
          const ch = String.fromCharCode(32 + i);
          w.push(Math.ceil(g.measureText(ch).width));
          g.fillText(ch, 32 * i, 40 * row + 20);
        }
        widths.push(w);
      }
      return { widths, url: canvas.toDataURL() };
    });
    write("font.png", Buffer.from(font.url.split(",")[1], "base64"));
    execFileSync("magick", [
      path.join(out, "font.png"),
      "-depth",
      "8",
      "rgba:" + path.join(out, "font.rgba"),
    ]);
    header +=
      "\nstatic const int advances[][96]={" + rows(font.widths) + "};\n";
    const factory = vm.runInNewContext(
      fs.readFileSync(path.join(project, "audio.js"), "utf8") +
        "\nnew SamplerAudio()",
    );
    factory.context = {
      createBuffer: (_, n, sr) => {
        const data = new Float32Array(n);
        return { sampleRate: sr, length: n, getChannelData: () => data };
      },
    };
    const buffers = [],
      offsets = [],
      lengths = [];
    let samples = 0;
    for (let s = 0; s < 16; s++)
      for (let p = 0; p < 16; p++) {
        if (s < 8 && p) {
          offsets.push(offsets[offsets.length - 1]);
          lengths.push(lengths[lengths.length - 1]);
          continue;
        }
        const v = factory.source(s, p).getChannelData(0);
        offsets.push(samples);
        lengths.push(v.length);
        samples += v.length;
        buffers.push(Buffer.from(v.buffer));
      }
    write("factory.f32", Buffer.concat(buffers));
    header +=
      "static const int wave_offsets[]={" +
      offsets +
      "};\nstatic const int wave_lengths[]={" +
      lengths +
      "};\n";
    write("skin.h", header);
  } finally {
    await browser.close();
  }
}
prepare().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
