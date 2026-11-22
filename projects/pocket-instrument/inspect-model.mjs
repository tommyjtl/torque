import * as T from "./assets/inspect/vendor/three.module.min.js";

const root = new URL("assets/inspect/", import.meta.url);
const loadImage = async (url) => {
  const image = new Image();
  image.src = url;
  await image.decode();
  return image;
};

function roundedOutline(x, y, w, h, r, Path = T.Shape) {
  const s = new Path();
  s.moveTo(x + r, y);
  s.lineTo(x + w - r, y);
  s.quadraticCurveTo(x + w, y, x + w, y + r);
  s.lineTo(x + w, y + h - r);
  s.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  s.lineTo(x + r, y + h);
  s.quadraticCurveTo(x, y + h, x, y + h - r);
  s.lineTo(x, y + r);
  s.quadraticCurveTo(x, y, x + r, y);
  return s;
}
function canvasTexture(canvas) {
  const t = new T.CanvasTexture(canvas);
  t.colorSpace = T.SRGBColorSpace;
  return t;
}

// Draw the same LCD elements as the live instrument on the raised screen.
function makeLcd(layout, background, atlas) {
  const canvas = document.createElement("canvas");
  canvas.width = background.width;
  canvas.height = background.height;
  const ctx = canvas.getContext("2d");
  const texture = canvasTexture(canvas);
  const [ox, oy, w, h] = layout.lcd;
  const texts = layout.texts.map((entry) => ({
    ...entry,
    el: document.querySelector(entry.selector),
  }));
  const figures = [...document.querySelectorAll(".scene i")];
  const meter = document.querySelector("#strip");
  function update() {
    ctx.setTransform(canvas.width / w, 0, 0, canvas.height / h, 0, 0);
    ctx.globalAlpha = 1;
    ctx.drawImage(background, 0, 0, w, h);
    ctx.fillStyle = "#282829";
    ctx.textBaseline = "middle";
    for (const {
      el,
      rect: [x, y, , height],
      font,
      selector,
    } of texts) {
      ctx.font = font;
      ctx.textAlign = selector === "#status" ? "center" : "left";
      const dx = selector === "#status" ? w / 2 : x - ox;
      ctx.fillText(
        el.textContent,
        dx,
        y - oy + height / 2,
        selector === "#status" ? 125 : 120,
      );
    }
    layout.poses.forEach(([x, y, pw, ph], i) => {
      ctx.globalAlpha = figures[i].classList.contains("lit") ? 0.85 : 0.075;
      const sw = atlas.width / 4,
        sh = atlas.height / 2;
      ctx.drawImage(
        atlas,
        (i % 4) * sw,
        Math.floor(i / 4) * sh,
        sw,
        sh,
        x - ox,
        y - oy,
        pw,
        ph,
      );
    });
    ctx.globalAlpha = 1;
    const [x, y, mw, mh] = layout.meter;
    const bars = Math.round(
      (48 * (parseFloat(meter.style.getPropertyValue("--fill")) || 0)) / 100,
    );
    for (let i = 0; i < bars; i++)
      ctx.fillRect(x - ox + (i * mw) / 48, y - oy, (mw / 48) * 0.55, mh);
    texture.needsUpdate = true;
  }
  update();
  return { texture, update };
}

function rearPrint() {
  const c = document.createElement("canvas");
  c.width = 480;
  c.height = 640;
  const g = c.getContext("2d");
  g.fillStyle = "#202323";
  g.fillRect(0, 0, 480, 640);
  g.strokeStyle = "#454946";
  g.lineWidth = 1;
  // Etched signal traces with 45-degree bends and plated vias.
  for (let i = 0; i < 28; i++) {
    const x = 22 + (i % 14) * 31,
      y = 302 + (i % 7) * 13,
      side = i < 14 ? 1 : -1;
    const end = side > 0 ? 580 - (i % 4) * 16 : 397 + (i % 5) * 8;
    g.beginPath();
    g.moveTo(x, y);
    g.lineTo(x, y + 22);
    g.lineTo(x + side * 12, y + 34);
    g.lineTo(x + side * 12, end);
    g.stroke();
    g.fillStyle = "#9c8b60";
    g.beginPath();
    g.arc(x + side * 12, end, 2.5, 0, Math.PI * 2);
    g.fill();
  }
  g.fillStyle = "#d8ba78";
  g.font = "600 34px 'Space Grotesk',sans-serif";
  g.fillText("B.A.P.", 26, 333);
  g.fillStyle = "#d5d6cc";
  g.font = "16px 'Space Grotesk',sans-serif";
  g.fillText("Bureau of Accidental Percussion", 26, 357);
  g.font = "13px 'Space Grotesk',sans-serif";
  g.fillText("TORQUE   /   TQ–01", 26, 610);
  g.fillText("2 × AAA", 345, 292);
  return canvasTexture(c);
}

