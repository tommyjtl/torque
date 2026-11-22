// Flatten the browser's actual meshes once on the host, batching by material and moving part.
const fs = require("node:fs"),
  path = require("node:path"),
  http = require("node:http");
const { chromium } = require("playwright");
const root = path.resolve(__dirname, ".."),
  out = path.join(__dirname, "build");
async function bake() {
  fs.mkdirSync(out, { recursive: true });
  const server = http.createServer((req, res) => {
    const name = new URL(req.url, "http://localhost").pathname;
    if (name === "/") {
      res.setHeader("Content-Type", "text/html");
      res.end("<title>BAP asset bake</title>");
      return;
    }
    if (
      !/^\/(inspect-model\.mjs|assets\/inspect\/[\w./-]+|assets\/SpaceGrotesk-Latin\.woff2)$/.test(
        name,
      ) ||
      name.includes("..")
    ) {
      res.writeHead(404).end();
      return;
    }
    const file = path.join(root, name);
    if (!fs.existsSync(file)) {
      res.writeHead(404).end();
      return;
    }
    res.setHeader(
      "Content-Type",
      {
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".png": "image/png",
        ".woff2": "font/woff2",
        ".json": "application/json",
      }[path.extname(file)] || "application/octet-stream",
    );
    fs.createReadStream(file).pipe(res);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  let browser;
  try {
    browser = await chromium.launch({ channel: "chrome" });
    const page = await browser.newPage();
    await page.goto("http://127.0.0.1:" + server.address().port);
    const model = await page.evaluate(async () => {
      const T = await import("/assets/inspect/vendor/three.module.min.js");
      const { buildHardware } = await import("/inspect-model.mjs");
      const font = new FontFace(
        "Space Grotesk",
        "url(/assets/SpaceGrotesk-Latin.woff2)",
      );
      document.fonts.add(await font.load());
      const scene = new T.Scene();
      const layout = await (await fetch("/assets/inspect/layout.json")).json();
      const face = await new T.TextureLoader().loadAsync(
        "/assets/inspect/silkscreen.png",
      );
      const lcd = new T.Texture();
      buildHardware(scene, layout, face, { texture: lcd });
      scene.updateMatrixWorld(true);
      const textures = [],
        groups = new Map();
      const keys = [
        "sound",
        "pattern",
        "bpm",
        "a",
        "b",
        "record",
        "fx",
        "play",
        "write",
      ];
      const pos = new T.Vector3(),
        norm = new T.Vector3(),
        normalMat = new T.Matrix3();
      function flatten(obj, world) {
        const m = obj.material,
          geo = obj.geometry,
          uv = geo.attributes.uv;
        let tex = 0;
        if (m.map === lcd) tex = -1;
        else if (m.map) {
          if (!textures.includes(m.map)) textures.push(m.map);
          tex = textures.indexOf(m.map) + 1;
        }
        const rotor = obj.parent.userData.encoder,
          pivot = rotor ? obj.parent.position : new T.Vector3();
        const key = obj.userData.indicator;
        const control = key
          ? key.startsWith("Pad ")
            ? Number(key.slice(4)) - 1
            : 16 + keys.indexOf(key)
          : -1;
        const groupKey = [m.uuid, rotor || "", control].join("/");
        if (!groups.has(groupKey))
          groups.set(groupKey, {
            tex,
            control,
            rotor: rotor === "a" ? 0 : rotor === "b" ? 1 : -1,
            pivot: [pivot.x, pivot.y],
            material: [
              ...m.color.toArray(),
              m.metalness || 0,
              m.roughness ?? 1,
              m.isMeshBasicMaterial ? 1 : 0,
            ],
            vertices: [],
          });
        const vertices = groups.get(groupKey).vertices;
        normalMat.getNormalMatrix(world);
        const count = geo.index
          ? geo.index.count
          : geo.attributes.position.count;
        for (let n = 0; n < count; n++) {
          const i = geo.index ? geo.index.getX(n) : n;
          pos
            .fromBufferAttribute(geo.attributes.position, i)
            .applyMatrix4(world);
          norm
            .fromBufferAttribute(geo.attributes.normal, i)
            .applyMatrix3(normalMat)
            .normalize();
          vertices.push(
            pos.x,
            pos.y,
            pos.z,
            norm.x,
            norm.y,
            norm.z,
            uv ? uv.getX(i) : 0,
            uv ? uv.getY(i) : 0,
          );
        }
      }
      scene.traverse((obj) => {
        if (!obj.isMesh) return;
        if (obj.isInstancedMesh) {
          for (let i = 0; i < obj.count; i++) {
            const matrix = new T.Matrix4();
            obj.getMatrixAt(i, matrix);
            flatten(obj, matrix.premultiply(obj.matrixWorld));
          }
        } else flatten(obj, obj.matrixWorld);
      });
      const chunks = [],
        parts = [];
      let first = 0;
      function encode(bytes) {
        let s = "";
        for (let i = 0; i < bytes.length; i += 16384)
          s += String.fromCharCode(...bytes.subarray(i, i + 16384));
        return btoa(s);
      }
      for (const { vertices, ...group } of groups.values()) {
        const count = vertices.length / 8;
        parts.push({ ...group, first, count });
        first += count;
        chunks.push(encode(new Uint8Array(new Float32Array(vertices).buffer)));
      }
      const images = textures.map((t) => {
        const c = document.createElement("canvas"),
          img = t.image;
        c.width = img.width;
        c.height = img.height;
        const g = c.getContext("2d");
        g.translate(0, c.height);
        g.scale(1, -1);
        g.drawImage(img, 0, 0);
        return {
          w: c.width,
          h: c.height,
          rgba: encode(g.getImageData(0, 0, c.width, c.height).data),
        };
      });
      return { parts, chunks, images, lcd: layout.lcd };
    });
    const i32 = (a) => Buffer.from(Int32Array.from(a).buffer),
      f32 = (a) => Buffer.from(Float32Array.from(a).buffer);
    const chunks = model.chunks.map((s) => Buffer.from(s, "base64"));
    const vertices = chunks.reduce((n, b) => n + b.length / 32, 0);
    const file = [
      Buffer.from("BAP3"),
      i32([1, vertices, model.parts.length, model.images.length]),
      f32(model.lcd),
    ];
    for (const p of model.parts)
      file.push(
        i32([p.first, p.count, p.tex, p.control, p.rotor]),
        f32([...p.pivot, ...p.material]),
      );
    file.push(...chunks);
    for (const t of model.images)
      file.push(i32([t.w, t.h]), Buffer.from(t.rgba, "base64"));
    fs.writeFileSync(path.join(out, "inspect.mesh"), Buffer.concat(file));
    console.log(
      vertices +
        " vertices, " +
        model.parts.length +
        " material batches, " +
        model.images.length +
        " textures",
    );
  } finally {
    await browser?.close();
    server.close();
  }
}
bake().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