// Alternating radii form physical flutes, visible even in an edge-on silhouette.
function flutedShaft(radius, height) {
  const teeth = 32,
    sides = teeth * 2,
    positions = [],
    indices = [];
  const rings = [
    [0, 0.92],
    [1, 1],
    [height - 2, 1],
    [height, 0.95],
  ];
  for (const [z, scale] of rings) {
    for (let i = 0; i < sides; i++) {
      const theta = (i * 2 * Math.PI) / sides,
        r = radius * scale * (i % 2 ? 0.94 : 1);
      positions.push(Math.cos(theta) * r, Math.sin(theta) * r, z);
    }
  }
  for (let j = 0; j < rings.length - 1; j++)
    for (let i = 0; i < sides; i++) {
      const a = j * sides + i,
        b = j * sides + ((i + 1) % sides);
      indices.push(a, b, a + sides, b, b + sides, a + sides);
    }
  const geometry = new T.BufferGeometry();
  geometry.setAttribute("position", new T.Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  const faceted = geometry.toNonIndexed();
  geometry.dispose();
  faceted.computeVertexNormals();
  return faceted;
}

// The low board edge and the wire foot share a 13-degree support plane.
const restingTilt = T.MathUtils.degToRad(13);
const tabletopZ = (y) => -7 - (y + 320) * Math.tan(restingTilt);
export function buildHardware(scene, layout, front, lcd) {
  const mat = (color, metalness = 0, roughness = 0.54) =>
    new T.MeshStandardMaterial({ color, metalness, roughness });
  const pcb = mat(0x262825, 0.3, 0.57),
    dark = mat(0x161817, 0.16, 0.46),
    rubber = mat(0x232322, 0.02, 0.8);
  const tin = mat(0xd8d8d7, 0.58, 0.31),
    steel = mat(0x999d9e, 0.9, 0.27),
    gold = mat(0xc8a256, 0.62, 0.37),
    copper = mat(0x9a7559, 0.67, 0.39);
  const amber = mat(0xe68642, 0.25, 0.57),
    ledOff = mat(0x732e24, 0.1, 0.4),
    ledOn = new T.MeshBasicMaterial({ color: 0xff8055 });
  const boxGeo = new T.BoxGeometry(1, 1, 1),
    cylGeo = new T.CylinderGeometry(1, 1, 1, 40);
  const stampedPlate = new T.ExtrudeGeometry(
    roundedOutline(-0.48, -0.48, 0.96, 0.96, 0.065),
    {
      depth: 0.88,
      bevelEnabled: true,
      bevelSize: 0.02,
      bevelThickness: 0.06,
      bevelSegments: 2,
      curveSegments: 4,
    },
  ).translate(0, 0, -0.44);
  const plunger = new T.LatheGeometry(
    [
      [0, -0.5],
      [0.92, -0.5],
      [1, -0.34],
      [0.99, 0.24],
      [0.91, 0.42],
      [0.7, 0.5],
      [0, 0.54],
    ].map(([r, y]) => new T.Vector2(r, y)),
    32,
  );
  const batches = new Map(),
    temp = new T.Object3D();
  function part(
    geo,
    m,
    x,
    y,
    z,
    sx = 1,
    sy = 1,
    sz = 1,
    rx = 0,
    ry = 0,
    rz = 0,
  ) {
    temp.position.set(x, y, z);
    temp.rotation.set(rx, ry, rz);
    temp.scale.set(sx, sy, sz);
    temp.updateMatrix();
    let byMaterial = batches.get(geo);
    if (!byMaterial) batches.set(geo, (byMaterial = new Map()));
    let instances = byMaterial.get(m);
    if (!instances) byMaterial.set(m, (instances = []));
    instances.push(temp.matrix.clone());
  }
  const box = (m, x, y, z, w, h, d, rx = 0, ry = 0, rz = 0) =>
    part(boxGeo, m, x, y, z, w, h, d, rx, ry, rz);
  const disc = (m, x, y, z, r, d) =>
    part(cylGeo, m, x, y, z, r, d, r, Math.PI / 2);
  function mesh(geometry, material, x = 0, y = 0, z = 0) {
    const obj = new T.Mesh(geometry, material);
    obj.position.set(x, y, z);
    scene.add(obj);
    return obj;
  }
  function plate(shape, z, depth, material, bevel = 1) {
    mesh(
      new T.ExtrudeGeometry(shape, {
        depth,
        bevelEnabled: true,
        bevelThickness: bevel,
        bevelSize: bevel,
        bevelSegments: 2,
        curveSegments: 8,
      }),
      material,
      0,
      0,
      z,
    );
  }
  function plane(texture, w, h, x, y, z, back = false) {
    const face = mesh(
      new T.PlaneGeometry(w, h),
      new T.MeshBasicMaterial({
        map: texture,
        transparent: true,
        alphaTest: 0.4,
        toneMapped: false,
      }),
      x,
      y,
      z,
    );
    if (back) face.rotation.y = Math.PI;
  }
  plate(roundedOutline(-239, -319, 478, 638, 11), -6, 6, pcb, 1.1);
  plane(front, 480, 640, 0, 0, 1.2);
  plane(rearPrint(), 475, 630, 0, 0, -7.4, true);
  // Open keyring tab is continuous with the board laminate.
  const tab = roundedOutline(-66, 299, 132, 56, 25);
  tab.holes.push(roundedOutline(-48, 321, 96, 18, 8, T.Path));
  plate(tab, -5.9, 5.9, pcb, 0.9);

  const [lx, ly, lw, lh] = layout.lcd,
    sx = lx + lw / 2 - 240,
    sy = 320 - ly - lh / 2;
  box(dark, sx, sy, 4, lw + 5, lh + 5, 8);
  box(steel, sx, sy, 8, lw, lh, 2);
  plane(lcd.texture, lw, lh, sx, sy, 9.2);
  for (let x = sx - lw * 0.4; x < sx + lw * 0.4; x += 11) {
    box(tin, x, sy + lh / 2 + 3, 3, 3, 7, 4);
    box(tin, x, sy - lh / 2 + 1, 3, 3, 7, 4);
  }
  const shaftGeometry = flutedShaft(13.7, 39);
  const knurl = mat(0x464946, 0.55, 0.37);
  const collar = new T.CylinderGeometry(18, 18, 4, 6);
  const lamps = [],
    dials = [];
  for (const {
    key,
    rect: [bx, by, w, h],
  } of layout.controls) {
    const x = bx + w / 2 - 240,
      y = 320 - by - h / 2;
    const dial = key === "a" || key === "b";
    const rim = key === "sound" || key === "record" ? amber : tin;
    if (dial) {
      // Cartridge, metal lid, retaining nut, tall knurled shaft and silver end cap.
      for (const sign of [-1, 1])
        for (const side of [-1, 1])
          box(tin, x + sign * w * 0.36, y + side * h * 0.32, 4.5, 6, 7, 8);
      part(stampedPlate, dark, x, y, 13, w * 0.9, h * 0.86, 19);
      part(stampedPlate, steel, x, y, 23, w * 0.93, h * 0.89, 3);
      part(collar, tin, x, y, 26, 1, 1, 1, Math.PI / 2);
      disc(dark, x, y, 29, 14.5, 3);
      const rotor = new T.Group();
      rotor.position.set(x, y, 30);
      rotor.userData.encoder = key;
      scene.add(rotor);
      rotor.add(new T.Mesh(shaftGeometry, knurl));
      const cap = new T.Mesh(new T.CylinderGeometry(13.2, 13.7, 3, 40), tin);
      cap.rotation.x = Math.PI / 2;
      cap.position.z = 39;
      rotor.add(cap);
      const index = new T.Mesh(new T.BoxGeometry(2.1, 14, 1), dark);
      index.position.z = 40.6;
      rotor.add(index);
      dials.push({ key, rotor });
      for (const sign of [-1, 1])
        disc(dark, x + sign * w * 0.36, y - sign * h * 0.33, 25.1, 2.5, 1);
    } else {
      disc(rim, x, y, 3, w * 0.48, 3);
      box(rubber, x, y, 5, w * 0.78, h * 0.89, 7);
      part(stampedPlate, tin, x, y, 10, w * 0.76, h * 0.86, 5);
      for (const sign of [-1, 1])
        for (const side of [-1, 1]) {
          box(steel, x + side * w * 0.22, y + sign * h * 0.43, 7, 4, 5, 9);
        }
      part(plunger, rubber, x, y, 16.8, w * 0.2, 10, w * 0.2, Math.PI / 2);
    }
    const lamp = mesh(
      new T.BoxGeometry(7, 3.5, 2.2),
      ledOff,
      x,
      320 - by + 3.5,
      2.3,
    );
    lamp.userData.indicator = key;
    lamps.push({ key, lamp });
  }
  // Side-entry jack barrels have a dark bore, a machined collar and board legs.
  for (const side of [-1, 1]) {
    box(dark, side * 216, 246, -11, 44, 32, 21);
    part(cylGeo, steel, side * 238, 246, -11, 12, 7, 12, 0, 0, Math.PI / 2);
    part(cylGeo, rubber, side * 242, 246, -11, 8.5, 1, 8.5, 0, 0, Math.PI / 2);
    for (const y of [227, 265]) box(tin, side * 221, y, -5, 21, 5, 5);
  }
  // Two exposed cells with alternating terminals; printed sleeves follow the cylinder.
  const cellCanvas = document.createElement("canvas");
  cellCanvas.width = 512;
  cellCanvas.height = 512;
  const g = cellCanvas.getContext("2d");
  g.fillStyle = "#292d2d";
  g.fillRect(0, 0, 512, 512);
  g.fillStyle = "#b69a63";
  g.fillRect(0, 0, 512, 60);
  g.fillStyle = "#a5aba6";
  g.fillRect(0, 500, 512, 12);
  g.translate(256, 250);
  g.rotate(-Math.PI / 2);
  g.fillStyle = "#dddcd1";
  g.font = "550 36px 'Space Grotesk',sans-serif";
  g.fillText("AAA   LR03   1.5 V", -142, 0);
  const sleeve = mat(0xffffff, 0.52, 0.42);
  sleeve.map = canvasTexture(cellCanvas);
  box(dark, 0, 144, -14, 395, 148, 16);
  for (const [i, y] of [110, 178].entries()) {
    part(
      cylGeo,
      sleeve,
      0,
      y,
      -46,
      31,
      330,
      31,
      0,
      0,
      i === 0 ? Math.PI / 2 : -Math.PI / 2,
    );
    for (const side of [-1, 1]) {
      part(cylGeo, tin, side * 166, y, -46, 29, 4, 29, 0, 0, Math.PI / 2);
      box(dark, side * 182, y, -32, 12, 67, 52);
    }
    part(
      cylGeo,
      gold,
      (i === 0 ? -1 : 1) * 171,
      y,
      -46,
      12,
      7,
      12,
      0,
      0,
      Math.PI / 2,
    );
  }
  // Fold-out wire stand. Cylinders follow the wire between the hinge points.
  function wire(a, b, r) {
    const v = new T.Vector3().subVectors(b, a);
    const rod = mesh(new T.CylinderGeometry(r, r, v.length(), 12), steel);
    rod.position.copy(a).lerp(b, 0.5);
    rod.quaternion.setFromUnitVectors(new T.Vector3(0, 1, 0), v.normalize());
  }
  // Pivot outside the cell end plates. The bail swings toward the hanger;
  // its crossbar clears the far side of the battery cradle.
  const footY = 258,
    footZ = tabletopZ(footY) + 3 / Math.cos(restingTilt);
  const points = [
    [-185, 101, -33],
    [-198, 101, -33],
    [-198, 115, -44],
    [-189, footY, footZ],
    [189, footY, footZ],
    [198, 115, -44],
    [198, 101, -33],
    [185, 101, -33],
  ].map((p) => new T.Vector3(...p));
  for (let i = 1; i < points.length; i++) wire(points[i - 1], points[i], 3);
  for (const p of points.slice(1, -1))
    mesh(new T.SphereGeometry(3, 12, 8), steel, p.x, p.y, p.z);
  for (const side of [-1, 1]) {
    box(dark, side * 188, 101, -22, 13, 20, 34);
    part(cylGeo, tin, side * 193, 101, -33, 5, 6, 5, 0, 0, Math.PI / 2);
  }
  // IC, solder pads and passives on the reverse side.
  box(dark, -116, -71, -12, 61, 55, 9);
  for (let i = 0; i < 10; i++)
    for (const side of [-1, 1])
      box(tin, -143 + 6 * i, -71 + side * 30, -10, 2.5, 7, 3);
  for (let i = 0; i < 36; i++) {
    const x = 84 + (i % 6) * 13,
      y = -72 - Math.floor(i / 6) * 17;
    box(tin, x, y, -9, 9, 4, 3);
    box(i % 4 === 0 ? copper : dark, x, y, -10, 5, 4, 3);
  }
  for (let i = 0; i < 18; i++) disc(gold, -196 + i * 13, -260, -8, 3.8, 1);
  for (const [geo, materials] of batches)
    for (const [material, items] of materials) {
      const group = new T.InstancedMesh(geo, material, items.length);
      items.forEach((m, i) => group.setMatrixAt(i, m));
      scene.add(group);
    }
  return function syncControls() {
    for (const { key, lamp } of lamps) {
      const btn = key.startsWith("Pad ")
        ? document.querySelectorAll(".pad")[Number(key.slice(4)) - 1]
        : document.querySelector('[data-action="' + key + '"]');
      lamp.material =
        btn?.matches("[aria-pressed=true],.hit,.key-held") ||
        btn?.parentElement.classList.contains("record-slots")
          ? ledOn
          : ledOff;
    }
    for (const { key, rotor } of dials) {
      const knob = document.querySelector('[data-action="' + key + '"] i');
      rotor.rotation.z = -T.MathUtils.degToRad(
        parseFloat(knob.style.getPropertyValue("--angle")) || 0,
      );
    }
  };
}

export async function createInspection(canvas, onLost) {
  const renderer = new T.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: true,
    powerPreference: "low-power",
  });
  const scene = new T.Scene(),
    camera = new T.PerspectiveCamera(35, 1, 2, 6000);
  let running = false,
    raf = 0,
    dirty = true,
    lastSync = 0;
  const faceOn = { yaw: 0, pitch: 0, up: 0, zoom: 1 };
  const placed = {
    yaw: 1.32,
    pitch: 0.19,
    up: Math.PI / 2 - restingTilt,
    zoom: 0.93,
  };
  const pose = { ...faceOn };
  const target = new T.Vector3(0, 0, 0);
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  let transition = null;
  function moveTo(end, ms, name, done) {
    const start = { ...pose };
    // Return via the nearest azimuth, even after several full revolutions.
    start.yaw =
      end.yaw +
      Math.atan2(Math.sin(start.yaw - end.yaw), Math.cos(start.yaw - end.yaw));
    transition = {
      start,
      end,
      ms: reduced.matches ? 0 : ms,
      last: null,
      elapsed: 0,
      name,
      done,
    };
    canvas.dataset.pose = name;
    schedule();
  }
  function advance(time) {
    if (!transition) return;
    const tr = transition;
    tr.elapsed += tr.last === null ? 0 : Math.min(50, time - tr.last);
    tr.last = time;
    const t = tr.ms ? Math.min(1, tr.elapsed / tr.ms) : 1;
    const v = t * t * (3 - 2 * t);
    for (const k of ["yaw", "pitch", "up", "zoom"])
      pose[k] = T.MathUtils.lerp(tr.start[k], tr.end[k], v);
    if (t === 1) {
      transition = null;
      canvas.dataset.pose = tr.name === "returning" ? "front" : "orbit";
      tr.done?.();
    }
  }
  const softbox = document.createElement("canvas");
  softbox.width = 512;
  softbox.height = 256;
  const g = softbox.getContext("2d");
  g.fillStyle = "#757570";
  g.fillRect(0, 0, 512, 256);
  g.fillStyle = "#fafafa";
  g.fillRect(30, 21, 130, 83);
  g.fillRect(310, 10, 52, 160);
  g.fillStyle = "#242625";
  g.fillRect(160, 158, 120, 86);
  const environment = canvasTexture(softbox);
  environment.mapping = T.EquirectangularReflectionMapping;
  scene.environment = environment;
  scene.add(new T.HemisphereLight(0xfff7e9, 0x828b96, 1.55));
  const key = new T.DirectionalLight(0xfff7e9, 2.5);
  key.position.set(-450, 700, 900);
  scene.add(key);
  let syncControls, lcd;
  try {
    const [layout, face, bg, atlas] = await Promise.all([
      fetch(new URL("layout.json", root)).then((r) => {
        if (!r.ok) throw Error("Missing model layout");
        return r.json();
      }),
      loadImage(new URL("silkscreen.png", root)),
      loadImage(new URL("lcd.png", root)),
      loadImage(new URL("assets/ringside-poses.png", import.meta.url)),
    ]);
    const texture = canvasTexture(face);
    texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
    lcd = makeLcd(layout, bg, atlas);
    lcd.texture.anisotropy = texture.anisotropy;
    syncControls = buildHardware(scene, layout, texture, lcd);
  } catch (error) {
    renderer.dispose();
    throw error;
  }
  // The lower board edge and the foot of the stand define the tabletop.
  const shade = document.createElement("canvas");
  shade.width = shade.height = 128;
  const sg = shade.getContext("2d");
  const grad = sg.createRadialGradient(64, 64, 8, 64, 64, 63);
  grad.addColorStop(0, "rgba(23,23,21,.52)");
  grad.addColorStop(0.65, "rgba(23,23,21,.22)");
  grad.addColorStop(1, "rgba(23,23,21,0)");
  sg.fillStyle = grad;
  sg.fillRect(0, 0, 128, 128);
  const shadow = new T.Mesh(
    new T.PlaneGeometry(680, 905),
    new T.MeshBasicMaterial({
      map: canvasTexture(shade),
      transparent: true,
      depthWrite: false,
      toneMapped: false,
    }),
  );
  shadow.rotation.x = -restingTilt;
  shadow.position.set(0, 0, tabletopZ(0) - 0.8);
  scene.add(shadow);
  const extents = [];
  for (const x of [-243, 243])
    for (const y of [-321, 356])
      for (const z of [tabletopZ(258) - 1, 72])
        extents.push(new T.Vector3(x, y, z));
  const right = new T.Vector3(),
    vertical = new T.Vector3();
  function draw(time) {
    raf = 0;
    if (!running) return;
    const width = canvas.clientWidth,
      height = canvas.clientHeight;
    if (!width || !height) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (renderer.getPixelRatio() !== dpr) renderer.setPixelRatio(dpr);
    if (
      canvas.width !== Math.floor(width * dpr) ||
      canvas.height !== Math.floor(height * dpr)
    )
      renderer.setSize(width, height, false);
    camera.aspect = width / height;
    advance(time);
    if (!running) return;
    const { yaw, pitch, up, zoom } = pose;
    const tanV = Math.tan(T.MathUtils.degToRad(camera.fov / 2));
    const heightAxis = Math.sin(pitch),
      forward = Math.cos(yaw) * Math.cos(pitch);
    camera.up.set(0, Math.cos(up), Math.sin(up));
    camera.position.set(
      Math.sin(yaw) * Math.cos(pitch),
      heightAxis * Math.cos(up) - forward * Math.sin(up),
      heightAxis * Math.sin(up) + forward * Math.cos(up),
    );
    right.crossVectors(camera.up, camera.position).normalize();
    vertical.crossVectors(camera.position, right);
    let fit = 0;
    for (const corner of extents) {
      fit = Math.max(
        fit,
        corner.dot(camera.position) +
          1.08 *
            Math.max(
              Math.abs(corner.dot(right)) / (tanV * camera.aspect),
              Math.abs(corner.dot(vertical)) / tanV,
            ),
      );
    }
    // At the start and finish the printed panel registers to the flat view.
    const distance =
      T.MathUtils.lerp(320 / tanV, fit, Math.min(1, up / placed.up)) * zoom;
    shadow.material.opacity = Math.min(1, up);
    camera.position.multiplyScalar(distance).add(target);
    camera.lookAt(target);
    camera.updateProjectionMatrix();
    if (dirty && time - lastSync >= 32) {
      lcd.update();
      syncControls();
      lastSync = time;
      dirty = false;
    }
    renderer.render(scene, camera);
    if (dirty || transition) schedule();
  }
  function schedule() {
    if (running && !raf) raf = requestAnimationFrame(draw);
  }
  const observer = new MutationObserver(() => {
    dirty = true;
    schedule();
  });
  const resize = new ResizeObserver(schedule);
  let drag = null;
  canvas.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || drag || transition?.name === "returning") return;
    drag = { id: e.pointerId, x: e.clientX, y: e.clientY };
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointermove", (e) => {
    if (drag?.id !== e.pointerId || transition?.name === "returning") return;
    if (e.clientX === drag.x && e.clientY === drag.y) return;
    transition = null;
    canvas.dataset.pose = "orbit";
    pose.yaw -= (e.clientX - drag.x) * 0.009;
    pose.pitch = T.MathUtils.clamp(
      pose.pitch + (e.clientY - drag.y) * 0.009,
      -1.48,
      1.48,
    );
    drag.x = e.clientX;
    drag.y = e.clientY;
    schedule();
  });
  canvas.addEventListener("lostpointercapture", () => {
    drag = null;
  });
  canvas.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      if (transition?.name === "returning") return;
      transition = null;
      pose.zoom = T.MathUtils.clamp(
        pose.zoom * Math.exp(T.MathUtils.clamp(e.deltaY, -200, 200) * 0.001),
        0.8,
        2.45,
      );
      schedule();
    },
    { passive: false },
  );
  canvas.addEventListener("keydown", (e) => {
    const dirs = {
      ArrowLeft: [-0.17, 0],
      ArrowRight: [0.17, 0],
      ArrowUp: [0, 0.17],
      ArrowDown: [0, -0.17],
      Home: [0, 0],
    };
    if (!Object.hasOwn(dirs, e.code)) return;
    e.preventDefault();
    if (transition?.name === "returning") return;
    transition = null;
    if (e.code === "Home") {
      moveTo({ ...faceOn, zoom: 1.22 }, 420, "moving");
    } else {
      pose.yaw += dirs[e.code][0];
      pose.pitch = T.MathUtils.clamp(pose.pitch + dirs[e.code][1], -1.48, 1.48);
    }
    schedule();
  });
  canvas.addEventListener("webglcontextlost", (e) => {
    e.preventDefault();
    running = false;
    observer.disconnect();
    resize.disconnect();
    onLost();
  });
  return {
    show() {
      running = true;
      dirty = true;
      Object.assign(pose, faceOn);
      moveTo(placed, 900, "entering");
      observer.observe(document.querySelector(".board"), {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: ["class", "style", "aria-pressed"],
      });
      resize.observe(canvas);
      schedule();
    },
    returnToPanel(done) {
      drag = null;
      moveTo(faceOn, 520, "returning", done);
    },
    hide() {
      transition = null;
      running = false;
      observer.disconnect();
      resize.disconnect();
      cancelAnimationFrame(raf);
      raf = 0;
      drag = null;
    },
  };
}
